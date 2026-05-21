"""Full pitcher deep-dive render function."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.models.pitcher_profile import LEAGUE_AVG


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _zone_heatmap(df: pd.DataFrame, pitch_type_filter: str | None = None) -> go.Figure:
    filtered = df if pitch_type_filter is None else df[df["pitch_type"] == pitch_type_filter]

    fig = go.Figure()
    if not filtered.empty and "plate_x" in filtered.columns and "plate_z" in filtered.columns:
        fig.add_trace(go.Histogram2dContour(
            x=filtered["plate_x"],
            y=filtered["plate_z"],
            colorscale="Blues",
            reversescale=False,
            showscale=True,
            contours=dict(showlabels=False),
            name="Pitch Density",
        ))

    fig.add_shape(
        type="rect",
        x0=-0.83, x1=0.83, y0=1.5, y1=3.5,
        line=dict(color="red", width=2, dash="dash"),
    )
    label = f" — {pitch_type_filter}" if pitch_type_filter else " (All Pitches)"
    fig.update_layout(
        title=f"Pitch Location{label}",
        xaxis=dict(title="Horizontal (ft, catcher's view)", range=[-2.5, 2.5], zeroline=True),
        yaxis=dict(title="Vertical (ft)", range=[0, 5]),
        height=400,
        margin=dict(t=40, b=30),
    )
    return fig


def _velocity_trend_chart(df: pd.DataFrame) -> go.Figure:
    season_avg = df["avg_velo"].mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["game_date"], y=df["avg_velo"],
        mode="lines+markers",
        name="Avg Velo",
        line=dict(color="#3498db", width=2),
        marker=dict(size=8),
    ))
    fig.add_hline(
        y=season_avg, line_dash="dot", line_color="gray",
        annotation_text=f"Season avg: {season_avg:.1f}",
    )
    fig.update_layout(
        title="4-Seam FB Velocity — Last 10 Starts",
        yaxis=dict(title="MPH", range=[df["avg_velo"].min() - 2, df["avg_velo"].max() + 2]),
        height=300,
        margin=dict(t=40, b=20),
    )
    return fig


def _stuff_radar(scores: dict) -> go.Figure:
    categories = list(scores.keys())
    pitcher_vals = list(scores.values())
    league_vals = [50.0] * len(categories)

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=pitcher_vals + [pitcher_vals[0]],
        theta=categories + [categories[0]],
        fill="toself",
        name="Pitcher",
        line=dict(color="#3498db"),
        fillcolor="rgba(52,152,219,0.3)",
    ))
    fig.add_trace(go.Scatterpolar(
        r=league_vals + [league_vals[0]],
        theta=categories + [categories[0]],
        fill="toself",
        name="League Avg",
        line=dict(color="gray", dash="dot"),
        fillcolor="rgba(150,150,150,0.1)",
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        title="Stuff Profile vs. League Average",
        height=350,
        margin=dict(t=50, b=20),
    )
    return fig


def _babip_gauge(babip: float) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=babip,
        number={"valueformat": ".3f"},
        gauge={
            "axis": {"range": [0.200, 0.420], "tickformat": ".3f"},
            "bar": {"color": "#3498db"},
            "steps": [
                {"range": [0.200, 0.275], "color": "#1a5c1a"},
                {"range": [0.275, 0.320], "color": "#2a2a2a"},
                {"range": [0.320, 0.420], "color": "#5c1a1a"},
            ],
            "threshold": {
                "line": {"color": "white", "width": 2},
                "thickness": 0.75,
                "value": 0.300,
            },
        },
        title={"text": "BABIP (white line = .300 avg)"},
    ))
    fig.update_layout(height=200, margin=dict(t=30, b=0, l=20, r=20))
    return fig


def _confidence_badge(confidence: str) -> str:
    colors = {"High": "#2ecc71", "Medium": "#f39c12", "Low": "#e74c3c"}
    c = colors.get(confidence, "#888")
    return (
        f'<span style="background:{c};color:#000;padding:3px 10px;'
        f'border-radius:8px;font-weight:bold;font-size:13px">{confidence} Confidence</span>'
    )


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_pitcher_analysis(
    pitcher_name: str,
    team: str,
    fg_row: pd.Series | None,
    statcast_df: pd.DataFrame,
    platoon_splits: dict,
    pitch_mix: pd.DataFrame,
    velocity_trend: pd.DataFrame,
    recent_form: pd.DataFrame,
    proj: dict,
    league_avg: dict,
) -> None:
    """Render complete pitcher analysis card."""

    # --- Row 1: Header ---
    hand = "LHP" if (fg_row is not None and str(fg_row.get("p_throws", fg_row.get("Throws", "R"))) == "L") else "RHP"
    st.markdown(f"## {pitcher_name}")
    st.caption(f"{team} · {hand}")

    if fg_row is not None:
        def _get(col, *alts):
            for c in (col, *alts):
                v = fg_row.get(c)
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    return v
            return None

        era = _get("ERA")
        fip = _get("FIP")
        xfip = _get("xFIP")
        siera = _get("SIERA")
        k_pct = _get("K%")
        bb_pct = _get("BB%")
        whip = _get("WHIP")
        hr9 = _get("HR9", "HR/9")
        ip = _get("IP")

        def as_dec(v):
            return v / 100 if (v is not None and v > 1.0) else v

        k_dec = as_dec(k_pct)
        bb_dec = as_dec(bb_pct)

        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
        c1.metric("IP", f"{ip:.1f}" if ip else "—")
        c2.metric("ERA", f"{era:.2f}" if era else "—",
                  delta=f"{era - LEAGUE_AVG['era']:+.2f}" if era else None,
                  delta_color="inverse")
        c3.metric("FIP", f"{fip:.2f}" if fip else "—",
                  delta=f"{fip - LEAGUE_AVG['fip']:+.2f}" if fip else None,
                  delta_color="inverse")
        c4.metric("xFIP", f"{xfip:.2f}" if xfip else "—")
        c5.metric("SIERA", f"{siera:.2f}" if siera else "—")
        c6.metric("K%", f"{k_dec:.1%}" if k_dec else "—",
                  delta=f"{k_dec - LEAGUE_AVG['k_pct']:+.1%}" if k_dec else None)
        c7.metric("BB%", f"{bb_dec:.1%}" if bb_dec else "—",
                  delta=f"{bb_dec - LEAGUE_AVG['bb_pct']:+.1%}" if bb_dec else None,
                  delta_color="inverse")
        c8.metric("WHIP", f"{whip:.2f}" if whip else "—")

        # --- Row 2: FIP vs ERA analysis ---
        if era is not None and fip is not None:
            gap = fip - era
            if gap > 0.50:
                st.warning(f"ERA underperforming FIP (gap: {gap:+.2f}) — likely due for regression (ERA will rise).")
            elif gap < -0.50:
                st.info(f"ERA outperforming FIP (gap: {gap:+.2f}) — may be running hot (ERA will fall).")
            else:
                st.success(f"ERA and FIP aligned (gap: {gap:+.2f}) — sustainable performance.")
    else:
        st.warning("No FanGraphs leaderboard row found for this pitcher. Season stats unavailable.")

    st.divider()

    # --- Row 3: Heatmap + Pitch Mix ---
    col_heat, col_mix = st.columns(2)

    with col_heat:
        st.markdown("**Pitch Location Heatmap**")
        pitch_types = ["All"] + sorted(statcast_df["pitch_type"].dropna().unique().tolist()) if not statcast_df.empty else ["All"]
        selected_pt = st.selectbox("Pitch Type", pitch_types, key=f"pt_{pitcher_name}")
        pt_filter = None if selected_pt == "All" else selected_pt

        from src.models.pitcher_profile import compute_zone_heatmap
        heatmap_df = compute_zone_heatmap(statcast_df, pt_filter)
        st.plotly_chart(_zone_heatmap(heatmap_df, pt_filter), use_container_width=True)

    with col_mix:
        st.markdown("**Pitch Mix**")
        if not pitch_mix.empty:
            display = pitch_mix.copy()
            for col in ["overall_pct", "ahead_pct", "behind_pct", "neutral_pct"]:
                if col in display.columns:
                    display[col] = display[col].apply(lambda v: f"{v:.1%}" if pd.notna(v) else "—")
            for col in ["avg_velocity"]:
                if col in display.columns:
                    display[col] = display[col].apply(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
            for col in ["avg_spin_rate"]:
                if col in display.columns:
                    display[col] = display[col].apply(lambda v: f"{int(v)}" if pd.notna(v) else "—")
            for col in ["avg_horizontal_break", "avg_vertical_break"]:
                if col in display.columns:
                    display[col] = display[col].apply(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
            display.columns = [c.replace("_", " ").title() for c in display.columns]
            st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.caption("No pitch mix data available.")

    # --- Row 4: Velocity Trend + Radar ---
    col_velo, col_radar = st.columns(2)

    with col_velo:
        if len(velocity_trend) >= 3:
            st.plotly_chart(_velocity_trend_chart(velocity_trend), use_container_width=True)
        else:
            st.caption("Not enough starts to show trend.")

    with col_radar:
        if fg_row is not None:
            from src.models.pitcher_profile import compute_stuff_radar
            radar_scores = compute_stuff_radar(fg_row, league_avg)
            st.plotly_chart(_stuff_radar(radar_scores), use_container_width=True)
        else:
            st.caption("Radar chart requires FanGraphs data.")

    # --- Row 5: Platoon splits + Recent form + BABIP ---
    col_plat, col_form, col_babip = st.columns(3)

    with col_plat:
        st.markdown("**Platoon Splits**")
        if platoon_splits:
            rows = []
            for label, hand_key in [("vs. LHH", "vs_lhh"), ("vs. RHH", "vs_rhh")]:
                d = platoon_splits.get(hand_key, {})
                rows.append({
                    "Matchup": label,
                    "K%": f"{d.get('k_pct', 0):.1%}",
                    "BB%": f"{d.get('bb_pct', 0):.1%}",
                    "BABIP": f"{d.get('babip', 0):.3f}",
                    "n PA": d.get("n_pa", 0),
                })
            split_df = pd.DataFrame(rows)
            # Highlight weaker side
            lhh_k = platoon_splits.get("vs_lhh", {}).get("k_pct", 0)
            rhh_k = platoon_splits.get("vs_rhh", {}).get("k_pct", 0)
            weaker = 0 if lhh_k < rhh_k else 1

            def highlight_weaker(s):
                return ["background-color: #7d5a00" if i == weaker else "" for i in range(len(s))]

            styled = split_df.style.apply(highlight_weaker, axis=0)
            st.dataframe(styled, use_container_width=True, hide_index=True)

    with col_form:
        st.markdown("**Recent Form (last 5 starts)**")
        if not recent_form.empty:
            display = recent_form.copy()
            if "game_date" in display.columns:
                display["game_date"] = pd.to_datetime(display["game_date"]).dt.strftime("%b %-d")
            display.columns = [c.replace("_", " ").title() for c in display.columns]
            st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.caption("No recent start data available.")

    with col_babip:
        st.markdown("**BABIP Signal**")
        babip_val = None
        if fg_row is not None:
            babip_val = fg_row.get("BABIP") or fg_row.get("babip")
        if not recent_form.empty and babip_val is None:
            pass  # no fallback needed

        if babip_val is not None and not pd.isna(babip_val):
            st.plotly_chart(_babip_gauge(float(babip_val)), use_container_width=True)
            st.caption(
                "BABIP measures luck on balls in play. League avg is .300. "
                "High BABIP → ERA likely inflated. Low BABIP → ERA likely to rise."
            )
        else:
            st.caption("BABIP data unavailable.")

    # --- Row 6: Game Projection ---
    st.divider()
    st.subheader("Tonight's Projection")

    if proj:
        m1, m2, m3 = st.columns(3)
        m1.metric("Proj IP", proj.get("proj_ip", "—"))
        m2.metric("Proj K", proj.get("proj_k", "—"))
        m3.metric("Proj ER", proj.get("proj_er", "—"))

        qs = proj.get("quality_start", False)
        conf = proj.get("confidence", "Medium")
        qs_html = (
            '<span style="background:#2ecc71;color:#000;padding:3px 10px;border-radius:8px;font-weight:bold">QS Likely</span>'
            if qs else
            '<span style="background:#e74c3c;color:#fff;padding:3px 10px;border-radius:8px;font-weight:bold">QS Unlikely</span>'
        )
        st.markdown(qs_html, unsafe_allow_html=True)
        st.markdown(_confidence_badge(conf), unsafe_allow_html=True)
        st.caption("Confidence based on IP sample size and xFIP availability.")
    else:
        st.caption("Projection unavailable — insufficient data.")
