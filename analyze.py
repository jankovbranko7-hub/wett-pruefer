from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from rapidfuzz import fuzz
from config import CUP_HINTS, ENABLE_1X2, THRESHOLD_1X2
from footystats import FootyStats
from model import calibrate_prob, expected_goals, league_averages, market_probs, team_rates

@dataclass
class Verdict:
    market: str
    pick: str | None
    probability: float
    reason: str

def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("-", " ").split())

def parse_query(query: str):
    raw = query.strip()
    for sep in (" - ", " – ", " vs ", " VS ", " gegen ", " v "):
        if sep.lower() in raw.lower():
            idx = raw.lower().find(sep.lower())
            return raw[:idx].strip(), raw[idx + len(sep):].strip()
    parts = raw.split()
    if len(parts) >= 2:
        mid = len(parts) // 2
        return " ".join(parts[:mid]), " ".join(parts[mid:])
    raise ValueError("Zwei Teams nennen.")

def _is_cup(league_name: str) -> bool:
    n = league_name.lower()
    return any(h in n for h in CUP_HINTS)

def find_match(api: FootyStats, home_q: str, away_q: str):
    seasons = api.latest_seasons(chosen_only=True) or api.latest_seasons(chosen_only=False)
    candidates = []
    now = int(datetime.now(timezone.utc).timestamp())
    for season in seasons:
        matches = api.league_matches(season["season_id"])
        for m in matches or []:
            h, a = m.get("home_name") or "", m.get("away_name") or ""
            if not h or not a:
                continue
            score = (fuzz.token_set_ratio(_norm(home_q), _norm(h)) + fuzz.token_set_ratio(_norm(away_q), _norm(a))) / 2.0
            ts = int(m.get("date_unix") or 0)
            if ts >= now - 3 * 3600:
                score += 4
            if score >= 72:
                candidates.append((score, m, season, matches))
    if not candidates:
        raise ValueError(f"Kein Spiel gefunden fuer {home_q} vs {away_q}")
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2], candidates[0][3]

def decide(probs, *, cup=False, n_home=0, n_away=0):
    out = []
    over_raw, btts_raw = probs["over25"], probs["btts_yes"]
    over_c = calibrate_prob(over_raw, "over")
    btts_c = calibrate_prob(btts_raw, "btts")
    thin = cup or n_home < 4 or n_away < 4
    if not thin and over_c >= 0.555 and over_raw >= 0.62:
        out.append(Verdict("Over/Under 2.5", "Over 2.5", over_c, f"geeicht {over_c:.0%} (roh {over_raw:.0%})"))
    elif not thin and (1 - over_c) >= 0.51 and over_raw <= 0.42:
        out.append(Verdict("Over/Under 2.5", "Under 2.5", 1 - over_c, f"geeicht {1-over_c:.0%} (roh {over_raw:.0%})"))
    else:
        out.append(Verdict("Over/Under 2.5", None, over_c, f"skip geeicht Over {over_c:.0%} (roh {over_raw:.0%})"))
    if not thin and btts_c >= 0.570 and btts_raw >= 0.62:
        out.append(Verdict("BTTS", "BTTS Ja", btts_c, f"geeicht {btts_c:.0%} (roh {btts_raw:.0%})"))
    elif not thin and (1 - btts_c) >= 0.50 and btts_raw <= 0.42:
        out.append(Verdict("BTTS", "BTTS Nein", 1 - btts_c, f"geeicht {1-btts_c:.0%} (roh {btts_raw:.0%})"))
    else:
        out.append(Verdict("BTTS", None, btts_c, f"skip geeicht Ja {btts_c:.0%} (roh {btts_raw:.0%})"))
    if ENABLE_1X2:
        best = max((("Heim", probs["home"]), ("Unentschieden", probs["draw"]), ("Auswaerts", probs["away"])), key=lambda x: x[1])
        out.append(Verdict("1X2", best[0] if best[1] >= THRESHOLD_1X2 and best[0] != "Unentschieden" else None, best[1], "1X2"))
    else:
        out.append(Verdict("1X2", None, max(probs["home"], probs["draw"], probs["away"]), "aus"))
    return out

def analyze(api: FootyStats, query: str) -> str:
    home_q, away_q = parse_query(query)
    match, season, matches = find_match(api, home_q, away_q)
    home_id, away_id = int(match["homeID"]), int(match["awayID"])
    home_name, away_name = match.get("home_name") or home_q, match.get("away_name") or away_q
    league = season.get("name") or ""
    cup = _is_cup(league)
    home = team_rates(matches, home_id, home_name, "home" if not cup else "any")
    away = team_rates(matches, away_id, away_name, "away" if not cup else "any")
    lg_h, lg_a, lg_tot = league_averages(matches)
    lam_h, lam_a = expected_goals(home, away, lg_h, lg_a)
    try:
        pre_h, pre_a = float(match.get("team_a_xg_prematch") or 0), float(match.get("team_b_xg_prematch") or 0)
        if pre_h >= 0.3 and pre_a >= 0.3:
            lam_h = 0.55 * lam_h + 0.45 * pre_h
            lam_a = 0.55 * lam_a + 0.45 * pre_a
    except (TypeError, ValueError):
        pass
    probs = market_probs(lam_h, lam_a)
    verdicts = decide(probs, cup=cup, n_home=home.games, n_away=away.games)
    kick = ""
    if match.get("date_unix"):
        kick = datetime.fromtimestamp(int(match["date_unix"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"{home_name} – {away_name}", f"Wettbewerb: {league}", f"Anstoss: {kick} | {match.get('status')}", f"Tore erwartet: {lam_h:.2f} / {lam_a:.2f} (Liga {lg_tot:.2f})", ""]
    for v in verdicts:
        lines.append(f"{v.market:16} {(v.pick or 'skip'):12} {v.probability:5.0%}  {v.reason}")
    lines.append(f"Roh Over {probs['over25']:.0%} BTTS {probs['btts_yes']:.0%} | geeicht Over {calibrate_prob(probs['over25'],'over'):.0%} BTTS {calibrate_prob(probs['btts_yes'],'btts'):.0%}")
    return "\n".join(lines)
