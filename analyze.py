from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from rapidfuzz import fuzz
from config import CUP_HINTS
from footystats import FootyStats
from model import calibrate_prob, expected_goals, league_averages, market_probs, team_rates

# Aus backtest_50_ligen: Markt-implied Over >= 0.58 -> real ~63 %.
# Modell allein roh>=0.62 -> real ~54 %. Modell gegen Markt -> ~46 %.
BOOK_OVER = 0.58
BOOK_BTTS = 0.58

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
    for sep in (" - ", " \u2013 ", " vs ", " VS ", " gegen ", " v "):
        if sep.lower() in raw.lower():
            idx = raw.lower().find(sep.lower())
            return raw[:idx].strip(), raw[idx + len(sep):].strip()
    parts = raw.split()
    if len(parts) >= 2:
        mid = len(parts) // 2
        return " ".join(parts[:mid]), " ".join(parts[mid:])
    raise ValueError("Zwei Teams nennen.")

def _is_cup(league_name: str) -> bool:
    return any(h in league_name.lower() for h in CUP_HINTS)

def _implied(odds) -> float | None:
    try:
        q = float(odds)
    except (TypeError, ValueError):
        return None
    if q <= 1.01:
        return None
    return 1.0 / q

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

def decide(probs, *, cup=False, n_home=0, n_away=0, imp_over=None, imp_btts=None):
    out = []
    over_raw, btts_raw = probs["over25"], probs["btts_yes"]
    over_c = calibrate_prob(over_raw, "over")
    btts_c = calibrate_prob(btts_raw, "btts")
    thin = cup or n_home < 4 or n_away < 4
    book_over_ok = imp_over is None or imp_over >= BOOK_OVER
    book_btts_ok = imp_btts is None or imp_btts >= BOOK_BTTS
    book_under_ok = imp_over is None or (1 - imp_over) >= BOOK_OVER
    book_bno_ok = imp_btts is None or (1 - imp_btts) >= BOOK_BTTS

    if not thin and over_c >= 0.555 and over_raw >= 0.62 and book_over_ok:
        out.append(Verdict("Over 2.5", "Over 2.5", over_c, f"roh {over_raw:.0%} | Markt {imp_over:.0%}" if imp_over else f"roh {over_raw:.0%}"))
    elif not thin and (1 - over_c) >= 0.51 and over_raw <= 0.42 and book_under_ok:
        out.append(Verdict("Under 2.5", "Under 2.5", 1 - over_c, f"roh {over_raw:.0%}"))
    else:
        reason = f"roh {over_raw:.0%}"
        if imp_over is not None:
            reason += f" | Markt {imp_over:.0%}"
        out.append(Verdict("Over 2.5", None, over_c, reason))

    if not thin and btts_c >= 0.570 and btts_raw >= 0.62 and book_btts_ok:
        out.append(Verdict("BTTS Ja", "BTTS Ja", btts_c, f"roh {btts_raw:.0%} | Markt {imp_btts:.0%}" if imp_btts else f"roh {btts_raw:.0%}"))
    elif not thin and (1 - btts_c) >= 0.50 and btts_raw <= 0.42 and book_bno_ok:
        out.append(Verdict("BTTS Nein", "BTTS Nein", 1 - btts_c, f"roh {btts_raw:.0%}"))
    else:
        reason = f"roh {btts_raw:.0%}"
        if imp_btts is not None:
            reason += f" | Markt {imp_btts:.0%}"
        out.append(Verdict("BTTS Ja", None, btts_c, reason))
    return out

def _bundle(api, query):
    home_q, away_q = parse_query(query)
    match, season, matches = find_match(api, home_q, away_q)
    home_id, away_id = int(match["homeID"]), int(match["awayID"])
    home_name = match.get("home_name") or home_q
    away_name = match.get("away_name") or away_q
    league = season.get("name") or ""
    cup = _is_cup(league)
    home = team_rates(matches, home_id, home_name, "home" if not cup else "any")
    away = team_rates(matches, away_id, away_name, "away" if not cup else "any")
    lg_h, lg_a, lg_tot = league_averages(matches)
    lam_h, lam_a = expected_goals(home, away, lg_h, lg_a)
    try:
        pre_h = float(match.get("team_a_xg_prematch") or 0)
        pre_a = float(match.get("team_b_xg_prematch") or 0)
        if pre_h >= 0.3 and pre_a >= 0.3:
            lam_h = 0.55 * lam_h + 0.45 * pre_h
            lam_a = 0.55 * lam_a + 0.45 * pre_a
    except (TypeError, ValueError):
        pass
    probs = market_probs(lam_h, lam_a)
    imp_over = _implied(match.get("odds_ft_over25"))
    imp_btts = _implied(match.get("odds_btts_yes"))
    verdicts = decide(
        probs, cup=cup, n_home=home.games, n_away=away.games,
        imp_over=imp_over, imp_btts=imp_btts,
    )
    kick = ""
    if match.get("date_unix"):
        kick = datetime.fromtimestamp(int(match["date_unix"]), tz=timezone.utc).strftime("%d.%m. %H:%M")
    return {
        "spiel": f"{home_name} vs {away_name}",
        "liga": league,
        "kick": kick,
        "verdicts": verdicts,
        "over_raw": probs["over25"],
        "over_c": calibrate_prob(probs["over25"], "over"),
        "btts_raw": probs["btts_yes"],
        "btts_c": calibrate_prob(probs["btts_yes"], "btts"),
        "imp_over": imp_over,
        "imp_btts": imp_btts,
    }

def analyze(api: FootyStats, query: str) -> str:
    b = _bundle(api, query)
    tips = [v.pick for v in b["verdicts"] if v.pick]
    tip = ", ".join(tips) if tips else "kein Tipp"
    markt = ""
    if b["imp_over"] is not None:
        markt = f" | Markt Over {b['imp_over']:.0%}"
    return f"{b['spiel']}\n{b['liga']} | {b['kick']}\nAktion: {tip}\nOver geeicht {b['over_c']:.0%} (roh {b['over_raw']:.0%}){markt}"

def analyze_html(api: FootyStats, query: str) -> str:
    b = _bundle(api, query)
    rows = ""
    for v in b["verdicts"]:
        aktion = v.pick or "kein Tipp"
        color = "#4ade80" if v.pick else "#f87171"
        rows += (
            f"<tr><td>{v.market}</td><td style='color:{color};font-weight:700'>{aktion}</td>"
            f"<td>{v.probability:.0%}</td><td>{v.reason}</td></tr>"
        )
    extra = ""
    if b["imp_over"] is not None:
        extra = f"<p>Markt Over ~{b['imp_over']:.0%} / BTTS ~{(b['imp_btts'] or 0):.0%} (Quote aus FootyStats)</p>"
    return (
        f"<h3>{b['spiel']}</h3><p>{b['liga']} | {b['kick']}</p>{extra}"
        f"<table><thead><tr><th>Markt</th><th>Aktion</th><th>Geeicht</th><th>Roh / Markt</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<p class='hinweis'>Gruen nur wenn Modell und Markt in dieselbe Richtung zeigen. "
        "Historisch dann ~63 % Over, nicht 70 %. Rot = nicht wetten.</p>"
    )
