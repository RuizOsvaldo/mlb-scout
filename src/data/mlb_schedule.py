"""MLB schedule, probable starters, and confirmed lineups via MLB Stats API."""
from __future__ import annotations

import datetime

import pandas as pd
import requests

from src.data.cache import cached

MLB_API = "https://statsapi.mlb.com/api/v1"
_TIMEOUT = 15


def get_schedule(date: datetime.date) -> list[dict]:
    """Return list of games scheduled for date with probable starters."""
    date_str = date.strftime("%Y-%m-%d")

    def fetch():
        resp = requests.get(
            f"{MLB_API}/schedule",
            params={
                "sportId": 1,
                "date": date_str,
                "hydrate": "probablePitcher,lineups,team",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
        rows = []
        for d in dates:
            for g in d.get("games", []):
                home = g["teams"]["home"]
                away = g["teams"]["away"]
                home_pitcher = home.get("probablePitcher", {})
                away_pitcher = away.get("probablePitcher", {})
                game_time = g.get("gameDate", "")
                rows.append({
                    "game_id": g["gamePk"],
                    "home_team": home["team"]["name"],
                    "home_team_id": home["team"]["id"],
                    "away_team": away["team"]["name"],
                    "away_team_id": away["team"]["id"],
                    "game_time_et": game_time,
                    "status": g.get("status", {}).get("detailedState", ""),
                    "home_starter": home_pitcher.get("fullName"),
                    "home_starter_id": home_pitcher.get("id"),
                    "away_starter": away_pitcher.get("fullName"),
                    "away_starter_id": away_pitcher.get("id"),
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    df = cached(f"schedule_{date_str}", fetch, ttl_hours=1.0)
    if df.empty:
        return []
    return df.to_dict("records")


def get_confirmed_lineup(game_id: int, side: str) -> list[dict]:
    """Return batting order for 'home' or 'away'; empty list if not yet posted."""
    if side not in ("home", "away"):
        raise ValueError(f"side must be 'home' or 'away', got {side!r}")

    def fetch():
        resp = requests.get(f"{MLB_API}/game/{game_id}/boxscore", timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        team_data = data.get("teams", {}).get(side, {})
        batting_order = team_data.get("battingOrder", [])
        players = team_data.get("players", {})
        rows = []
        for order_idx, pid in enumerate(batting_order):
            key = f"ID{pid}"
            p = players.get(key, {})
            person = p.get("person", {})
            pos = p.get("position", {})
            rows.append({
                "batting_order": order_idx + 1,
                "player_id": pid,
                "player_name": person.get("fullName", ""),
                "position": pos.get("abbreviation", ""),
                "bat_side": p.get("batSide", {}).get("code", ""),
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    try:
        df = cached(f"lineup_{game_id}_{side}", fetch, ttl_hours=0.5)
        if df.empty:
            return []
        return df.to_dict("records")
    except Exception:
        return []


def get_team_season_stats(season: int) -> pd.DataFrame:
    """Return team batting+pitching totals from MLB Stats API merged on team_id."""
    def fetch():
        batting_resp = requests.get(
            f"{MLB_API}/teams/stats",
            params={"season": season, "sportId": 1, "stats": "season", "group": "hitting"},
            timeout=_TIMEOUT,
        )
        batting_resp.raise_for_status()
        pitching_resp = requests.get(
            f"{MLB_API}/teams/stats",
            params={"season": season, "sportId": 1, "stats": "season", "group": "pitching"},
            timeout=_TIMEOUT,
        )
        pitching_resp.raise_for_status()

        bat_rows = []
        for s in batting_resp.json()["stats"][0]["splits"]:
            stat = s.get("stat", {})
            bat_rows.append({
                "team_id": s["team"]["id"],
                "team": s["team"]["name"],
                "games": stat.get("gamesPlayed", 0),
                "runs_scored": stat.get("runs", 0),
            })

        pit_rows = []
        for s in pitching_resp.json()["stats"][0]["splits"]:
            stat = s.get("stat", {})
            era_str = stat.get("era", "0.00")
            try:
                era = float(era_str)
            except (ValueError, TypeError):
                era = None
            pit_rows.append({
                "team_id": s["team"]["id"],
                "runs_allowed": stat.get("runs", 0),
                "era": era,
                "wins": stat.get("wins", 0),
                "losses": stat.get("losses", 0),
            })

        bat_df = pd.DataFrame(bat_rows)
        pit_df = pd.DataFrame(pit_rows)
        return bat_df.merge(pit_df, on="team_id", how="inner")

    return cached(f"team_season_stats_{season}", fetch, ttl_hours=6.0)


def get_team_last_games(team_id: int, season: int, n: int = 5) -> list[dict]:
    """Return the last N completed regular-season games for a team."""
    import json, time
    from pathlib import Path

    today = datetime.date.today()
    start = (today - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")

    cache_dir = Path("data/cache")
    path = cache_dir / f"last_games_{team_id}_{season}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < 3600:
        return json.loads(path.read_text())

    resp = requests.get(
        f"{MLB_API}/schedule",
        params={
            "sportId": 1, "teamId": team_id, "gameType": "R",
            "season": season, "startDate": start, "endDate": end,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    games = [g for d in resp.json().get("dates", []) for g in d.get("games", [])]
    finals = [g for g in games if g.get("status", {}).get("detailedState") == "Final"]
    rows = []
    for g in finals[-n:]:
        home = g["teams"]["home"]
        away = g["teams"]["away"]
        is_home = home["team"]["id"] == team_id
        team_side = home if is_home else away
        opp_side  = away if is_home else home
        won        = bool(team_side.get("isWinner"))
        team_score = team_side.get("score", 0)
        opp_score  = opp_side.get("score", 0)
        rows.append({
            "date":       g.get("officialDate", ""),
            "opponent":   opp_side["team"]["name"],
            "home_away":  "vs" if is_home else "@",
            "result":     "W" if won else "L",
            "team_score": team_score,
            "opp_score":  opp_score,
            "score_line": f"{team_score}-{opp_score}" if won else f"{opp_score}-{team_score}",
        })

    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def fetch_handedness(player_ids: list[int]) -> dict[int, dict]:
    """Batch-fetch pitchHand and batSide for a list of MLB player IDs."""
    if not player_ids:
        return {}
    resp = requests.get(
        f"{MLB_API}/people",
        params={"personIds": ",".join(str(i) for i in player_ids)},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return {
        p["id"]: {
            "pitch_hand": p.get("pitchHand", {}).get("code", "R"),
            "bat_side": p.get("batSide", {}).get("code", "R"),
        }
        for p in resp.json().get("people", [])
    }
