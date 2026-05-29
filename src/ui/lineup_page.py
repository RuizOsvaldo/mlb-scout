"""Full lineup analysis render function."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.models.lineup_analysis import classify_lineup_strength, build_threat_why

_LEAGUE_AVG_XWOBA = 0.318
_LEAGUE_AVG_K_PCT = 0.228
_LEAGUE_AVG_BARREL = 0.080


_HP_X, _HP_Y = 125.42, 198.27   # home plate in Statcast pixel space
_SCALE = 2.496                   # pixels → feet (calibrated: 170 px ≈ 424 ft to CF)


def _build_field_traces() -> list[go.BaseTraceType]:
    """Return invisible scatter traces that draw the field layout."""
    import numpy as np
    traces = []
    line_kw = dict(showlegend=False, hoverinfo="skip", mode="lines")

    # --- Foul lines (45° each side, extending 330 ft) ---
    sin45 = np.sin(np.radians(45))
    for sign in (-1, 1):
        traces.append(go.Scatter(
            x=[0, sign * 330 * sin45], y=[0, 330 * sin45],
            line=dict(color="rgba(255,255,255,0.6)", width=1.5, dash="dot"),
            **line_kw,
        ))

    # --- Outfield wall arc: LF pole → CF → RF pole ---
    ang = np.linspace(np.radians(-49), np.radians(49), 80)
    # Distance tapers from 330 ft at poles to 400 ft at CF
    dist = 330 + 70 * np.cos(ang) ** 2
    wall_x = dist * np.sin(ang)
    wall_y = dist * np.cos(ang)
    traces.append(go.Scatter(
        x=wall_x, y=wall_y,
        line=dict(color="rgba(255,255,255,0.8)", width=2.5),
        **line_kw,
    ))

    # --- Foul-territory connector lines (poles to wall ends) ---
    # Already connected by the arc endpoints; add short vertical stubs
    for sign in (-1, 1):
        pole_x = sign * 330 * sin45
        pole_y = 330 * sin45
        traces.append(go.Scatter(
            x=[sign * 310 * sin45, pole_x],
            y=[310 * sin45, pole_y],
            line=dict(color="rgba(255,255,255,0.4)", width=1),
            **line_kw,
        ))

    # --- Infield dirt circle (95 ft radius) ---
    t = np.linspace(0, 2 * np.pi, 120)
    traces.append(go.Scatter(
        x=95 * np.cos(t), y=63.6 + 95 * np.sin(t),
        line=dict(color="rgba(180,130,70,0.35)", width=12),
        **line_kw,
        fill="toself",
        fillcolor="rgba(180,130,70,0.12)",
    ))

    # --- Base paths (90-ft diamond) ---
    b = 90 / np.sqrt(2)   # ≈ 63.64 ft
    diamond_x = [0,  b, 0, -b, 0]
    diamond_y = [0,  b, b*2, b, 0]
    traces.append(go.Scatter(
        x=diamond_x, y=diamond_y,
        line=dict(color="rgba(255,255,255,0.9)", width=1.8),
        **line_kw,
    ))

    # --- Bases (white squares, drawn as small filled markers) ---
    traces.append(go.Scatter(
        x=[b, 0, -b, 0], y=[b, b*2, b, 0],
        mode="markers",
        marker=dict(color="white", size=8, symbol="square"),
        showlegend=False, hoverinfo="skip",
    ))

    # --- Pitcher's mound ---
    t2 = np.linspace(0, 2 * np.pi, 40)
    traces.append(go.Scatter(
        x=5 * np.cos(t2), y=60.5 + 5 * np.sin(t2),
        line=dict(color="rgba(255,255,255,0.5)", width=1),
        fill="toself", fillcolor="rgba(180,130,70,0.3)",
        **line_kw,
    ))

    return traces


def render_spray_chart(statcast_df: pd.DataFrame) -> go.Figure:
    """Render a correctly scaled top-down spray chart with full field layout."""
    fig = go.Figure()

    # Draw field first (underneath dots)
    for trace in _build_field_traces():
        fig.add_trace(trace)

    if not statcast_df.empty and "hc_x" in statcast_df.columns and "hc_y" in statcast_df.columns:
        df = statcast_df.dropna(subset=["hc_x", "hc_y"]).copy()

        # Vectorized coordinate transform — no zip/apply
        df["x_ft"] = (df["hc_x"].astype(float) - _HP_X) * _SCALE
        df["y_ft"] = (_HP_Y - df["hc_y"].astype(float)) * _SCALE

        color_map = {
            "home_run": "#e74c3c",
            "triple":   "#e67e22",
            "double":   "#f1c40f",
            "single":   "#2ecc71",
        }
        events_str = df["events"].astype(str)
        df["color"] = events_str.map(color_map).fillna("rgba(150,150,150,0.55)")

        ls = df["launch_speed"].astype(float)
        df["dot_size"] = ls.fillna(85).clip(60, 115).apply(lambda v: (v - 60) / 6 + 5)

        ev_col  = df["launch_speed"].astype(float)
        la_col  = df["launch_angle"].astype(float) if "launch_angle" in df.columns else pd.Series([float("nan")] * len(df))
        df["hover"] = (
            events_str.str.replace("_", " ").str.title()
            + "<br>EV: " + ev_col.apply(lambda v: f"{v:.0f} mph" if pd.notna(v) else "—")
            + "  |  LA: " + la_col.apply(lambda v: f"{v:.0f}°" if pd.notna(v) else "—")
        )

        for color, label in [
            ("#e74c3c", "HR"),
            ("#e67e22", "3B"),
            ("#f1c40f", "2B"),
            ("#2ecc71", "1B"),
            ("rgba(150,150,150,0.55)", "Out"),
        ]:
            sub = df[df["color"] == color]
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["x_ft"].tolist(),
                y=sub["y_ft"].tolist(),
                mode="markers",
                name=label,
                hovertext=sub["hover"].tolist(),
                hoverinfo="text",
                marker=dict(
                    color=color,
                    size=sub["dot_size"].tolist(),
                    opacity=0.88,
                    line=dict(width=0.8, color="white"),
                ),
            ))

    fig.update_layout(
        title=dict(text="Spray Chart", font=dict(size=14)),
        xaxis=dict(
            range=[-310, 310], showgrid=False, zeroline=False,
            showticklabels=False, fixedrange=True,
        ),
        yaxis=dict(
            range=[-25, 435], showgrid=False, zeroline=False,
            showticklabels=False, fixedrange=True,
        ),
        height=430,
        margin=dict(t=35, b=5, l=5, r=5),
        showlegend=True,
        plot_bgcolor="#1a3a22",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=11)),
    )
    return fig


def render_hot_cold_zones(statcast_df: pd.DataFrame) -> go.Figure:
    """3x3 strike-zone heatmap showing avg exit velocity by zone (hot=red, cold=blue)."""
    fig = go.Figure()

    # Only batted balls with location data
    required_cols = {"plate_x", "plate_z", "launch_speed"}
    if not required_cols.issubset(statcast_df.columns):
        return fig
    df = statcast_df.dropna(subset=list(required_cols)).copy()

    # Strike zone boundaries (split evenly into 3 columns × 3 rows)
    x_edges = [-0.83, -0.28, 0.28, 0.83]
    z_edges = [1.50, 2.17, 2.83, 3.50]

    zone_ev = [[None] * 3 for _ in range(3)]
    zone_n  = [[0] * 3 for _ in range(3)]

    for row_i in range(3):
        for col_j in range(3):
            mask = (
                (df["plate_x"] >= x_edges[col_j]) & (df["plate_x"] < x_edges[col_j + 1]) &
                (df["plate_z"] >= z_edges[row_i]) & (df["plate_z"] < z_edges[row_i + 1])
            )
            sub = df[mask]
            zone_ev[row_i][col_j] = sub["launch_speed"].mean() if not sub.empty else None
            zone_n[row_i][col_j]  = len(sub)

    # Build heatmap (row 0 = low zone; we flip for display so high zone is top)
    ev_matrix  = list(reversed(zone_ev))   # flip so high zone = top row
    n_matrix   = list(reversed(zone_n))

    # Color scale: blue (cold, ~70 mph) → white (avg, ~88 mph) → red (hot, ~100+ mph)
    z_vals = [[v if v is not None else 0 for v in row] for row in ev_matrix]
    annotations = []
    for ri in range(3):
        for ci in range(3):
            ev = ev_matrix[ri][ci]
            n  = n_matrix[ri][ci]
            text = f"{ev:.0f}<br><span style='font-size:9px'>n={n}</span>" if ev else "—"
            annotations.append(dict(
                x=ci, y=ri, text=text, showarrow=False,
                font=dict(color="white", size=13),
                xref="x", yref="y",
            ))

    fig.add_trace(go.Heatmap(
        z=z_vals,
        colorscale=[
            [0.0, "#1f77b4"],    # cold blue
            [0.4, "#aec7e8"],    # light blue
            [0.5, "#f7f7f7"],    # neutral white
            [0.7, "#fdae6b"],    # warm
            [1.0, "#d62728"],    # hot red
        ],
        zmin=70, zmax=105,
        showscale=True,
        colorbar=dict(title="EV (mph)", thickness=12, len=0.8),
        hovertemplate="EV: %{z:.0f} mph<extra></extra>",
    ))

    # Strike zone border
    fig.add_shape(type="rect", x0=-0.5, y0=-0.5, x1=2.5, y1=2.5,
                  line=dict(color="white", width=2))

    fig.update_layout(
        title="Hot / Cold Zones — Avg Exit Velocity",
        annotations=annotations,
        xaxis=dict(
            tickvals=[0, 1, 2],
            ticktext=["Inside", "Middle", "Outside"],
            showgrid=False, zeroline=False,
        ),
        yaxis=dict(
            tickvals=[0, 1, 2],
            ticktext=["Low", "Mid", "High"],
            showgrid=False, zeroline=False,
        ),
        height=320,
        margin=dict(t=45, b=30, l=60, r=60),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_batter_sabermetrics(statcast_df: pd.DataFrame) -> None:
    """Advanced sabermetric panel from Statcast data."""
    if statcast_df.empty:
        st.caption("No Statcast data for advanced metrics.")
        return

    batted = statcast_df.dropna(subset=["launch_speed"]).copy()
    total_pa = len(statcast_df["at_bat_number"].dropna().unique()) if "at_bat_number" in statcast_df.columns else None

    if batted.empty:
        st.caption("No batted ball data for advanced metrics.")
        return

    # --- Computed metrics ---
    avg_ev   = batted["launch_speed"].mean()
    max_ev   = batted["launch_speed"].max()
    hard_pct = (batted["launch_speed"] >= 95).mean()
    avg_la   = batted["launch_angle"].mean() if "launch_angle" in batted.columns else None

    xba   = batted["estimated_ba_using_speedangle"].mean()   if "estimated_ba_using_speedangle"   in batted.columns else None
    xslg  = batted["estimated_slg_using_speedangle"].mean()  if "estimated_slg_using_speedangle"  in batted.columns else None
    xwoba = batted["estimated_woba_using_speedangle"].mean() if "estimated_woba_using_speedangle" in batted.columns else None

    # Batted ball type %
    if "bb_type" in batted.columns:
        bb_counts = batted["bb_type"].value_counts(normalize=True)
        gb_pct = bb_counts.get("ground_ball", 0)
        ld_pct = bb_counts.get("line_drive", 0)
        fb_pct = bb_counts.get("fly_ball", 0)
        pu_pct = bb_counts.get("popup", 0)
    else:
        gb_pct = ld_pct = fb_pct = pu_pct = None

    # Pull / Center / Oppo using hc_x
    if "hc_x" in batted.columns and "stand" in batted.columns:
        stand = batted["stand"].mode().iloc[0] if not batted["stand"].mode().empty else "R"
        x = batted["hc_x"].dropna()
        if stand == "R":
            pull_pct   = (x < 100).mean()
            center_pct = ((x >= 100) & (x <= 150)).mean()
            oppo_pct   = (x > 150).mean()
        else:
            pull_pct   = (x > 150).mean()
            center_pct = ((x >= 100) & (x <= 150)).mean()
            oppo_pct   = (x < 100).mean()
    else:
        pull_pct = center_pct = oppo_pct = None

    st.markdown("#### Advanced Sabermetrics")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg EV", f"{avg_ev:.1f} mph" if avg_ev else "—")
    c2.metric("Max EV",  f"{max_ev:.1f} mph" if max_ev else "—")
    c3.metric("Hard Hit%", f"{hard_pct:.1%}" if hard_pct is not None else "—",
              delta=f"{hard_pct - 0.383:+.1%} vs lg" if hard_pct is not None else None)
    c4.metric("Avg LA", f"{avg_la:.1f}°" if avg_la is not None else "—")

    c5, c6, c7 = st.columns(3)
    c5.metric("xBA",   f"{xba:.3f}"  if xba  else "—")
    c6.metric("xSLG",  f"{xslg:.3f}" if xslg else "—")
    c7.metric("xwOBA", f"{xwoba:.3f}" if xwoba else "—")

    if gb_pct is not None:
        c8, c9, c10, c11 = st.columns(4)
        c8.metric("GB%",  f"{gb_pct:.1%}")
        c9.metric("LD%",  f"{ld_pct:.1%}")
        c10.metric("FB%", f"{fb_pct:.1%}")
        c11.metric("PU%", f"{pu_pct:.1%}")

    if pull_pct is not None:
        c12, c13, c14 = st.columns(3)
        c12.metric("Pull%",   f"{pull_pct:.1%}")
        c13.metric("Center%", f"{center_pct:.1%}")
        c14.metric("Oppo%",   f"{oppo_pct:.1%}")


def render_last_10_games(statcast_df: pd.DataFrame) -> None:
    """Table of per-game stats for the last 10 games played."""
    if statcast_df.empty or "game_date" not in statcast_df.columns:
        return

    # Plate appearance rows only (events populated on the final pitch of each PA)
    pa_df = statcast_df[statcast_df["events"].notna()].copy()
    if pa_df.empty:
        return

    pa_df["game_date"] = pd.to_datetime(pa_df["game_date"])

    hit_events = {"single", "double", "triple", "home_run"}

    def _agg_game(grp: pd.DataFrame) -> pd.Series:
        ev = grp["launch_speed"].dropna()
        xwoba_col = "estimated_woba_using_speedangle"
        xw = grp[xwoba_col].dropna() if xwoba_col in grp.columns else pd.Series(dtype=float)
        return pd.Series({
            "PA":     len(grp),
            "H":      grp["events"].isin(hit_events).sum(),
            "2B":     (grp["events"] == "double").sum(),
            "3B":     (grp["events"] == "triple").sum(),
            "HR":     (grp["events"] == "home_run").sum(),
            "BB":     (grp["events"] == "walk").sum(),
            "K":      (grp["events"] == "strikeout").sum(),
            "Avg EV": round(ev.mean(), 1) if not ev.empty else None,
            "xwOBA":  round(xw.mean(), 3) if not xw.empty else None,
        })

    game_stats = (
        pa_df.groupby("game_date")
        .apply(_agg_game)
        .reset_index()
        .sort_values("game_date", ascending=False)
        .head(10)
    )
    game_stats["game_date"] = game_stats["game_date"].dt.strftime("%Y-%m-%d")
    game_stats = game_stats.rename(columns={"game_date": "Date"})

    # Integer columns
    for col in ["PA", "H", "2B", "3B", "HR", "BB", "K"]:
        game_stats[col] = game_stats[col].astype(int)

    def _fmt(val, fmt):
        return f"{val:{fmt}}" if pd.notna(val) else "—"

    game_stats["Avg EV"] = game_stats["Avg EV"].apply(lambda v: _fmt(v, ".1f"))
    game_stats["xwOBA"]  = game_stats["xwOBA"].apply(lambda v: _fmt(v, ".3f"))

    st.markdown("#### Last 10 Games")
    st.dataframe(game_stats, use_container_width=True, hide_index=True)


def render_season_avg_line(row: dict) -> None:
    """One-line season average stats from FanGraphs/Statcast data."""
    avg    = row.get("avg")
    obp    = row.get("obp")
    slg    = row.get("slg")
    xwoba  = row.get("xwoba")
    k_pct  = row.get("k_pct")
    bb_pct = row.get("bb_pct")
    barrel = row.get("barrel_pct")
    hh     = row.get("hard_hit_pct")
    ops    = (obp + slg) if (obp is not None and slg is not None) else None

    if not any([avg, obp, slg, xwoba, k_pct]):
        return

    st.markdown("#### Season Averages")
    cols = st.columns(8)
    cols[0].metric("AVG",     f"{avg:.3f}"    if avg    is not None else "—")
    cols[1].metric("OBP",     f"{obp:.3f}"    if obp    is not None else "—")
    cols[2].metric("SLG",     f"{slg:.3f}"    if slg    is not None else "—")
    cols[3].metric("OPS",     f"{ops:.3f}"    if ops    is not None else "—")
    cols[4].metric("xwOBA",   f"{xwoba:.3f}"  if xwoba  is not None else "—")
    cols[5].metric("K%",      f"{k_pct:.1%}"  if k_pct  is not None else "—")
    cols[6].metric("BB%",     f"{bb_pct:.1%}" if bb_pct is not None else "—")
    cols[7].metric("Barrel%", f"{barrel:.1%}" if barrel is not None else "—")


def _matchup_score_color(score: float) -> str:
    if score >= 8:
        return "green"
    if score >= 5:
        return "#f39c12"
    return "#e74c3c"


# League-average thresholds for color coding (2024 MLB)
# (good_threshold, bad_threshold, inverse)
# inverse=True means lower is better (e.g. K%)
_STAT_THRESHOLDS: dict[str, tuple[float, float, bool]] = {
    "AVG":       (0.270, 0.230, False),
    "OBP":       (0.340, 0.300, False),
    "SLG":       (0.440, 0.360, False),
    "xwOBA":     (0.340, 0.295, False),
    "Barrel%":   (0.100, 0.050, False),
    "Hard Hit%": (0.430, 0.330, False),
    "K%":        (0.180, 0.270, True),   # lower K% is better
    "BB%":       (0.100, 0.060, False),
}

_GREEN  = "color: #2ecc71"
_RED    = "color: #e74c3c"
_WHITE  = "color: #ffffff"


def _color_stat(val: str, good: float, bad: float, inverse: bool = False) -> str:
    try:
        s = str(val).replace("%", "").replace("—", "").strip()
        if not s:
            return ""
        v = float(s)
        if str(val).endswith("%"):
            v /= 100.0
    except (ValueError, TypeError):
        return ""
    if not inverse:
        if v >= good:
            return _GREEN
        if v <= bad:
            return _RED
    else:
        if v <= good:
            return _GREEN
        if v >= bad:
            return _RED
    return _WHITE


def render_lineup_analysis(
    lineup: list[dict],
    batter_fg_rows: pd.DataFrame,
    batter_statcast: dict[int, pd.DataFrame],
    opposing_pitcher_name: str,
    opposing_pitcher_hand: str,
    batter_analysis_rows: list[dict],
) -> None:
    """Render the full lineup analysis section."""
    hand_label = f"{opposing_pitcher_hand}HP"
    st.markdown(f"### Starting Lineup vs. {opposing_pitcher_name} ({hand_label})")

    if not lineup:
        st.info("Lineup not yet posted. Check back ~3 hours before game time.")
        st.caption("Probable lineup may be available on team beat reporters' Twitter/X accounts.")
        return

    if not batter_analysis_rows:
        st.warning("Batter analysis data unavailable.")
        return

    # --- Main table ---
    table_rows = []
    for row in batter_analysis_rows:
        xwoba = row.get("xwoba")
        barrel = row.get("barrel_pct")
        hh = row.get("hard_hit_pct")
        k_pct = row.get("k_pct")
        bb_pct = row.get("bb_pct")
        platoon = row.get("platoon_advantage", False)
        score = row.get("matchup_score", 5.0)

        table_rows.append({
            "#": row.get("batting_order", ""),
            "Batter": row.get("name", ""),
            "B/T": row.get("bat_side", ""),
            "PA": row.get("pa", ""),
            "AVG": f"{row['avg']:.3f}" if row.get("avg") else "—",
            "OBP": f"{row['obp']:.3f}" if row.get("obp") else "—",
            "SLG": f"{row['slg']:.3f}" if row.get("slg") else "—",
            "xwOBA": f"{xwoba:.3f}" if xwoba else "—",
            "Barrel%": f"{barrel:.1%}" if barrel else "—",
            "Hard Hit%": f"{hh:.1%}" if hh else "—",
            "K%": f"{k_pct:.1%}" if k_pct else "—",
            "BB%": f"{bb_pct:.1%}" if bb_pct else "—",
            "Platoon": "Adv" if platoon else "Dis",
            "Score": score,
        })

    tdf = pd.DataFrame(table_rows)

    def color_score(val):
        try:
            v = float(val)
        except (ValueError, TypeError):
            return ""
        if v >= 8:
            return "color: #2ecc71; font-weight: bold"
        if v >= 5:
            return "color: #f39c12"
        return "color: #e74c3c"

    def color_platoon(val):
        if val == "Adv":
            return "color: #2ecc71; font-weight: bold"
        return "color: #e74c3c"

    from functools import partial

    styled = tdf.style.map(color_score, subset=["Score"]).map(color_platoon, subset=["Platoon"])
    for col, (good, bad, inv) in _STAT_THRESHOLDS.items():
        if col in tdf.columns:
            styled = styled.map(partial(_color_stat, good=good, bad=bad, inverse=inv), subset=[col])

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # --- Aggregate summary ---
    st.subheader("Lineup Summary")
    from src.models.lineup_analysis import compute_lineup_aggregate
    agg = compute_lineup_aggregate(batter_analysis_rows)

    avg_xwoba = agg.get("avg_xwoba")
    avg_k = agg.get("avg_k_pct")
    avg_barrel = agg.get("avg_barrel_pct")
    grade = classify_lineup_strength(avg_xwoba) if avg_xwoba else "—"

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric(
        "Avg xwOBA",
        f"{avg_xwoba:.3f}" if avg_xwoba else "—",
        delta=f"{avg_xwoba - _LEAGUE_AVG_XWOBA:+.3f} vs lg" if avg_xwoba else None,
    )
    sc2.metric(
        "Avg K%",
        f"{avg_k:.1%}" if avg_k else "—",
        delta=f"{avg_k - _LEAGUE_AVG_K_PCT:+.1%} vs lg" if avg_k else None,
        delta_color="inverse",
    )
    sc3.metric(
        "Avg Barrel%",
        f"{avg_barrel:.1%}" if avg_barrel else "—",
        delta=f"{avg_barrel - _LEAGUE_AVG_BARREL:+.1%} vs lg" if avg_barrel else None,
    )
    sc4.metric("Lineup Grade", grade)

    # --- Top threats ---
    top_rows = sorted(batter_analysis_rows, key=lambda r: r.get("matchup_score", 0), reverse=True)[:3]
    if top_rows:
        st.subheader("Top 3 Matchup Threats")
        for row in top_rows:
            score = row.get("matchup_score", 0)
            xwoba = row.get("xwoba")
            barrel = row.get("barrel_pct")
            platoon = row.get("platoon_advantage", False)
            name = row.get("name", "Unknown")
            why = build_threat_why(barrel, platoon, xwoba)

            with st.container(border=True):
                st.markdown(
                    f"**{name}** — Score: {score}/10  \n"
                    f"xwOBA: {f'{xwoba:.3f}' if xwoba else '—'} | "
                    f"Barrel%: {f'{barrel:.1%}' if barrel else '—'} | "
                    f"vs {opposing_pitcher_hand}HP: {'Adv' if platoon else 'Dis'}  \n"
                    f"*{why}*"
                )

    # --- Spray charts + zones + sabermetrics ---
    if batter_statcast:
        st.subheader("Batter Deep Dive")
        for row in batter_analysis_rows:
            pid = row.get("player_id")
            name = row.get("name", f"Player {pid}")
            sc_df = batter_statcast.get(pid, pd.DataFrame())
            with st.expander(f"{name}"):
                col_spray, col_zone = st.columns(2)
                with col_spray:
                    st.plotly_chart(render_spray_chart(sc_df), use_container_width=True)
                with col_zone:
                    st.plotly_chart(render_hot_cold_zones(sc_df), use_container_width=True)
                render_batter_sabermetrics(sc_df)
                render_last_10_games(sc_df)
                render_season_avg_line(row)
