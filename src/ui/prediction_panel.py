"""Top-level game prediction summary panel."""
from __future__ import annotations

import streamlit as st


def _qs_badge(quality_start: bool) -> str:
    if quality_start:
        return '<span style="background:#2ecc71;color:#000;padding:2px 8px;border-radius:6px;font-size:12px;font-weight:bold">QS Likely</span>'
    return '<span style="background:#e74c3c;color:#fff;padding:2px 8px;border-radius:6px;font-size:12px;font-weight:bold">QS Unlikely</span>'


def render_prediction_panel(preview: dict, home_team: str, away_team: str) -> None:
    """Render the top-level game prediction summary at the top of the main page."""
    st.subheader("Game Preview")

    home_proj = preview.get("home_pitcher_proj", {})
    away_proj = preview.get("away_pitcher_proj", {})
    home_agg = preview.get("home_lineup_agg", {})
    away_agg = preview.get("away_lineup_agg", {})

    col_away, col_home = st.columns(2)

    with col_away:
        st.markdown(f"**{away_team}**")
        proj = away_proj
        if proj:
            qs = proj.get("quality_start", False)
            st.markdown(
                f"Proj: {proj.get('proj_ip', '—')} IP, {proj.get('proj_k', '—')} K, "
                f"{proj.get('proj_er', '—')} ER &nbsp; {_qs_badge(qs)}",
                unsafe_allow_html=True,
            )
        agg = away_agg
        if agg:
            xwoba = agg.get("avg_xwoba")
            top = agg.get("top_threats", [])
            grade = _grade(xwoba)
            xwoba_str = f"{xwoba:.3f}" if xwoba is not None else "—"
            st.caption(
                f"Lineup: {grade} | Avg xwOBA: {xwoba_str} | "
                f"Top Threat: {top[0] if top else '—'}"
            )

    with col_home:
        st.markdown(f"**{home_team}**")
        proj = home_proj
        if proj:
            qs = proj.get("quality_start", False)
            st.markdown(
                f"Proj: {proj.get('proj_ip', '—')} IP, {proj.get('proj_k', '—')} K, "
                f"{proj.get('proj_er', '—')} ER &nbsp; {_qs_badge(qs)}",
                unsafe_allow_html=True,
            )
        agg = home_agg
        if agg:
            xwoba = agg.get("avg_xwoba")
            top = agg.get("top_threats", [])
            grade = _grade(xwoba)
            xwoba_str = f"{xwoba:.3f}" if xwoba is not None else "—"
            st.caption(
                f"Lineup: {grade} | Avg xwOBA: {xwoba_str} | "
                f"Top Threat: {top[0] if top else '—'}"
            )

    narrative = preview.get("narrative", "")
    if narrative:
        st.info(narrative)

    st.caption(
        "Data: MLB Stats API · Baseball Savant (Statcast) · FanGraphs via pybaseball  \n"
        "Projections are statistical estimates, not guarantees."
    )


def _grade(xwoba: float | None) -> str:
    from src.models.lineup_analysis import classify_lineup_strength
    if xwoba is None:
        return "—"
    return classify_lineup_strength(xwoba)
