"""Team Analysis page — search bar, team browser, team detail view."""
from __future__ import annotations

import datetime

import streamlit as st

import pandas as pd

from src.data.team_data import (
    get_all_teams,
    get_team_roster,
    get_player_stats,
    get_team_record,
    get_standings,
    get_percentile_ranks,
    get_all_team_stats,
)

CURRENT_SEASON = datetime.date.today().year

# ESPN CDN abbreviations differ from MLB API for a handful of teams
_ESPN_ABBREV: dict[str, str] = {
    "CWS": "chw",   # Chicago White Sox
    "ATH": "oak",   # Athletics (Sacramento)
    "SD":  "sd",
    "SF":  "sf",
    "KC":  "kc",
    "TB":  "tb",
}


def _logo_url(mlb_abbrev: str) -> str:
    espn = _ESPN_ABBREV.get(mlb_abbrev, mlb_abbrev).lower()
    return f"https://a.espncdn.com/i/teamlogos/mlb/500/{espn}.png"


# Metrics to display for batters / pitchers, with human-readable labels
# For batters: higher = better EXCEPT k_percent, whiff_percent, chase_percent
# For pitchers: higher = better EXCEPT exit_velocity, hard_hit_percent, brl_percent, bb_percent, chase_percent
_BATTER_METRICS = [
    ("xwoba",          "xwOBA",           True),
    ("exit_velocity",  "Exit Velocity",   True),
    ("hard_hit_percent","Hard Hit%",      True),
    ("brl_percent",    "Barrel%",         True),
    ("bb_percent",     "BB%",             True),
    ("k_percent",      "K%",              False),   # lower = better
    ("whiff_percent",  "Whiff%",          False),
    ("sprint_speed",   "Sprint Speed",    True),
    ("bat_speed",      "Bat Speed",       True),
]

_PITCHER_METRICS = [
    ("xwoba",          "xwOBA Against",   False),  # lower = better for pitcher
    ("xera",           "xERA",            False),
    ("k_percent",      "K%",              True),
    ("bb_percent",     "BB%",             False),
    ("exit_velocity",  "Exit Velo Allowed", False),
    ("hard_hit_percent","Hard Hit% Allowed", False),
    ("brl_percent",    "Barrel% Allowed", False),
    ("whiff_percent",  "Whiff%",          True),
    ("fb_velocity",    "FB Velocity",     True),
]


def _percentile_color(pct: float, higher_is_better: bool) -> str:
    """Return a Baseball Savant-style color for a percentile value."""
    effective = pct if higher_is_better else (100 - pct)
    if effective >= 90:
        return "#e55b2b"   # orange-red (elite)
    if effective >= 70:
        return "#e8a42b"   # amber
    if effective >= 40:
        return "#8da9bf"   # neutral blue-gray
    if effective >= 20:
        return "#5a9cc5"   # medium blue
    return "#1f6faf"       # deep blue (poor)


def render_percentile_bars(player_id: int, position_type: str) -> None:
    """Render Baseball Savant-style percentile bars for a player."""
    ranks = get_percentile_ranks(CURRENT_SEASON, position_type)
    player_ranks = ranks.get(player_id)

    if not player_ranks:
        st.caption("Percentile data unavailable for this player.")
        return

    metrics = _BATTER_METRICS if position_type == "batter" else _PITCHER_METRICS
    st.markdown("**Baseball Savant Percentile Rankings**")

    for key, label, higher_is_better in metrics:
        raw = player_ranks.get(key)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        pct = float(raw)
        color = _percentile_color(pct, higher_is_better)
        bar_w = int(pct)
        st.markdown(
            f"""
<div style="display:flex;align-items:center;margin-bottom:4px;gap:8px">
  <span style="width:130px;font-size:12px;text-align:right;color:#ccc">{label}</span>
  <div style="flex:1;background:#2c2c2c;border-radius:4px;height:16px;position:relative">
    <div style="width:{bar_w}%;background:{color};height:100%;border-radius:4px"></div>
  </div>
  <span style="width:32px;font-size:12px;font-weight:bold;color:{color}">{int(pct)}</span>
</div>""",
            unsafe_allow_html=True,
        )


_DIVISION_LABELS = [
    "American League East",
    "American League Central",
    "American League West",
    "National League East",
    "National League Central",
    "National League West",
]


def _fmt_stat(val, fmt=".3f") -> str:
    if val is None or val == "" or val == "-.--":
        return "—"
    try:
        return f"{float(val):{fmt}}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_val(val, fmt: str) -> str:
    """Format a numeric value with d / +d / standard format spec."""
    if val is None:
        return "—"
    try:
        if fmt == "d":
            return str(int(round(float(val))))
        if fmt == "+d":
            return f"{int(round(float(val))):+d}"
        return f"{float(val):{fmt}}"
    except (ValueError, TypeError):
        return str(val)


# (display label, stat key, higher_is_better, format string)
_LEAGUE_STAT_OPTIONS: list[tuple] = [
    ("Runs Scored / Game", "runs_per_g",  True,  ".2f"),
    ("Hits per Game",      "hits_per_g",  True,  ".2f"),
    ("Home Runs",          "hr",          True,  "d"),
    ("Batting AVG",        "avg",         True,  ".3f"),
    ("OBP",                "obp",         True,  ".3f"),
    ("SLG",                "slg",         True,  ".3f"),
    ("OPS",                "ops",         True,  ".3f"),
    ("Stolen Bases",       "sb",          True,  "d"),
    ("Batting Strikeouts", "k",           False, "d"),
    ("Team ERA",           "era",         False, ".2f"),
    ("WHIP",               "whip",        False, ".3f"),
    ("K / 9 (pitching)",   "k_per_9",     True,  ".1f"),
    ("BB / 9 (pitching)",  "bb_per_9",    False, ".1f"),
    ("Pitcher Strikeouts", "pit_k",       True,  "d"),
    ("Run Differential",   "run_diff",    True,  "+d"),
    ("Win %",              "win_pct",     True,  ".3f"),
]

_LEAGUE_STAT_LABELS = [opt[0] for opt in _LEAGUE_STAT_OPTIONS]
_LEAGUE_STAT_MAP = {opt[0]: opt for opt in _LEAGUE_STAT_OPTIONS}


def _render_league_comparison(all_stats: list[dict]) -> None:
    """Horizontal bar chart — all 30 teams ranked by a user-selected stat."""
    import plotly.graph_objects as go

    st.subheader("League Stats Comparison")
    col_sel, col_spacer = st.columns([3, 5])
    with col_sel:
        stat_label = st.selectbox(
            "Stat",
            _LEAGUE_STAT_LABELS,
            key="league_stat_select",
            label_visibility="collapsed",
        )

    _, col_key, higher_is_better, fmt = _LEAGUE_STAT_MAP[stat_label]

    valid = [r for r in all_stats if r.get(col_key) is not None]
    if not valid:
        st.info("League stats not yet available.")
        return

    # Sort best-first; autorange="reversed" will put index 0 at the top
    valid.sort(key=lambda r: r[col_key], reverse=higher_is_better)

    abbrevs = [r["abbreviation"] for r in valid]
    values  = [r[col_key] for r in valid]
    leagues = [r.get("league", "") for r in valid]
    texts   = [_fmt_val(v, fmt) for v in values]
    colors  = ["#1e88e5" if lg.startswith("American") else "#e53935" for lg in leagues]

    # Pad x-axis so outside-bar text isn't clipped
    v_min, v_max = min(values), max(values)
    span = v_max - v_min if v_max != v_min else max(abs(v_max) * 0.1, 0.1)
    x_lo = v_min - span * 0.02 if v_min >= 0 else v_min - span * 0.18
    x_hi = v_max + span * 0.22

    fig = go.Figure(go.Bar(
        x=values,
        y=abbrevs,
        orientation="h",
        marker_color=colors,
        text=texts,
        textposition="outside",
        textfont=dict(size=11),
        hovertemplate="<b>%{y}</b>: %{text}<extra></extra>",
    ))
    fig.update_layout(
        height=700,
        margin=dict(l=10, r=80, t=10, b=30),
        xaxis=dict(title=stat_label, range=[x_lo, x_hi], gridcolor="#333", zerolinecolor="#666"),
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="#0f1117",
        paper_bgcolor="#0f1117",
        font=dict(color="#eee", size=12),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("🔵 American League  ·  🔴 National League")


def _render_team_stats_section(team_id: int, all_stats: list[dict]) -> None:
    """Compact batting/pitching stat tables + league-rank chart for one team."""
    import plotly.graph_objects as go

    team_row = next((r for r in all_stats if r["team_id"] == team_id), None)
    if team_row is None:
        return

    st.subheader("Team Season Stats")

    # ── Batting ──────────────────────────────────────────────────────────────
    st.markdown("**Batting**")
    bat_cols = st.columns(9)
    bat_items = [
        ("R",    team_row.get("runs", 0),      "d"),
        ("H",    team_row.get("hits", 0),      "d"),
        ("2B",   team_row.get("doubles", 0),   "d"),
        ("HR",   team_row.get("hr", 0),        "d"),
        ("RBI",  team_row.get("rbi", 0),       "d"),
        ("SB",   team_row.get("sb", 0),        "d"),
        ("AVG",  team_row.get("avg", 0),       ".3f"),
        ("OBP",  team_row.get("obp", 0),       ".3f"),
        ("OPS",  team_row.get("ops", 0),       ".3f"),
    ]
    for col, (label, val, fmt) in zip(bat_cols, bat_items):
        col.metric(label, _fmt_val(val, fmt))

    # ── Pitching ─────────────────────────────────────────────────────────────
    st.markdown("**Pitching**")
    pit_cols = st.columns(9)
    pit_items = [
        ("ERA",    team_row.get("era", 0),      ".2f"),
        ("WHIP",   team_row.get("whip", 0),     ".3f"),
        ("K/9",    team_row.get("k_per_9", 0),  ".1f"),
        ("BB/9",   team_row.get("bb_per_9", 0), ".1f"),
        ("K",      team_row.get("pit_k", 0),    "d"),
        ("BB",     team_row.get("pit_bb", 0),   "d"),
        ("HR",     team_row.get("pit_hr", 0),   "d"),
        ("SV",     team_row.get("saves", 0),    "d"),
        ("R-Diff", team_row.get("run_diff", 0), "+d"),
    ]
    for col, (label, val, fmt) in zip(pit_cols, pit_items):
        col.metric(label, _fmt_val(val, fmt))

    # ── League ranking bar chart ──────────────────────────────────────────────
    st.markdown("**League Rankings** (out of 30 teams)")

    rank_stats = [
        ("Runs/G",  "runs_per_g",  True,  ".2f"),
        ("Hits",    "hits",        True,  "d"),
        ("HR",      "hr",          True,  "d"),
        ("AVG",     "avg",         True,  ".3f"),
        ("OPS",     "ops",         True,  ".3f"),
        ("ERA",     "era",         False, ".2f"),
        ("WHIP",    "whip",        False, ".3f"),
        ("K/9",     "k_per_9",     True,  ".1f"),
        ("R-Diff",  "run_diff",    True,  "+d"),
    ]

    x_labels, y_pcts, bar_texts, bar_colors, hover_texts = [], [], [], [], []
    for label, key, higher, fmt in rank_stats:
        val = team_row.get(key)
        if val is None:
            continue
        if higher:
            rank = sum(1 for r in all_stats if (r.get(key) or 0) > val) + 1
        else:
            rank = sum(1 for r in all_stats if 0 < (r.get(key) or 0) < val) + 1
        n = sum(1 for r in all_stats if r.get(key) is not None)
        pct = 1.0 - (rank - 1) / max(n - 1, 1)
        color = "#2ecc71" if pct >= 0.667 else "#f39c12" if pct >= 0.333 else "#e74c3c"
        x_labels.append(label)
        y_pcts.append(pct)
        bar_texts.append(f"#{rank}")
        bar_colors.append(color)
        hover_texts.append(f"{label}: {_fmt_val(val, fmt)} — #{rank} of {n}")

    fig = go.Figure(go.Bar(
        x=x_labels,
        y=y_pcts,
        marker_color=bar_colors,
        text=bar_texts,
        textposition="outside",
        hovertext=hover_texts,
        hoverinfo="text",
    ))
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis=dict(
            tickformat=".0%",
            range=[0, 1.3],
            gridcolor="#333",
            showticklabels=False,
        ),
        xaxis=dict(tickfont=dict(size=12)),
        plot_bgcolor="#0f1117",
        paper_bgcolor="#0f1117",
        font=dict(color="#eee"),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Green = top 10  ·  Orange = middle 10  ·  Red = bottom 10")


def _render_team_detail(team: dict) -> None:
    """Full team page: record, roster, hitting & pitching splits."""
    team_id = team["team_id"]

    col_back, col_logo, col_title = st.columns([1, 1, 8])
    with col_back:
        if st.button("← Back", key="team_back"):
            st.session_state.selected_team = None
            st.rerun()
    with col_logo:
        st.image(_logo_url(team["abbreviation"]), width=72)
    with col_title:
        st.title(f"{team['name']}")
        st.caption(f"{team['division']} · {team['venue']}")

    # --- Record ---
    record = get_team_record(team_id, CURRENT_SEASON)
    if record:
        w, l, pct = record.get("wins", 0), record.get("losses", 0), record.get("pct", ".000")
        rank = record.get("division_rank", "—")
        gb = record.get("games_back", "—")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Wins", w)
        r2.metric("Losses", l)
        r3.metric("Win %", pct)
        r4.metric("Div Rank / GB", f"#{rank} / {gb}")

    # --- Team Season Stats & Rankings ---
    with st.spinner("Loading league stats..."):
        all_stats = get_all_team_stats(CURRENT_SEASON)
    _render_team_stats_section(team_id, all_stats)

    st.divider()

    # --- Roster ---
    with st.spinner("Loading roster..."):
        roster = get_team_roster(team_id, CURRENT_SEASON)

    if not roster:
        st.info("Roster not yet available for this season.")
        return

    pitchers = [p for p in roster if p["position_type"] == "Pitcher"]
    hitters = [p for p in roster if p["position_type"] != "Pitcher"]

    tab_hit, tab_pit = st.tabs(["Batters", "Pitchers"])

    with tab_hit:
        _render_hitter_table(hitters)

    with tab_pit:
        _render_pitcher_table(pitchers)


def _render_hitter_table(players: list[dict]) -> None:
    if not players:
        st.info("No batters on active roster.")
        return

    rows = []
    progress = st.progress(0, text="Loading hitter stats...")
    player_stats_map = {}
    for i, p in enumerate(players):
        stats = get_player_stats(p["player_id"], CURRENT_SEASON, "hitting")
        player_stats_map[p["player_id"]] = stats
        pa = stats.get("plateAppearances") or 0
        rows.append({
            "#": p["jersey"],
            "Name": p["name"],
            "Pos": p["position"],
            "G": stats.get("gamesPlayed", 0),
            "PA": pa,
            "AVG": _fmt_stat(stats.get("avg"), ".3f"),
            "OBP": _fmt_stat(stats.get("obp"), ".3f"),
            "SLG": _fmt_stat(stats.get("slg"), ".3f"),
            "OPS": _fmt_stat(stats.get("ops"), ".3f"),
            "HR": stats.get("homeRuns", 0),
            "RBI": stats.get("rbi", 0),
            "SB": stats.get("stolenBases", 0),
            "K%": f"{stats.get('strikeOuts', 0) / max(pa, 1):.1%}" if pa else "—",
            "BB%": f"{stats.get('baseOnBalls', 0) / max(pa, 1):.1%}" if pa else "—",
        })
        progress.progress((i + 1) / len(players), text=f"Loading {p['name']}...")
    progress.empty()

    summary_df = pd.DataFrame(rows).sort_values("PA", ascending=False).reset_index(drop=True)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.markdown("#### Player Profiles")
    for p in sorted(players, key=lambda x: player_stats_map.get(x["player_id"], {}).get("plateAppearances", 0) or 0, reverse=True):
        stats = player_stats_map[p["player_id"]]
        pa = stats.get("plateAppearances") or 0
        label = f"**#{p['jersey']}  {p['name']}** — {p['position']} | {stats.get('avg','—')} AVG · {stats.get('ops','—')} OPS · {stats.get('homeRuns',0)} HR"
        with st.expander(label):
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("AVG", _fmt_stat(stats.get("avg"), ".3f"))
            c2.metric("OBP", _fmt_stat(stats.get("obp"), ".3f"))
            c3.metric("SLG", _fmt_stat(stats.get("slg"), ".3f"))
            c4.metric("HR", stats.get("homeRuns", 0))
            c5.metric("RBI", stats.get("rbi", 0))
            c6.metric("SB", stats.get("stolenBases", 0))
            st.divider()
            render_percentile_bars(p["player_id"], "batter")


def _render_pitcher_table(players: list[dict]) -> None:
    if not players:
        st.info("No pitchers on active roster.")
        return

    rows = []
    progress = st.progress(0, text="Loading pitcher stats...")
    player_stats_map = {}
    for i, p in enumerate(players):
        stats = get_player_stats(p["player_id"], CURRENT_SEASON, "pitching")
        player_stats_map[p["player_id"]] = stats
        ip_raw = stats.get("inningsPitched", "0.0")
        try:
            ip = float(ip_raw)
        except (ValueError, TypeError):
            ip = 0.0
        bf = stats.get("battersFaced", 0) or 1
        so = stats.get("strikeOuts", 0)
        bb = stats.get("baseOnBalls", 0)
        rows.append({
            "#": p["jersey"],
            "Name": p["name"],
            "Pos": p["position"],
            "G": stats.get("gamesPlayed", 0),
            "GS": stats.get("gamesStarted", 0),
            "W": stats.get("wins", 0),
            "L": stats.get("losses", 0),
            "SV": stats.get("saves", 0),
            "IP": f"{ip:.1f}",
            "ERA": _fmt_stat(stats.get("era"), ".2f"),
            "WHIP": _fmt_stat(stats.get("whip"), ".2f"),
            "K/9": _fmt_stat(stats.get("strikeoutsPer9Inn"), ".1f"),
            "BB/9": _fmt_stat(stats.get("walksPer9Inn"), ".1f"),
            "K%": f"{so / bf:.1%}" if stats else "—",
            "BB%": f"{bb / bf:.1%}" if stats else "—",
        })
        progress.progress((i + 1) / len(players), text=f"Loading {p['name']}...")
    progress.empty()

    summary_df = pd.DataFrame(rows).sort_values(["GS", "IP"], ascending=False).reset_index(drop=True)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.markdown("#### Player Profiles")
    for p in sorted(players, key=lambda x: float(player_stats_map.get(x["player_id"], {}).get("inningsPitched") or 0), reverse=True):
        stats = player_stats_map[p["player_id"]]
        ip = stats.get("inningsPitched", "0.0")
        label = f"**#{p['jersey']}  {p['name']}** — {p['position']} | {_fmt_stat(stats.get('era'), '.2f')} ERA · {ip} IP · {stats.get('strikeOuts',0)} K"
        with st.expander(label):
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("ERA",  _fmt_stat(stats.get("era"), ".2f"))
            c2.metric("WHIP", _fmt_stat(stats.get("whip"), ".2f"))
            c3.metric("IP",   ip)
            c4.metric("W-L",  f"{stats.get('wins',0)}-{stats.get('losses',0)}")
            c5.metric("K",    stats.get("strikeOuts", 0))
            c6.metric("BB",   stats.get("baseOnBalls", 0))
            st.divider()
            render_percentile_bars(p["player_id"], "pitcher")


def _standings_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["W-L"] = df["w"].astype(str) + "-" + df["l"].astype(str)
    df["Home"] = df["home_w"].astype(str) + "-" + df["home_l"].astype(str)
    df["Away"] = df["away_w"].astype(str) + "-" + df["away_l"].astype(str)
    df["L10"] = df["l10_w"].astype(str) + "-" + df["l10_l"].astype(str)
    df["R-Diff"] = df["diff"].apply(lambda v: f"+{v}" if v > 0 else str(v))
    return df[["team_name", "W-L", "pct", "gb", "wcgb", "Home", "Away", "L10", "R-Diff", "streak"]].rename(columns={
        "team_name": "Team", "pct": "PCT", "gb": "GB", "wcgb": "WCGB", "streak": "Strk",
    })


def _render_standings() -> None:
    rows = get_standings(CURRENT_SEASON)
    if not rows:
        st.info("Standings not yet available.")
        return

    tab_labels = [
        "AL East", "AL Central", "AL West",
        "NL East", "NL Central", "NL West",
        "AL Overall", "NL Overall", "MLB",
    ]
    tabs = st.tabs(tab_labels)

    div_map = {
        "American League East": "AL East",
        "American League Central": "AL Central",
        "American League West": "AL West",
        "National League East": "NL East",
        "National League Central": "NL Central",
        "National League West": "NL West",
    }

    for tab, label in zip(tabs, tab_labels):
        with tab:
            if label in ("AL Overall", "NL Overall", "MLB"):
                league_filter = {"AL Overall": "American League", "NL Overall": "National League"}.get(label)
                filtered = [r for r in rows if (league_filter is None or r["league"] == league_filter)]
                sort_key = "sport_rank" if label == "MLB" else "league_rank"
                filtered.sort(key=lambda r: r[sort_key])
            else:
                div_name = next(k for k, v in div_map.items() if v == label)
                filtered = [r for r in rows if r["division"] == div_name]
                filtered.sort(key=lambda r: r["div_rank"])

            st.dataframe(_standings_df(filtered), use_container_width=True, hide_index=True)


def render_team_browser() -> None:
    """Main entry point — search bar + team grid, or selected team detail."""
    # Navigate into a team if one is selected
    if "selected_team" not in st.session_state:
        st.session_state.selected_team = None

    if st.session_state.selected_team is not None:
        _render_team_detail(st.session_state.selected_team)
        return

    st.title("Team Analysis")
    st.caption(f"{CURRENT_SEASON} Season · Updates daily")

    _render_standings()
    st.divider()

    # League-wide comparison chart
    with st.spinner("Loading league stats..."):
        all_stats = get_all_team_stats(CURRENT_SEASON)
    _render_league_comparison(all_stats)
    st.divider()

    st.subheader("Browse Teams")
    search = st.text_input("Search teams", placeholder="e.g. Yankees, Dodgers, NYY...", label_visibility="collapsed")
    query = search.strip().lower()

    teams = get_all_teams(CURRENT_SEASON)
    if query:
        teams = [
            t for t in teams
            if query in t["name"].lower()
            or query in t["abbreviation"].lower()
            or query in t["location"].lower()
            or query in t["team_name"].lower()
        ]

    if not teams:
        st.info("No teams match your search.")
        return

    # Group by division
    by_division: dict[str, list[dict]] = {}
    for t in teams:
        by_division.setdefault(t["division"], []).append(t)

    for division in _DIVISION_LABELS:
        division_teams = by_division.get(division)
        if not division_teams:
            continue
        st.subheader(division)
        cols = st.columns(min(len(division_teams), 5))
        for idx, team in enumerate(division_teams):
            with cols[idx % 5]:
                st.image(_logo_url(team["abbreviation"]), width=64)
                if st.button(
                    f"{team['abbreviation']} · {team['team_name']}",
                    key=f"team_btn_{team['team_id']}",
                    use_container_width=True,
                ):
                    st.session_state.selected_team = team
                    st.rerun()
