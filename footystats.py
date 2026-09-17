from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any
import requests

BASE = "https://api.football-data-api.com"
CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"

class FootyStatsError(RuntimeError):
    pass

class FootyStats:
    def __init__(self, api_key: str) -> None:
        if not api_key or api_key == "dein_key_hier":
            raise FootyStatsError("Kein API-Key.")
        self.api_key = api_key
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get(self, endpoint: str, params: dict[str, Any], cache_hours: float | None) -> Any:
        params = {"key": self.api_key, **params}
        cache_name = endpoint.strip("/") + "_" + "_".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "key")
        cache_file = CACHE_DIR / f"{cache_name}.json"
        if cache_hours and cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < cache_hours * 3600:
                return json.loads(cache_file.read_text(encoding="utf-8"))
        url = f"{BASE}/{endpoint.lstrip('/')}"
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 401:
            raise FootyStatsError("API-Key ungueltig.")
        if r.status_code == 403:
            raise FootyStatsError(f"Kein Zugriff auf {endpoint}.")
        if r.status_code == 429:
            raise FootyStatsError("Zu viele Anfragen.")
        r.raise_for_status()
        payload = r.json()
        if not payload.get("success", True):
            raise FootyStatsError(str(payload.get("message") or payload))
        data = payload.get("data")
        if cache_hours:
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def league_list(self, chosen_only: bool = True):
        params = {"chosen_leagues_only": "true"} if chosen_only else {}
        return self._get("league-list", params, cache_hours=24) or []

    def latest_seasons(self, chosen_only: bool = True):
        rows = []
        for league in self.league_list(chosen_only=chosen_only):
            seasons = league.get("season") or []
            if not seasons:
                continue
            current = max(seasons, key=lambda s: int(s.get("id") or 0))
            rows.append({"name": league.get("name") or "", "league_name": league.get("league_name") or "", "country": league.get("country") or "", "season_id": int(current["id"]), "year": current.get("year")})
        return rows

    def league_matches(self, season_id: int):
        page, out = 1, []
        while True:
            chunk = self._get("league-matches", {"season_id": season_id, "page": page, "max_per_page": 500}, cache_hours=6) or []
            if isinstance(chunk, dict):
                chunk = chunk.get("data") or []
            out.extend(chunk)
            if len(chunk) < 500 or page > 20:
                break
            page += 1
        return out
