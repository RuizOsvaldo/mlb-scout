"""Today's MLB game schedule table rendered as a custom HTML component."""
from __future__ import annotations

import datetime
import json
import time
from zoneinfo import ZoneInfo

import requests
import streamlit.components.v1 as components

from src.data.ballpark import park_factor_label
from src.data.cache import CACHE_DIR
from src.data.game_results import get_live_game_state
from src.data.mlb_schedule import get_team_last_games
from src.data.team_data import get_standings
from src.data.weather import STADIUMS, fetch_weather

_MLB = "https://statsapi.mlb.com/api/v1"
_ESPN = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
_TIMEOUT = 12
_PT = ZoneInfo("America/Los_Angeles")

_FULL_TO_ABBR: dict[str, str] = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
    "Athletics": "OAK",
}

# ESPN uses different abbreviations for some teams in logo URLs
_ESPN_LOGO_ABBR: dict[str, str] = {
    "CWS": "chw", "WSH": "wsh",
}

_SKIP_STATUSES = {"Postponed", "Cancelled", "Suspended", "Canceled"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abbr(full_name: str) -> str:
    return _FULL_TO_ABBR.get(full_name, full_name[:3].upper())


def _espn_logo(abbr: str) -> str:
    e = _ESPN_LOGO_ABBR.get(abbr, abbr.lower())
    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{e}.png"


def _to_pt(iso_str: str) -> datetime.datetime | None:
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(_PT)
    except Exception:
        return None


def _time_pt_str(iso_str: str) -> str:
    dt = _to_pt(iso_str)
    if not dt:
        return "TBD"
    return dt.strftime("%-I:%M %p PT").lstrip("0")


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _fetch_mlb_schedule(date: datetime.date) -> list[dict]:
    """Fetch today's schedule with extra hydrations. Cached 1h."""
    date_str = date.strftime("%Y-%m-%d")
    path = CACHE_DIR / f"games_schedule_{date_str}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < 3600:
        return json.loads(path.read_text())

    try:
        resp = requests.get(
            f"{_MLB}/schedule",
            params={
                "sportId": 1,
                "date": date_str,
                "hydrate": "probablePitcher,linescore,venue(location,fieldInfo),weather,team",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
    except Exception:
        return []

    rows = []
    for d in dates:
        for g in d.get("games", []):
            status = g.get("status", {}).get("detailedState", "")
            if any(s in status for s in _SKIP_STATUSES):
                continue
            abstract = g.get("status", {}).get("abstractGameState", "Preview")  # Preview/Live/Final

            home = g["teams"]["home"]
            away = g["teams"]["away"]
            home_p = home.get("probablePitcher", {})
            away_p = away.get("probablePitcher", {})
            ls = g.get("linescore", {})
            ls_teams = ls.get("teams", {})
            venue = g.get("venue", {})
            loc = venue.get("location", {})

            rows.append({
                "game_id": g["gamePk"],
                "game_time_et": g.get("gameDate", ""),
                "status": status,
                "abstract_state": abstract,  # Preview / Live / Final
                "series_game_num": g.get("seriesGameNumber", 1),
                "games_in_series": g.get("gamesInSeries", 3),
                "home_team": home["team"]["name"],
                "home_team_id": home["team"]["id"],
                "away_team": away["team"]["name"],
                "away_team_id": away["team"]["id"],
                "home_starter": home_p.get("fullName"),
                "home_starter_id": home_p.get("id"),
                "away_starter": away_p.get("fullName"),
                "away_starter_id": away_p.get("id"),
                # linescore (available for live/final)
                "inning": ls.get("currentInning", 0),
                "is_top": ls.get("isTopInning", True),
                "away_runs": ls_teams.get("away", {}).get("runs", 0),
                "home_runs": ls_teams.get("home", {}).get("runs", 0),
                "away_hits": ls_teams.get("away", {}).get("hits", 0),
                "home_hits": ls_teams.get("home", {}).get("hits", 0),
                # venue lon for travel detection
                "venue_lon": loc.get("defaultCoordinates", {}).get("longitude"),
            })

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def _fetch_espn(date: datetime.date) -> dict:
    """Return {espn_uid: {logo_away, logo_home, state}} from ESPN. Cached 2min."""
    date_str = date.strftime("%Y%m%d")
    path = CACHE_DIR / f"espn_scoreboard_{date_str}.json"
    ttl = 120  # 2 minutes
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        return json.loads(path.read_text())

    try:
        resp = requests.get(_ESPN, params={"dates": date_str}, timeout=_TIMEOUT)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for ev in events:
        comps = ev.get("competitions", [{}])
        comp = comps[0] if comps else {}
        competitors = comp.get("competitors", [])
        logos: dict[str, str] = {}
        for c in competitors:
            side = "home" if c.get("homeAway") == "home" else "away"
            team = c.get("team", {})
            logo = team.get("logo", "")
            logos[side] = logo
        uid = str(ev.get("uid", ""))
        result[uid] = logos

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result


def _standings_map(season: int) -> dict[int, dict]:
    """Return {team_id: standings_row} cached 6h via get_standings."""
    rows = get_standings(season)
    return {r["team_id"]: r for r in rows}


def _last5_map(team_ids: list[int], season: int) -> dict[int, list[str]]:
    """Return {team_id: ["W","L","W",...]} last 5 results, most-recent last."""
    result: dict[int, list[str]] = {}
    for tid in team_ids:
        try:
            games = get_team_last_games(tid, season, 5)
            result[tid] = [g["result"] for g in games]
        except Exception:
            result[tid] = []
    return result


def _prev_venue_lon(team_id: int, today: datetime.date) -> float | None:
    """Return longitude of where team_id played yesterday (for travel detection)."""
    yesterday = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    path = CACHE_DIR / f"prev_venue_{team_id}_{yesterday}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < 43200:
        val = json.loads(path.read_text())
        return val.get("lon")

    try:
        resp = requests.get(
            f"{_MLB}/schedule",
            params={"sportId": 1, "teamId": team_id, "date": yesterday,
                    "hydrate": "venue(location)"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
        for d in dates:
            for g in d.get("games", []):
                loc = g.get("venue", {}).get("location", {})
                coords = loc.get("defaultCoordinates", {})
                lon = coords.get("longitude")
                if lon is not None:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"lon": lon}))
                    return float(lon)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Series record derivation
# ---------------------------------------------------------------------------

def _series_record(game: dict, today: datetime.date) -> tuple[int, int]:
    """Return (away_wins, home_wins) in the current series from recent schedule."""
    gnum = game.get("series_game_num", 1)
    if gnum <= 1:
        return 0, 0
    away_id = game["away_team_id"]
    home_id = game["home_team_id"]
    # Look at schedule for the past (gnum-1) days to find prior series games
    away_wins = home_wins = 0
    for delta in range(1, gnum + 2):
        check_date = today - datetime.timedelta(days=delta)
        path = CACHE_DIR / f"games_schedule_{check_date.strftime('%Y-%m-%d')}.json"
        if not path.exists():
            continue
        try:
            past = json.loads(path.read_text())
        except Exception:
            continue
        for g in past:
            if g["away_team_id"] == away_id and g["home_team_id"] == home_id:
                if g.get("abstract_state") == "Final":
                    if g["away_runs"] > g["home_runs"]:
                        away_wins += 1
                    else:
                        home_wins += 1
    return away_wins, home_wins


# ---------------------------------------------------------------------------
# HTML fragments
# ---------------------------------------------------------------------------

def _last5_html(results: list[str]) -> str:
    dots = []
    for r in results:
        color = "#2ecc71" if r == "W" else "#e74c3c"
        dots.append(
            f'<span style="color:{color};font-weight:700;font-size:11px;">{r}</span>'
        )
    return "&thinsp;".join(dots)


def _base_diamond(b1: bool, b2: bool, b3: bool) -> str:
    def sq(occupied: bool) -> str:
        bg = "#f1c40f" if occupied else "#2a2a2a"
        return (
            f'<div style="width:9px;height:9px;background:{bg};'
            f'transform:rotate(45deg);margin:1px;"></div>'
        )
    return (
        '<div style="display:grid;grid-template-columns:repeat(3,11px);'
        'grid-template-rows:repeat(3,11px);gap:0;margin-top:4px;">'
        f'<div></div>{sq(b2)}<div></div>'
        f'{sq(b3)}<div></div>{sq(b1)}'
        '<div></div><div></div><div></div>'
        '</div>'
    )


def _pitcher_line_left(name: str | None) -> str:
    label = name or "TBD"
    return f'<div style="font-size:11px;color:#9ca3af;margin-top:3px;">SP: {label}</div>'


def _pitcher_line_right(name: str | None) -> str:
    label = name or "TBD"
    return f'<div style="font-size:11px;color:#9ca3af;margin-top:3px;text-align:right;">{label} SP</div>'


def _live_pitcher_line_right(p: dict) -> str:
    if not p.get("name"):
        return ""
    stats = (
        f'{p["ip"]} IP&thinsp;{p["hits"]}H&thinsp;{p["k"]}K&thinsp;{p["er"]}ER'
        f'&thinsp;·&thinsp;({p["pitches"]}p)'
    )
    return (
        f'<div style="font-size:10px;color:#9ca3af;margin-top:3px;text-align:right;">'
        f'{stats} {p["name"]} SP</div>'
    )


def _live_pitcher_line_left(p: dict) -> str:
    if not p.get("name"):
        return ""
    stats = (
        f'{p["ip"]} IP&thinsp;{p["hits"]}H&thinsp;{p["k"]}K&thinsp;{p["er"]}ER'
        f'&thinsp;·&thinsp;({p["pitches"]}p)'
    )
    return (
        f'<div style="font-size:10px;color:#9ca3af;margin-top:3px;">'
        f'SP: {p["name"]} {stats}</div>'
    )


def _away_side_html(game: dict, stand: dict, last5: list[str], live: dict) -> str:
    name = game["away_team"]
    abbr = _abbr(name)
    w, l = stand.get("w", 0), stand.get("l", 0)
    record = f"{w}–{l}"
    l5 = _last5_html(last5)

    lines = [
        f'<div style="font-weight:700;font-size:13px;line-height:1.2;">{name}</div>',
        f'<div style="font-size:11px;color:#9ca3af;margin-top:2px;">{record}'
        f'&nbsp;&nbsp;{l5}</div>',
    ]

    state = game.get("abstract_state", "Preview")
    if state == "Live" and live:
        lines.append(_live_pitcher_line_left(live.get("away_pitcher", {})))
        batter = live.get("batter", "")
        on_deck = live.get("on_deck", "")
        if batter:
            lines.append(
                f'<div style="font-size:10px;color:#f1c40f;margin-top:3px;">🏏 {batter}</div>'
            )
        if on_deck:
            lines.append(
                f'<div style="font-size:10px;color:#6b7280;margin-top:1px;">On deck: {on_deck}</div>'
            )
    else:
        lines.append(_pitcher_line_left(game.get("away_starter")))

    return "".join(lines)


def _home_side_html(game: dict, stand: dict, last5: list[str], live: dict) -> str:
    name = game["home_team"]
    abbr = _abbr(name)
    w, l = stand.get("w", 0), stand.get("l", 0)
    record = f"{w}–{l}"
    l5 = _last5_html(last5)

    lines = [
        f'<div style="font-weight:700;font-size:13px;line-height:1.2;text-align:right;">{name}</div>',
        f'<div style="font-size:11px;color:#9ca3af;margin-top:2px;text-align:right;">'
        f'{l5}&nbsp;&nbsp;{record}</div>',
    ]

    state = game.get("abstract_state", "Preview")
    if state == "Live" and live:
        lines.append(_live_pitcher_line_right(live.get("home_pitcher", {})))
    else:
        lines.append(_pitcher_line_right(game.get("home_starter")))

    return "".join(lines)


def _center_html(
    game: dict,
    today: datetime.date,
    season: int,
    away_wins: int,
    home_wins: int,
    travel_flag: str,
) -> str:
    gnum = game.get("series_game_num", 1)
    total = game.get("games_in_series", 3)
    away_abbr = _abbr(game["away_team"])
    home_abbr = _abbr(game["home_team"])

    parts = ['<div style="font-size:16px;font-weight:700;color:#fff;text-align:center;">@</div>']

    # Series context
    if total > 1:
        series_line = f"Game {gnum} of {total}"
        if gnum > 1 and (away_wins + home_wins) > 0:
            if away_wins == home_wins:
                series_line += f" · Tied {away_wins}–{home_wins}"
            elif away_wins > home_wins:
                series_line += f" · {away_abbr} leads {away_wins}–{home_wins}"
            else:
                series_line += f" · {home_abbr} leads {home_wins}–{away_wins}"
        parts.append(
            f'<div style="font-size:10px;color:#6b7280;text-align:center;margin-top:2px;">'
            f'{series_line}</div>'
        )

    # Travel flag
    if travel_flag:
        parts.append(
            f'<div style="font-size:10px;color:#e67e22;text-align:center;margin-top:2px;">'
            f'✈️ {travel_flag}</div>'
        )

    # Weather + park factor
    home_id = game["home_team_id"]
    wx = fetch_weather(home_id)
    wx_parts = []
    if wx and not wx.get("controlled"):
        if wx.get("temp_f") is not None:
            wx_parts.append(f'{wx["temp_f"]:.0f}°F')
        if wx.get("wind_mph") and wx["wind_mph"] >= 5:
            wx_parts.append(f'{wx["wind_label"]} {wx["wind_mph"]:.0f} mph')
    elif wx and wx.get("controlled"):
        wx_parts.append("Dome/Retractable")

    pf_label = park_factor_label(home_id)
    wx_parts.append(pf_label)

    if wx_parts:
        parts.append(
            f'<div style="font-size:10px;color:#6b7280;text-align:center;margin-top:2px;">'
            f'{"&thinsp;·&thinsp;".join(wx_parts)}</div>'
        )

    return "".join(parts)


def _score_cell_html(game: dict, live: dict, espn_logos: dict) -> str:
    state = game.get("abstract_state", "Preview")
    away_abbr = _abbr(game["away_team"])
    home_abbr = _abbr(game["home_team"])
    away_logo = espn_logos.get("away") or _espn_logo(away_abbr)
    home_logo = espn_logos.get("home") or _espn_logo(home_abbr)

    logo_away = f'<img src="{away_logo}" width="24" height="24" style="vertical-align:middle;" onerror="this.style.display=\'none\'">'
    logo_home = f'<img src="{home_logo}" width="24" height="24" style="vertical-align:middle;" onerror="this.style.display=\'none\'">'

    if state == "Final":
        ar = game.get("away_runs", 0)
        hr = game.get("home_runs", 0)
        ah = game.get("away_hits", 0)
        hh = game.get("home_hits", 0)
        away_bold = "font-weight:700;" if ar > hr else "color:#9ca3af;"
        home_bold = "font-weight:700;" if hr > ar else "color:#9ca3af;"
        return (
            '<div style="text-align:center;">'
            '<div style="font-size:10px;color:#6b7280;margin-bottom:4px;">Final</div>'
            f'<div style="display:flex;align-items:center;justify-content:center;gap:6px;">'
            f'{logo_away}'
            f'<span style="font-size:16px;{away_bold}">{ar}</span>'
            f'<span style="color:#4b5563;font-size:12px;">-</span>'
            f'<span style="font-size:16px;{home_bold}">{hr}</span>'
            f'{logo_home}'
            f'</div>'
            f'<div style="font-size:10px;color:#6b7280;margin-top:3px;">{ah}H · {hh}H</div>'
            '</div>'
        )

    if state == "Live" and live:
        inning = live.get("inning", game.get("inning", 0))
        is_top = live.get("is_top", game.get("is_top", True))
        half = "▲" if is_top else "▼"
        balls = live.get("balls", 0)
        strikes = live.get("strikes", 0)
        outs = live.get("outs", 0)
        ar = live.get("away_runs", game.get("away_runs", 0))
        hr = live.get("home_runs", game.get("home_runs", 0))
        ah = live.get("away_hits", game.get("away_hits", 0))
        hh = live.get("home_hits", game.get("home_hits", 0))
        away_bold = "font-weight:700;" if ar > hr else ""
        home_bold = "font-weight:700;" if hr > ar else ""
        b1 = live.get("base1", False)
        b2 = live.get("base2", False)
        b3 = live.get("base3", False)
        diamond = _base_diamond(b1, b2, b3)
        outs_str = "·" * outs + "○" * (3 - outs)
        return (
            '<div style="text-align:center;">'
            f'<div style="font-size:11px;color:#9ca3af;margin-bottom:3px;">'
            f'{half}{inning}&nbsp;&nbsp;{balls}-{strikes}&nbsp;&nbsp;{outs_str}</div>'
            f'<div style="display:flex;align-items:center;justify-content:center;gap:6px;">'
            f'{logo_away}'
            f'<span style="font-size:16px;{away_bold}">{ar}</span>'
            f'<span style="color:#4b5563;font-size:12px;">-</span>'
            f'<span style="font-size:16px;{home_bold}">{hr}</span>'
            f'{logo_home}'
            f'</div>'
            f'<div style="font-size:10px;color:#6b7280;margin-top:2px;">{ah}H · {hh}H</div>'
            f'<div style="display:flex;justify-content:center;">{diamond}</div>'
            '</div>'
        )

    # Pre-game
    time_pt = _time_pt_str(game.get("game_time_et", ""))
    status = game.get("status", "Scheduled")
    status_display = status if status not in ("Scheduled", "Pre-Game") else ""
    return (
        '<div style="text-align:center;">'
        f'<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:4px;">'
        f'{logo_away}'
        f'<span style="color:#4b5563;font-size:11px;">vs</span>'
        f'{logo_home}'
        f'</div>'
        f'{"<div style=\"font-size:10px;color:#f59e0b;margin-bottom:2px;\">" + status_display + "</div>" if status_display else ""}'
        '</div>'
    )


def _sort_key(game: dict) -> tuple:
    state = game.get("abstract_state", "Preview")
    order = {"Live": 0, "Preview": 1, "Final": 2}
    t = order.get(state, 1)
    return (t, game.get("game_time_et", ""))


# ---------------------------------------------------------------------------
# Table builder
# ---------------------------------------------------------------------------

def _build_table_html(
    games: list[dict],
    standings: dict[int, dict],
    last5: dict[int, list[str]],
    live_states: dict[int, dict],
    espn_data: dict,
    today: datetime.date,
    season: int,
) -> str:
    rows_html = []
    for game in sorted(games, key=_sort_key):
        state = game.get("abstract_state", "Preview")
        opacity = "opacity:0.4;" if state == "Final" else ""
        game_id = game["game_id"]
        live = live_states.get(game_id, {})

        away_id = game["away_team_id"]
        home_id = game["home_team_id"]
        away_stand = standings.get(away_id, {})
        home_stand = standings.get(home_id, {})
        away_l5 = last5.get(away_id, [])
        home_l5 = last5.get(home_id, [])

        # Travel detection
        travel_flag = ""
        home_lon = None
        if home_id in STADIUMS:
            home_lon = STADIUMS[home_id][1]
        prev_lon = _prev_venue_lon(away_id, today)
        if home_lon is not None and prev_lon is not None:
            delta = home_lon - prev_lon
            if abs(delta) > 5:
                direction = "W→E" if delta > 0 else "E→W"
                travel_flag = f"{_abbr(game['away_team'])} traveled ({direction})"

        # Series record
        away_wins, home_wins = _series_record(game, today)

        # ESPN logos
        espn_logos: dict = {}
        for uid, logos in espn_data.items():
            # Match by checking if either team abbr appears in uid (rough match)
            espn_logos = logos  # Will be overridden per game below

        # Time cell
        time_pt = _time_pt_str(game.get("game_time_et", ""))
        live_dot = '🔴&thinsp;' if state == "Live" else ""
        time_cell = (
            f'<td style="width:80px;padding:10px 8px;vertical-align:top;'
            f'font-size:12px;color:#d1d5db;white-space:nowrap;">'
            f'{live_dot}{time_pt}</td>'
        )

        # Matchup cell
        away_html = _away_side_html(game, away_stand, away_l5, live)
        home_html = _home_side_html(game, home_stand, home_l5, live)
        center_html = _center_html(game, today, season, away_wins, home_wins, travel_flag)

        matchup_cell = (
            f'<td style="padding:10px 8px;vertical-align:top;">'
            '<div style="display:flex;align-items:flex-start;gap:0;">'
            f'<div style="flex:1;min-width:0;">{away_html}</div>'
            f'<div style="width:100px;flex-shrink:0;padding:0 6px;">{center_html}</div>'
            f'<div style="flex:1;min-width:0;">{home_html}</div>'
            '</div>'
            '</td>'
        )

        # Score cell — try to find matching ESPN logos by game index
        score_cell = (
            f'<td style="width:160px;padding:10px 8px;vertical-align:top;">'
            f'{_score_cell_html(game, live, {})}'
            f'</td>'
        )

        rows_html.append(
            f'<tr style="border-bottom:1px solid #1f2937;{opacity}">'
            f'{time_cell}{matchup_cell}{score_cell}'
            f'</tr>'
        )

    header = (
        '<thead>'
        '<tr style="border-bottom:1px solid #374151;">'
        '<th style="padding:6px 8px;text-align:center;font-size:10px;color:#6b7280;'
        'text-transform:uppercase;letter-spacing:0.08em;font-weight:500;">Time</th>'
        '<th style="padding:6px 8px;text-align:center;font-size:10px;color:#6b7280;'
        'text-transform:uppercase;letter-spacing:0.08em;font-weight:500;">Matchup</th>'
        '<th style="padding:6px 8px;text-align:center;font-size:10px;color:#6b7280;'
        'text-transform:uppercase;letter-spacing:0.08em;font-weight:500;">Score</th>'
        '</tr>'
        '</thead>'
    )

    css = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: transparent; overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: #e5e7eb; }
table { width: 100%; border-collapse: collapse; }
tr:hover td { background: rgba(255,255,255,0.02); }
</style>"""

    resize_js = """
<script>
(function() {
  function sendHeight() {
    var h = document.documentElement.scrollHeight;
    window.parent.postMessage({type: 'streamlit:setFrameHeight', height: h}, '*');
  }
  var ro = new ResizeObserver(sendHeight);
  ro.observe(document.body);
  sendHeight();
})();
</script>"""

    return (
        f"<!DOCTYPE html><html><head>{css}</head><body>"
        f"<table>{header}<tbody>{''.join(rows_html)}</tbody></table>"
        f"{resize_js}</body></html>"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_today_schedule(season: int | None = None) -> None:
    """Render the today's games schedule table as an HTML component."""
    today = datetime.date.today()
    if season is None:
        season = today.year

    games = _fetch_mlb_schedule(today)
    if not games:
        import streamlit as st
        st.info("No games scheduled for today.")
        return

    # Standings (6h TTL via get_standings JSON cache)
    standings = _standings_map(season)

    # Last-5 per team (1h TTL via get_team_last_games)
    all_team_ids = list({g["away_team_id"] for g in games} | {g["home_team_id"] for g in games})
    last5 = _last5_map(all_team_ids, season)

    # ESPN (2-min TTL) — fallback gracefully
    espn_data = _fetch_espn(today)

    # Live states for in-progress games only (always fresh)
    live_states: dict[int, dict] = {}
    for g in games:
        if g.get("abstract_state") == "Live":
            state = get_live_game_state(g["game_id"])
            if state:
                live_states[g["game_id"]] = state

    # Height estimate
    live_count = sum(1 for g in games if g.get("abstract_state") == "Live")
    pre_count = sum(1 for g in games if g.get("abstract_state") == "Preview")
    est_height = max(live_count * 140 + pre_count * 90 + 45, 200)
    # Final rows are dimmed but still take space
    final_count = len(games) - live_count - pre_count
    est_height += final_count * 70

    html = _build_table_html(games, standings, last5, live_states, espn_data, today, season)
    components.html(html, height=est_height, scrolling=False)
