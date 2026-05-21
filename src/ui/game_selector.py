"""Date picker + game dropdown sidebar component."""
from __future__ import annotations

import datetime

import streamlit as st

from src.data.mlb_schedule import get_schedule


def _format_game_label(game: dict) -> str:
    home = game["home_team"]
    away = game["away_team"]
    home_s = game.get("home_starter")
    away_s = game.get("away_starter")
    time_raw = game.get("game_time_et", "")
    time_label = _parse_time(time_raw)
    starters = f" ({away_s} vs. {home_s})" if home_s and away_s else ""
    return f"{away} @ {home}{starters} — {time_label}"


def _parse_time(iso_str: str) -> str:
    try:
        from datetime import timezone
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        eastern = datetime.timezone(datetime.timedelta(hours=-4))
        dt_et = dt.astimezone(eastern)
        return dt_et.strftime("%-I:%M %p ET")
    except Exception:
        return "TBD"


def render_game_selector(date: datetime.date) -> dict | None:
    """Render date picker and game dropdown in the sidebar; return selected game dict or None."""
    with st.spinner("Loading schedule..."):
        games = get_schedule(date)

    if not games:
        st.sidebar.info("No games scheduled for this date.")
        return None

    labels = ["— Today's Schedule —"] + [_format_game_label(g) for g in games]
    idx = st.sidebar.selectbox("Select Game", range(len(labels)), format_func=lambda i: labels[i])
    if idx == 0:
        return None
    return games[idx - 1]
