"""Live game state from MLB Stats API live feed."""
from __future__ import annotations

import requests

_TIMEOUT = 10
_MLB = "https://statsapi.mlb.com"


def get_live_game_state(game_pk: int) -> dict:
    """Return live game state. Always fetches fresh (TTL=0)."""
    try:
        data = requests.get(
            f"{_MLB}/api/v1.1/game/{game_pk}/feed/live",
            timeout=_TIMEOUT,
        ).json()
    except Exception:
        return {}

    gd = data.get("gameData", {})
    ld = data.get("liveData", {})
    ls = ld.get("linescore", {})
    off = ls.get("offense", {})
    teams = ls.get("teams", {})

    result: dict = {
        "state": gd.get("status", {}).get("abstractGameState", "Preview"),
        "inning": ls.get("currentInning", 0),
        "is_top": ls.get("isTopInning", True),
        "balls": ls.get("balls", 0),
        "strikes": ls.get("strikes", 0),
        "outs": ls.get("outs", 0),
        "away_runs": teams.get("away", {}).get("runs", 0),
        "home_runs": teams.get("home", {}).get("runs", 0),
        "away_hits": teams.get("away", {}).get("hits", 0),
        "home_hits": teams.get("home", {}).get("hits", 0),
        "base1": bool(off.get("first")),
        "base2": bool(off.get("second")),
        "base3": bool(off.get("third")),
        "batter": off.get("batter", {}).get("fullName", ""),
        "on_deck": off.get("onDeck", {}).get("fullName", ""),
        "home_pitcher": {},
        "away_pitcher": {},
    }

    # Pitcher game stats from boxscore
    try:
        box = requests.get(
            f"{_MLB}/api/v1/game/{game_pk}/boxscore",
            timeout=_TIMEOUT,
        ).json()
        for side in ("home", "away"):
            td = box.get("teams", {}).get(side, {})
            pitchers = td.get("pitchers", [])
            players = td.get("players", {})
            if pitchers:
                p = players.get(f"ID{pitchers[-1]}", {})
                stats = p.get("stats", {}).get("pitching", {})
                result[f"{side}_pitcher"] = {
                    "name": p.get("person", {}).get("fullName", ""),
                    "ip": stats.get("inningsPitched", "0.0"),
                    "hits": stats.get("hits", 0),
                    "k": stats.get("strikeOuts", 0),
                    "er": stats.get("earnedRuns", 0),
                    "pitches": stats.get("pitchesThrown", 0),
                }
    except Exception:
        pass

    return result
