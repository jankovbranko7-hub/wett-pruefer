from __future__ import annotations
import json, math
from dataclasses import dataclass
from pathlib import Path
from config import LAST_N_MATCHES, MAX_GOALS, MIN_MATCHES_FULL_WEIGHT, SHRINKAGE_GAMES

_CAL = None

def _calibration():
    global _CAL
    if _CAL is None:
        _CAL = json.loads((Path(__file__).resolve().parent / "calibration.json").read_text(encoding="utf-8"))
    return _CAL

def calibrate_prob(p: float, market: str) -> float:
    key = "over_map" if market in ("over", "over25", "under", "under25") else "btts_map"
    table = _calibration()[key]
    for row in table:
        if row["lo"] <= p < row["hi"]:
            return float(row["actual"])
    return float(table[-1]["actual"])

def _poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)

def market_probs(lam_h: float, lam_a: float):
    mx = MAX_GOALS
    ph = [_poisson(i, lam_h) for i in range(mx + 1)]
    pa = [_poisson(j, lam_a) for j in range(mx + 1)]
    p_home = p_draw = p_away = p_over = p_btts = 0.0
    for i in range(mx + 1):
        for j in range(mx + 1):
            p = ph[i] * pa[j]
            if i > j: p_home += p
            elif i == j: p_draw += p
            else: p_away += p
            if i + j >= 3: p_over += p
            if i >= 1 and j >= 1: p_btts += p
    return {"home": p_home, "draw": p_draw, "away": p_away, "over25": p_over, "under25": 1 - p_over, "btts_yes": p_btts, "btts_no": 1 - p_btts}

@dataclass
class TeamRates:
    team_id: int
    name: str
    games: int
    scored_avg: float
    conceded_avg: float
    xg_for_avg: float | None
    xg_against_avg: float | None

def _is_complete(match: dict) -> bool:
    return str(match.get("status") or "").lower() == "complete"

def team_rates(matches, team_id, name, venue):
    rows = []
    for m in matches:
        if not _is_complete(m):
            continue
        hid, aid = int(m.get("homeID") or 0), int(m.get("awayID") or 0)
        if venue == "home" and hid != team_id: continue
        if venue == "away" and aid != team_id: continue
        if venue == "any" and team_id not in (hid, aid): continue
        rows.append(m)
    rows.sort(key=lambda x: int(x.get("date_unix") or 0), reverse=True)
    rows = rows[:LAST_N_MATCHES]
    scored = conceded = xgf = xga = 0.0
    xg_n = 0
    for m in rows:
        hid = int(m.get("homeID") or 0)
        is_home = hid == team_id
        gf = float(m.get("homeGoalCount") if is_home else m.get("awayGoalCount") or 0)
        ga = float(m.get("awayGoalCount") if is_home else m.get("homeGoalCount") or 0)
        scored += gf; conceded += ga
        xf = m.get("team_a_xg" if is_home else "team_b_xg")
        xa = m.get("team_b_xg" if is_home else "team_a_xg")
        try:
            xgf += float(xf or 0); xga += float(xa or 0); xg_n += 1
        except (TypeError, ValueError):
            pass
    n = max(len(rows), 1)
    return TeamRates(team_id, name, len(rows), scored / n if rows else 0.0, conceded / n if rows else 0.0, (xgf / xg_n) if xg_n else None, (xga / xg_n) if xg_n else None)

def league_averages(matches):
    done = [m for m in matches if _is_complete(m)]
    if not done:
        return 1.35, 1.15, 2.50
    hg = sum(float(m.get("homeGoalCount") or 0) for m in done) / len(done)
    ag = sum(float(m.get("awayGoalCount") or 0) for m in done) / len(done)
    return hg, ag, hg + ag

def shrink(value, league_avg, games):
    if games >= MIN_MATCHES_FULL_WEIGHT:
        return value
    w = games / float(SHRINKAGE_GAMES)
    return w * value + (1.0 - w) * league_avg

def expected_goals(home, away, league_home_avg, league_away_avg):
    def attack(team, venue_avg):
        raw = team.xg_for_avg if team.xg_for_avg and team.xg_for_avg > 0.15 else team.scored_avg
        return shrink(raw or venue_avg, venue_avg, team.games)
    def defense(team, venue_avg):
        raw = team.xg_against_avg if team.xg_against_avg and team.xg_against_avg > 0.15 else team.conceded_avg
        return shrink(raw if raw is not None else venue_avg, venue_avg, team.games)
    h_att, h_def = attack(home, league_home_avg), defense(home, league_away_avg)
    a_att, a_def = attack(away, league_away_avg), defense(away, league_home_avg)
    lam_h = min(max(h_att * a_def / max(league_home_avg, 0.3), 0.15), 4.2)
    lam_a = min(max(a_att * h_def / max(league_away_avg, 0.3), 0.15), 4.2)
    return lam_h, lam_a
