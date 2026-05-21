"""Team, roster, and player season stats via MLB Stats API."""
from __future__ import annotations

import json
import time

import requests

from src.data.cache import CACHE_DIR

MLB_API = "https://statsapi.mlb.com/api/v1"
_TIMEOUT = 15

_DIVISION_ORDER = {
    "American League East": 0,
    "American League Central": 1,
    "American League West": 2,
    "National League East": 3,
    "National League Central": 4,
    "National League West": 5,
}


def get_all_teams(season: int) -> list[dict]:
    """Return all 30 MLB teams sorted by division then name."""
    def fetch():
        resp = requests.get(
            f"{MLB_API}/teams",
            params={"sportId": 1, "season": season},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = []
        for t in resp.json().get("teams", []):
            if not t.get("active"):
                continue
            league = t.get("league", {}).get("name", "")
            division = t.get("division", {}).get("name", "")
            rows.append({
                "team_id": t["id"],
                "name": t["name"],
                "abbreviation": t.get("abbreviation", ""),
                "location": t.get("locationName", ""),
                "team_name": t.get("teamName", ""),
                "league": league,
                "division": division,
                "venue": t.get("venue", {}).get("name", ""),
            })
        rows.sort(key=lambda r: (_DIVISION_ORDER.get(r["division"], 99), r["name"]))
        return rows

    key = f"teams_{season}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 24.0:
            return json.loads(path.read_text())

    rows = fetch()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def get_team_roster(team_id: int, season: int) -> list[dict]:
    """Return active 26-man roster players with basic info."""
    def fetch():
        resp = requests.get(
            f"{MLB_API}/teams/{team_id}/roster",
            params={"rosterType": "active", "season": season},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = []
        for p in resp.json().get("roster", []):
            person = p.get("person", {})
            pos = p.get("position", {})
            rows.append({
                "player_id": person["id"],
                "name": person.get("fullName", ""),
                "jersey": p.get("jerseyNumber", ""),
                "position": pos.get("abbreviation", ""),
                "position_type": pos.get("type", ""),
                "status": p.get("status", {}).get("description", "Active"),
            })
        rows.sort(key=lambda r: (r["position_type"] != "Pitcher", r["name"]))
        return rows

    key = f"roster_{team_id}_{season}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 6.0:
            return json.loads(path.read_text())

    rows = fetch()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def get_player_stats(player_id: int, season: int, group: str) -> dict:
    """Return a player's season stats dict for 'hitting' or 'pitching'."""
    def fetch():
        resp = requests.get(
            f"{MLB_API}/people/{player_id}/stats",
            params={"stats": "season", "group": group, "season": season},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for stat_group in data.get("stats", []):
            splits = stat_group.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
        return {}

    key = f"player_stats_{player_id}_{season}_{group}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 6.0:
            return json.loads(path.read_text())

    stats = fetch()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats))
    return stats


_DIVISION_ID_NAME = {
    200: "American League West",
    201: "American League East",
    202: "American League Central",
    203: "National League West",
    204: "National League East",
    205: "National League Central",
}
_LEAGUE_ID_NAME = {103: "American League", 104: "National League"}


def get_standings(season: int) -> list[dict]:
    """Return full standings for all 30 teams with division/league/overall rank."""
    def fetch():
        resp = requests.get(
            f"{MLB_API}/standings",
            params={"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = []
        for record in resp.json().get("records", []):
            division_id = record.get("division", {}).get("id", 0)
            league_id = record.get("league", {}).get("id", 0)
            division_name = _DIVISION_ID_NAME.get(division_id, "")
            league_name = _LEAGUE_ID_NAME.get(league_id, "")
            for tr in record.get("teamRecords", []):
                lr = tr.get("leagueRecord", {})
                streak = tr.get("streak", {}).get("streakCode", "")
                last10 = next(
                    (s for s in tr.get("records", {}).get("splitRecords", []) if s.get("type") == "lastTen"),
                    {},
                )
                rows.append({
                    "team_id": tr["team"]["id"],
                    "team_name": tr["team"]["name"],
                    "division": division_name,
                    "league": league_name,
                    "w": tr.get("wins", 0),
                    "l": tr.get("losses", 0),
                    "pct": tr.get("winningPercentage", ".000"),
                    "gb": tr.get("gamesBack", "-"),
                    "wcgb": tr.get("wildCardGamesBack", "-"),
                    "rs": tr.get("runsScored", 0),
                    "ra": tr.get("runsAllowed", 0),
                    "diff": tr.get("runDifferential", 0),
                    "l10_w": last10.get("wins", 0),
                    "l10_l": last10.get("losses", 0),
                    "streak": streak,
                    "div_rank": int(tr.get("divisionRank", 99)),
                    "league_rank": int(tr.get("leagueRank", 99)),
                    "sport_rank": int(tr.get("sportRank", 99)),
                    "home_w": next((s["wins"] for s in tr.get("records", {}).get("splitRecords", []) if s.get("type") == "home"), 0),
                    "home_l": next((s["losses"] for s in tr.get("records", {}).get("splitRecords", []) if s.get("type") == "home"), 0),
                    "away_w": next((s["wins"] for s in tr.get("records", {}).get("splitRecords", []) if s.get("type") == "away"), 0),
                    "away_l": next((s["losses"] for s in tr.get("records", {}).get("splitRecords", []) if s.get("type") == "away"), 0),
                })
        return rows

    import json
    from src.data.cache import CACHE_DIR
    import time

    key = f"standings_{season}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 1.0:
            return json.loads(path.read_text())

    rows = fetch()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def get_team_record(team_id: int, season: int) -> dict:
    """Return a team's W-L-PCT from the standings API."""
    def fetch():
        resp = requests.get(
            f"{MLB_API}/standings",
            params={"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        for record in resp.json().get("records", []):
            for team in record.get("teamRecords", []):
                if team["team"]["id"] == team_id:
                    return {
                        "wins": team.get("wins", 0),
                        "losses": team.get("losses", 0),
                        "pct": team.get("winningPercentage", ".000"),
                        "games_back": team.get("gamesBack", "-"),
                        "division": record.get("division", {}).get("name", ""),
                        "division_rank": team.get("divisionRank", "-"),
                    }
        return {}

    key = f"team_record_{team_id}_{season}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 1.0:
            return json.loads(path.read_text())

    record = fetch()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


def get_percentile_ranks(season: int, position_type: str) -> dict[int, dict]:
    """Return {player_id: {metric: percentile}} from Baseball Savant via pybaseball.

    position_type: 'batter' or 'pitcher'
    """
    key = f"percentile_{position_type}_{season}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 6.0:
            raw = json.loads(path.read_text())
            return {int(k): v for k, v in raw.items()}

    try:
        import pybaseball
        if position_type == "batter":
            df = pybaseball.statcast_batter_percentile_ranks(season)
        else:
            df = pybaseball.statcast_pitcher_percentile_ranks(season)

        if df is None or df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            pid = int(row["player_id"])
            result[pid] = {k: v for k, v in row.items() if k not in ("player_name", "player_id", "year")}
    except Exception:
        return {}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(k): v for k, v in result.items()}))
    return result


def get_all_team_stats(season: int) -> list[dict]:
    """Return batting + pitching season totals for all 30 teams, merged with standings."""
    key = f"all_team_stats_{season}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < 1.0:
            return json.loads(path.read_text())

    def _fetch_group(group: str) -> list[dict]:
        resp = requests.get(
            f"{MLB_API}/teams/stats",
            params={"season": season, "sportId": 1, "stats": "season", "group": group},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["stats"][0]["splits"]

    bat_splits = _fetch_group("hitting")
    pit_splits = _fetch_group("pitching")

    bat_map: dict[int, dict] = {}
    for s in bat_splits:
        tid = s["team"]["id"]
        stat = s.get("stat", {})
        g = max(stat.get("gamesPlayed", 1) or 1, 1)
        bat_map[tid] = {
            "team_id": tid,
            "team_name": s["team"]["name"],
            "games": g,
            "runs": stat.get("runs", 0),
            "hits": stat.get("hits", 0),
            "doubles": stat.get("doubles", 0),
            "triples": stat.get("triples", 0),
            "hr": stat.get("homeRuns", 0),
            "rbi": stat.get("rbi", 0),
            "sb": stat.get("stolenBases", 0),
            "bb": stat.get("baseOnBalls", 0),
            "k": stat.get("strikeOuts", 0),
            "avg": float(stat.get("avg") or 0),
            "obp": float(stat.get("obp") or 0),
            "slg": float(stat.get("slg") or 0),
            "ops": float(stat.get("ops") or 0),
            "runs_per_g": stat.get("runs", 0) / g,
            "hr_per_g": stat.get("homeRuns", 0) / g,
            "hits_per_g": stat.get("hits", 0) / g,
        }

    pit_map: dict[int, dict] = {}
    for s in pit_splits:
        tid = s["team"]["id"]
        stat = s.get("stat", {})
        try:
            era = float(stat.get("era") or 0)
        except (ValueError, TypeError):
            era = 0.0
        try:
            whip = float(stat.get("whip") or 0)
        except (ValueError, TypeError):
            whip = 0.0
        pit_map[tid] = {
            "era": era,
            "whip": whip,
            "wins": stat.get("wins", 0),
            "losses": stat.get("losses", 0),
            "saves": stat.get("saves", 0),
            "ip": stat.get("inningsPitched", "0.0"),
            "pit_k": stat.get("strikeOuts", 0),
            "pit_bb": stat.get("baseOnBalls", 0),
            "pit_hr": stat.get("homeRuns", 0),
            "k_per_9": float(stat.get("strikeoutsPer9Inn") or 0),
            "bb_per_9": float(stat.get("walksPer9Inn") or 0),
        }

    # Enrich with standings for division/league/run diff/win pct
    standings = get_standings(season)
    stand_map = {r["team_id"]: r for r in standings}
    teams_list = get_all_teams(season)
    abbrev_map = {t["team_id"]: t["abbreviation"] for t in teams_list}
    div_map_local = {t["team_id"]: t["division"] for t in teams_list}
    league_map_local = {t["team_id"]: t["league"] for t in teams_list}

    rows = []
    for tid, bat in bat_map.items():
        pit = pit_map.get(tid, {})
        st_row = stand_map.get(tid, {})
        row = {**bat, **pit}
        row["abbreviation"] = abbrev_map.get(tid, "")
        row["division"] = div_map_local.get(tid, "")
        row["league"] = league_map_local.get(tid, "")
        row["run_diff"] = st_row.get("diff", 0)
        try:
            row["win_pct"] = float(st_row.get("pct", "0.000") or "0.000")
        except (ValueError, TypeError):
            row["win_pct"] = 0.0
        row["team_wins"] = st_row.get("w", 0)
        row["team_losses"] = st_row.get("l", 0)
        rows.append(row)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows
