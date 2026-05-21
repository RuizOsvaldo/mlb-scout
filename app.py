"""Scout — MLB Starting Pitcher & Lineup Analysis."""
from __future__ import annotations

import datetime
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Scout — MLB Analysis",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.data.mlb_schedule import get_schedule, get_confirmed_lineup, fetch_handedness, get_team_last_games
from src.data.weather import fetch_weather
from src.data.statcast import (
    get_pitcher_statcast,
    get_batter_statcast,
    get_pitcher_season_leaderboard,
    get_batter_season_leaderboard,
)
from src.models.pitcher_profile import (
    compute_pitch_mix, compute_velocity_trend, compute_platoon_splits,
    compute_recent_form, project_pitcher_game, LEAGUE_AVG,
)
from src.models.lineup_analysis import (
    compute_batter_matchup_score, compute_lineup_aggregate, has_platoon_advantage,
)
from src.models.game_preview import build_game_preview
from src.ui.game_selector import render_game_selector
from src.ui.pitcher_page import render_pitcher_analysis
from src.ui.lineup_page import render_lineup_analysis
from src.ui.prediction_panel import render_prediction_panel
from src.ui.team_page import render_team_browser
from src.dashboard.sections.games import render_today_schedule

CURRENT_SEASON = datetime.date.today().year

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _load_fg_pitching(season: int) -> pd.DataFrame:
    try:
        return get_pitcher_season_leaderboard(season)
    except Exception as e:
        st.warning(f"FanGraphs pitching data unavailable: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _load_fg_batting(season: int) -> pd.DataFrame:
    try:
        return get_batter_season_leaderboard(season)
    except Exception as e:
        st.warning(f"FanGraphs batting data unavailable: {e}")
        return pd.DataFrame()


def _find_fg_pitcher(name: str, fg_df: pd.DataFrame) -> pd.Series | None:
    if fg_df.empty or "Name" not in fg_df.columns:
        return None
    name_n = _norm(name)
    for _, row in fg_df.iterrows():
        if _norm(str(row.get("Name", ""))) == name_n:
            return row
    return None


def _find_fg_batter(name: str, fg_df: pd.DataFrame) -> pd.Series | None:
    if fg_df.empty or "Name" not in fg_df.columns:
        return None
    name_n = _norm(name)
    for _, row in fg_df.iterrows():
        if _norm(str(row.get("Name", ""))) == name_n:
            return row
    return None


def _extract_batter_metrics(fg_row: pd.Series | None, statcast_df: pd.DataFrame) -> dict:
    def safe(v):
        return float(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None

    def as_dec(v):
        if v is None:
            return None
        return v / 100.0 if v > 1.0 else v

    def _fg(row: pd.Series, *keys):
        """Return first non-None value from row by trying keys in order."""
        for k in keys:
            v = row.get(k)
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                return v
        return None

    if fg_row is not None:
        xwoba = safe(_fg(fg_row, "xwOBA", "xwoba"))
        k_pct = as_dec(safe(_fg(fg_row, "K%", "k_pct")))
        bb_pct = as_dec(safe(_fg(fg_row, "BB%", "bb_pct")))
        barrel_pct = as_dec(safe(_fg(fg_row, "Barrel%", "Barrel", "barrel_pct")))
        hard_hit = as_dec(safe(_fg(fg_row, "Hard%", "HardHit%", "hard_hit_pct")))
        avg = safe(_fg(fg_row, "AVG", "avg"))
        obp = safe(_fg(fg_row, "OBP", "obp"))
        slg = safe(_fg(fg_row, "SLG", "slg"))
        pa = safe(_fg(fg_row, "PA", "pa"))
    else:
        xwoba = k_pct = bb_pct = barrel_pct = hard_hit = avg = obp = slg = pa = None

    # Supplement from Statcast if FG missing
    if not statcast_df.empty:
        if xwoba is None and "estimated_woba_using_speedangle" in statcast_df.columns:
            xwoba = statcast_df["estimated_woba_using_speedangle"].mean()
        if barrel_pct is None and "launch_speed_angle" in statcast_df.columns:
            batted = statcast_df["launch_speed_angle"].notna().sum()
            barrels = (statcast_df["launch_speed_angle"] == 6).sum()
            barrel_pct = float(barrels) / batted if batted else None
        if hard_hit is None and "hard_hit" in statcast_df.columns:
            hard_hit = statcast_df["hard_hit"].mean() if statcast_df["hard_hit"].notna().any() else None

    return {
        "xwoba": xwoba, "k_pct": k_pct, "bb_pct": bb_pct,
        "barrel_pct": barrel_pct, "hard_hit_pct": hard_hit,
        "avg": avg, "obp": obp, "slg": slg, "pa": int(pa) if pa else 0,
    }


def _build_pitcher_profile(
    pitcher_name: str | None,
    pitcher_id: int | None,
    fg_df: pd.DataFrame,
    season: int,
    opposing_lineup_k_pct: float = 0.228,
) -> dict:
    """Load all data and compute pitcher profile dict."""
    fg_row = _find_fg_pitcher(pitcher_name, fg_df) if pitcher_name else None

    statcast_df = pd.DataFrame()
    if pitcher_id:
        with st.spinner(f"Loading Statcast for {pitcher_name}..."):
            try:
                statcast_df = get_pitcher_statcast(pitcher_id, season)
            except Exception as e:
                st.warning(f"Statcast unavailable for {pitcher_name}: {e}")

    pitch_mix = pd.DataFrame()
    velocity_trend = pd.DataFrame()
    platoon_splits = {}
    recent_form = pd.DataFrame()

    if not statcast_df.empty:
        try:
            pitch_mix = compute_pitch_mix(statcast_df)
        except Exception:
            pass
        try:
            velocity_trend = compute_velocity_trend(statcast_df)
        except Exception:
            pass
        try:
            platoon_splits = compute_platoon_splits(statcast_df)
        except Exception:
            pass
        try:
            recent_form = compute_recent_form(statcast_df)
        except Exception:
            pass

    # Compute IP per start from recent form
    avg_ip = 5.0
    if not recent_form.empty and "ip_approx" in recent_form.columns:
        avg_ip = recent_form["ip_approx"].mean()

    # Build projection
    def safe(v):
        return float(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None

    def as_dec(v):
        if v is None:
            return None
        return v / 100.0 if v > 1.0 else v

    k_pct = 0.228
    bb_pct = 0.083
    fip = 4.20
    xfip = None

    if fg_row is not None:
        k_pct = as_dec(safe(fg_row.get("K%"))) or k_pct
        bb_pct = as_dec(safe(fg_row.get("BB%"))) or bb_pct
        fip = safe(fg_row.get("FIP")) or fip
        xfip = safe(fg_row.get("xFIP"))

    proj = project_pitcher_game(
        k_pct=k_pct,
        bb_pct=bb_pct,
        fip=fip,
        xfip=xfip,
        avg_ip_per_start=avg_ip,
        opposing_lineup_k_pct=opposing_lineup_k_pct,
    )

    return {
        "name": pitcher_name,
        "fg_row": fg_row,
        "statcast_df": statcast_df,
        "pitch_mix": pitch_mix,
        "velocity_trend": velocity_trend,
        "platoon_splits": platoon_splits,
        "recent_form": recent_form,
        "projection": proj,
        "k_pct": k_pct,
    }


def _build_lineup_rows(
    lineup: list[dict],
    fg_batting: pd.DataFrame,
    pitcher_hand: str,
    pitcher_k_pct: float,
    pitcher_gb_pct: float | None,
    season: int,
) -> tuple[list[dict], dict[int, pd.DataFrame]]:
    """Build per-batter analysis rows and load Statcast data."""
    batter_rows = []
    batter_statcast: dict[int, pd.DataFrame] = {}

    for player in lineup:
        pid = player.get("player_id")
        name = player.get("player_name", "")
        bat_side = player.get("bat_side") or ""

        fg_row = _find_fg_batter(name, fg_batting)
        sc_df = pd.DataFrame()
        if pid:
            try:
                sc_df = get_batter_statcast(pid, season)
                batter_statcast[pid] = sc_df
            except Exception:
                pass

        # Fall back to Statcast "stand" column if API didn't return bat side
        if not bat_side and not sc_df.empty and "stand" in sc_df.columns:
            mode = sc_df["stand"].dropna().mode()
            bat_side = mode.iloc[0] if not mode.empty else "R"
        if not bat_side:
            bat_side = "R"

        metrics = _extract_batter_metrics(fg_row, sc_df)
        platoon_adv = has_platoon_advantage(bat_side, pitcher_hand)

        score = compute_batter_matchup_score(
            batter_xwoba=metrics["xwoba"],
            batter_k_pct=metrics["k_pct"] or 0.228,
            batter_bb_pct=metrics["bb_pct"] or 0.083,
            batter_barrel_pct=metrics["barrel_pct"],
            pitcher_k_pct=pitcher_k_pct,
            pitcher_bb_pct=0.083,
            pitcher_gb_pct=pitcher_gb_pct,
            platoon_advantage=platoon_adv,
        )

        batter_rows.append({
            "batting_order": player.get("batting_order"),
            "player_id": pid,
            "name": name,
            "bat_side": bat_side,
            "position": player.get("position", ""),
            "platoon_advantage": platoon_adv,
            "matchup_score": score,
            **metrics,
        })

    return batter_rows, batter_statcast


# ---------------------------------------------------------------------------
# About page
# ---------------------------------------------------------------------------

_STAT_GLOSSARY: list[dict] = [
    # ── Pitching ERA-family ───────────────────────────────────────────────────
    {
        "name": "ERA", "abbr": "ERA", "category": "Pitching",
        "what": "Earned Run Average — the number of earned runs a pitcher allows per 9 innings pitched.",
        "formula": "ERA = (Earned Runs / IP) × 9",
        "why": "The most common pitching stat, but it mixes the pitcher's skill with defense and luck on balls in play. Use ERA alongside FIP for a fuller picture.",
        "thresholds": "Elite < 3.00 · Average ≈ 4.20 · Poor > 5.50",
        "tags": ["pitching", "traditional"],
    },
    {
        "name": "FIP", "abbr": "FIP", "category": "Pitching",
        "what": "Fielding Independent Pitching — measures what a pitcher's ERA *should* look like based only on outcomes the pitcher directly controls: strikeouts, walks, hit-by-pitches, and home runs.",
        "formula": "FIP = ((13 × HR) + (3 × (BB + HBP)) − (2 × K)) / IP + constant",
        "why": "Strips out defense and batted-ball luck. If a pitcher's ERA is much higher than their FIP, they've been unlucky and ERA is likely to drop.",
        "thresholds": "Elite < 3.20 · Average ≈ 4.20 · Poor > 5.20",
        "tags": ["pitching", "advanced", "sabermetric"],
    },
    {
        "name": "xFIP", "abbr": "xFIP", "category": "Pitching",
        "what": "Expected FIP — like FIP but normalizes the home run rate to league average, because HR/FB% fluctuates significantly with park and luck.",
        "formula": "Replace actual HR with (FB × lg HR/FB rate) in the FIP formula.",
        "why": "Best single-number predictor of a pitcher's future ERA. Use this over FIP when you want to project forward.",
        "thresholds": "Elite < 3.20 · Average ≈ 4.20 · Poor > 5.20",
        "tags": ["pitching", "advanced", "sabermetric", "projection"],
    },
    {
        "name": "SIERA", "abbr": "SIERA", "category": "Pitching",
        "what": "Skill-Interactive ERA — builds on xFIP by accounting for how ground balls, fly balls, and strikeout/walk rates interact. More complex but slightly more accurate.",
        "formula": "Proprietary regression using K%, BB%, GB%, and their interactions.",
        "why": "Rewards pitchers who suppress soft contact. A pitcher with a high GB% benefits more from induced weak contact than FIP captures.",
        "thresholds": "Elite < 3.10 · Average ≈ 4.15 · Poor > 5.10",
        "tags": ["pitching", "advanced", "sabermetric"],
    },
    {
        "name": "BABIP (Pitcher)", "abbr": "BABIP", "category": "Pitching",
        "what": "Batting Average on Balls In Play — the rate at which balls put in play (excluding HRs and Ks) fall for hits against a pitcher.",
        "formula": "BABIP = (H − HR) / (AB − K − HR + SF)",
        "why": "League average is ~.300. Pitchers have little control over BABIP year-to-year. A pitcher with BABIP > .330 is likely unlucky; ERA should improve. BABIP < .270 suggests good luck that won't last.",
        "thresholds": "Unlucky > .330 · Average ≈ .300 · Lucky < .270",
        "tags": ["pitching", "luck", "regression"],
    },
    {
        "name": "WHIP", "abbr": "WHIP", "category": "Pitching",
        "what": "Walks + Hits per Inning Pitched — measures how many baserunners a pitcher allows per inning.",
        "formula": "WHIP = (BB + H) / IP",
        "why": "A simple proxy for command and contact suppression. Doesn't account for home runs or strikeouts separately, but is easy to interpret.",
        "thresholds": "Elite < 1.05 · Average ≈ 1.30 · Poor > 1.50",
        "tags": ["pitching", "traditional"],
    },
    {
        "name": "K% (Pitcher)", "abbr": "K%", "category": "Pitching",
        "what": "Strikeout rate — the percentage of batters faced who strike out.",
        "formula": "K% = Strikeouts / Batters Faced",
        "why": "The single best indicator of a pitcher's dominance and stuff. High K% pitchers are less reliant on defense.",
        "thresholds": "Elite > 30% · Average ≈ 22% · Poor < 16%",
        "tags": ["pitching", "stuff", "command"],
    },
    {
        "name": "BB% (Pitcher)", "abbr": "BB%", "category": "Pitching",
        "what": "Walk rate — the percentage of batters faced who draw a walk.",
        "formula": "BB% = Walks / Batters Faced",
        "why": "Free passes kill pitchers. High BB% inflates pitch counts and keeps rallies alive. Elite pitchers walk fewer than 6% of hitters.",
        "thresholds": "Elite < 6% · Average ≈ 8.5% · Poor > 12%",
        "tags": ["pitching", "command"],
    },
    {
        "name": "GB%", "abbr": "GB%", "category": "Pitching",
        "what": "Ground Ball Rate — percentage of batted balls that are ground balls.",
        "formula": "GB% = Ground Balls / Balls in Play",
        "why": "Ground balls rarely leave the park. High GB% pitchers suppress home runs and are more valuable in pitcher-friendly parks with good infield defense.",
        "thresholds": "Elite > 52% · Average ≈ 44% · Low < 36%",
        "tags": ["pitching", "batted ball"],
    },
    # ── Batting Traditional ───────────────────────────────────────────────────
    {
        "name": "Batting Average", "abbr": "AVG", "category": "Batting",
        "what": "The rate at which a batter gets a hit per at-bat.",
        "formula": "AVG = Hits / At-Bats",
        "why": "Simple but incomplete — treats all hits equally and ignores walks. Use OBP and SLG alongside AVG.",
        "thresholds": "Elite > .300 · Average ≈ .250 · Poor < .210",
        "tags": ["batting", "traditional"],
    },
    {
        "name": "On-Base Percentage", "abbr": "OBP", "category": "Batting",
        "what": "How often a batter reaches base, including hits, walks, and hit-by-pitches.",
        "formula": "OBP = (H + BB + HBP) / (AB + BB + HBP + SF)",
        "why": "The most important traditional stat. Not making outs is the engine of offense — OBP correlates more strongly with run scoring than AVG.",
        "thresholds": "Elite > .380 · Average ≈ .320 · Poor < .290",
        "tags": ["batting", "traditional"],
    },
    {
        "name": "Slugging Percentage", "abbr": "SLG", "category": "Batting",
        "what": "Total bases per at-bat — weights hits by their extra-base value.",
        "formula": "SLG = (1B + 2×2B + 3×3B + 4×HR) / AB",
        "why": "Measures raw power and run production. A batter with .500 SLG averages half a base per at-bat.",
        "thresholds": "Elite > .520 · Average ≈ .420 · Poor < .350",
        "tags": ["batting", "traditional", "power"],
    },
    {
        "name": "OPS", "abbr": "OPS", "category": "Batting",
        "what": "On-Base Plus Slugging — simply adds OBP and SLG together.",
        "formula": "OPS = OBP + SLG",
        "why": "A convenient single-number hitter summary. Not mathematically perfect (OBP and SLG have different denominators) but works well in practice.",
        "thresholds": "Elite > .900 · Average ≈ .720 · Poor < .620",
        "tags": ["batting", "traditional"],
    },
    # ── Advanced Batting ──────────────────────────────────────────────────────
    {
        "name": "wOBA", "abbr": "wOBA", "category": "Batting — Advanced",
        "what": "Weighted On-Base Average — assigns proper run-value weights to each offensive outcome (single, double, HR, walk, etc.) based on how many runs each actually produces.",
        "formula": "wOBA = (0.69×BB + 0.72×HBP + 0.89×1B + 1.27×2B + 1.62×3B + 2.10×HR) / PA",
        "why": "More accurate than OPS because it correctly values each outcome. A player who hits .300/.350/.450 and one who hits .275/.390/.430 may have the same OPS but different wOBAs.",
        "thresholds": "Elite > .380 · Average ≈ .320 · Poor < .290",
        "tags": ["batting", "advanced", "sabermetric"],
    },
    {
        "name": "xwOBA", "abbr": "xwOBA", "category": "Batting — Advanced",
        "what": "Expected wOBA — calculates wOBA based on exit velocity and launch angle rather than actual outcomes. Tells you what a batter *deserved* based on quality of contact.",
        "formula": "Derived from MLB Statcast models: each batted ball is assigned an expected value based on its EV/LA combination, then aggregated like wOBA.",
        "why": "Removes defense, park, and sequencing luck. A batter whose xwOBA >> actual wOBA is getting unlucky and likely to improve. Used in Scout's matchup scoring.",
        "thresholds": "Elite > .380 · Average ≈ .318 · Poor < .285",
        "tags": ["batting", "statcast", "advanced", "expected"],
    },
    {
        "name": "wRC+", "abbr": "wRC+", "category": "Batting — Advanced",
        "what": "Weighted Runs Created Plus — scales wOBA to park and league, then expresses it as a percentage of league average (100 = exactly average).",
        "formula": "wRC+ = ((wOBA − lgwOBA)/wOBAscale + lgR/PA) / lgR/PA × 100, adjusted for park.",
        "why": "The single best all-in-one offensive metric. Directly comparable across parks and eras. 150 wRC+ = 50% better than league average.",
        "thresholds": "Elite > 140 · Average = 100 · Poor < 75",
        "tags": ["batting", "advanced", "sabermetric"],
    },
    {
        "name": "BABIP (Batter)", "abbr": "BABIP", "category": "Batting — Advanced",
        "what": "Batting Average on Balls In Play — how often a batter's balls in play become hits.",
        "formula": "BABIP = (H − HR) / (AB − K − HR + SF)",
        "why": "Batters have more control over their BABIP than pitchers do (speed, hard contact). But extreme values still regress toward career norms. Very high BABIP may indicate a hot streak.",
        "thresholds": "High > .360 · Average ≈ .300 · Low < .250",
        "tags": ["batting", "luck", "regression"],
    },
    # ── Statcast / Batted Ball ────────────────────────────────────────────────
    {
        "name": "Exit Velocity", "abbr": "EV", "category": "Statcast",
        "what": "How fast the ball leaves the bat, measured in mph by Doppler radar.",
        "formula": "Measured directly by Hawk-Eye / Statcast sensors at each MLB park.",
        "why": "The most direct measure of a hitter's raw power. Average EV above 92 mph signals elite contact quality. Also tracked for pitchers (lower is better).",
        "thresholds": "Elite avg > 92 mph · Average ≈ 88 mph · Weak < 84 mph",
        "tags": ["statcast", "batting", "power"],
    },
    {
        "name": "Launch Angle", "abbr": "LA", "category": "Statcast",
        "what": "The vertical angle at which the ball leaves the bat (0° = flat groundball, 45° = optimal fly-ball trajectory).",
        "formula": "Measured by Statcast sensors. Negative = groundball, 0–10° = line drive, 10–25° = hard LD/FB, 25–50° = fly ball.",
        "why": "Combined with EV, LA determines whether a well-struck ball becomes a single, double, or home run. Optimal power zone is roughly 25–35° LA with 95+ mph EV.",
        "thresholds": "Optimal power LA: 25–35° · Line drive zone: 8–20°",
        "tags": ["statcast", "batting"],
    },
    {
        "name": "Hard Hit %", "abbr": "Hard Hit%", "category": "Statcast",
        "what": "The percentage of batted balls hit at 95 mph or harder.",
        "formula": "Hard Hit% = (Batted balls ≥ 95 mph EV) / Total batted balls",
        "why": "The simplest Statcast power indicator. Hard contact is strongly correlated with offensive output — hitters who consistently barrel the ball at 95+ are dangerous even when results don't show yet.",
        "thresholds": "Elite > 50% · Average ≈ 38% · Weak < 28%",
        "tags": ["statcast", "batting", "power"],
    },
    {
        "name": "Barrel %", "abbr": "Barrel%", "category": "Statcast",
        "what": "A 'barrel' is a batted ball with the ideal combination of EV and LA that historically produces a .500+ BA and 1.500+ SLG. Barrel% is the rate of such batted balls.",
        "formula": "Barrel zone: EV ≥ 98 mph with LA 26–30°, expanding as EV increases above 98.",
        "why": "The highest-quality contact profile. Barrels become hits at a .500+ rate and extra-base hits at an even higher rate. High Barrel% batters are slugging threats regardless of park.",
        "thresholds": "Elite > 18% · Average ≈ 8% · Low < 4%",
        "tags": ["statcast", "batting", "power"],
    },
    {
        "name": "xBA", "abbr": "xBA", "category": "Statcast",
        "what": "Expected Batting Average based on exit velocity and launch angle of each batted ball.",
        "formula": "Each batted ball is assigned a probability of being a hit based on historical EV/LA outcomes, then averaged.",
        "why": "Removes defensive positioning and park effects. A batter with .240 AVG but .290 xBA is hitting the ball well but being robbed by good defense or bad luck.",
        "thresholds": "Elite > .290 · Average ≈ .250 · Poor < .210",
        "tags": ["statcast", "batting", "expected"],
    },
    {
        "name": "xSLG", "abbr": "xSLG", "category": "Statcast",
        "what": "Expected Slugging Percentage based on exit velocity and launch angle.",
        "formula": "Assigns expected extra-base value to each batted ball based on EV/LA, then computes SLG-style.",
        "why": "Shows true power potential independent of park and defense. Gap between xSLG and actual SLG reveals luck in extra-base hit results.",
        "thresholds": "Elite > .500 · Average ≈ .410 · Poor < .340",
        "tags": ["statcast", "batting", "power", "expected"],
    },
    # ── Plate Discipline ──────────────────────────────────────────────────────
    {
        "name": "K% (Batter)", "abbr": "K%", "category": "Plate Discipline",
        "what": "Strikeout rate — the percentage of plate appearances ending in a strikeout.",
        "formula": "K% = Strikeouts / Plate Appearances",
        "why": "High K% batters are easier for pitchers to exploit; low K% hitters make consistent contact. In Scout, a lineup's avg K% helps project opposing pitcher strikeout totals.",
        "thresholds": "Elite (low) < 14% · Average ≈ 23% · High > 32%",
        "tags": ["batting", "plate discipline"],
    },
    {
        "name": "BB% (Batter)", "abbr": "BB%", "category": "Plate Discipline",
        "what": "Walk rate — the percentage of plate appearances ending in a base on balls.",
        "formula": "BB% = Walks / Plate Appearances",
        "why": "High BB% batters have elite pitch recognition and patience. Walks are free bases — they boost OBP without requiring a hit.",
        "thresholds": "Elite > 14% · Average ≈ 8.5% · Poor < 5%",
        "tags": ["batting", "plate discipline"],
    },
    {
        "name": "Whiff %", "abbr": "Whiff%", "category": "Plate Discipline",
        "what": "The percentage of swings that miss entirely.",
        "formula": "Whiff% = Swings and Misses / Total Swings",
        "why": "High whiff rates signal vulnerability to swing-and-miss stuff. For pitchers, high opponent whiff% is the best indicator of elite 'stuff'.",
        "thresholds": "Batter vulnerability > 30% · Average ≈ 23% · Contact specialist < 15%",
        "tags": ["statcast", "plate discipline"],
    },
    {
        "name": "Chase %", "abbr": "Chase%", "category": "Plate Discipline",
        "what": "The percentage of pitches outside the strike zone that a batter swings at.",
        "formula": "Chase% = Swings at pitches outside zone / Pitches outside zone",
        "why": "High chase rates indicate poor pitch recognition — these batters can be exploited heavily with off-speed pitches and breaking balls off the plate.",
        "thresholds": "Disciplined < 25% · Average ≈ 30% · Free swinger > 36%",
        "tags": ["statcast", "plate discipline"],
    },
    # ── Scout-specific ────────────────────────────────────────────────────────
    {
        "name": "Matchup Score", "abbr": "Score", "category": "Scout — Projections",
        "what": "Scout's 1–10 rating of how favorable a batter's matchup is against the opposing starter.",
        "formula": "Weighted blend: xwOBA (40%), K% vs pitcher (25%), Barrel% (20%), platoon advantage (15%). Normalized to a 1–10 scale.",
        "why": "Gives a single number to prioritize which lineup spots to watch. 8–10 = strong threat, 5–7 = neutral, 1–4 = unfavorable.",
        "thresholds": "Strong threat ≥ 8 · Neutral 5–7 · Unfavorable ≤ 4",
        "tags": ["scout", "projection"],
    },
    {
        "name": "Platoon Advantage", "abbr": "Platoon", "category": "Scout — Projections",
        "what": "Whether a batter has a handedness edge against the opposing pitcher (LHB vs RHP, or RHB vs LHP).",
        "formula": "Advantage = (batter bats opposite hand from pitcher's throwing hand)",
        "why": "Batters facing pitchers of the opposite hand historically hit ~20–30 points of OBP better. Platoon edge is a significant factor in in-game matchup quality.",
        "thresholds": "Adv = batter has platoon edge · Dis = pitcher has platoon edge",
        "tags": ["scout", "matchup"],
    },
    {
        "name": "Quality Start", "abbr": "QS", "category": "Scout — Projections",
        "what": "A quality start is defined as 6+ innings pitched with 3 or fewer earned runs allowed (4.50 ERA or better for the game).",
        "formula": "QS = projected IP ≥ 6.0 AND projected ER ≤ 3",
        "why": "Useful fantasy and betting marker. Scout projects whether the starter is likely to deliver a QS based on their season K%, xFIP, and the opposing lineup's profile.",
        "thresholds": "QS Likely = strong projection · QS Unlikely = ERA or IP risk",
        "tags": ["scout", "projection"],
    },
    {
        "name": "Lineup Grade", "abbr": "Grade", "category": "Scout — Projections",
        "what": "Scout's letter-grade summary of a lineup's offensive threat, derived from average xwOBA.",
        "formula": "Elite ≥ .360 · Strong .340–.359 · Average .310–.339 · Weak .290–.309 · Poor < .290",
        "why": "Gives a quick read on which lineup is the bigger offensive threat for today's game.",
        "thresholds": "Elite / Strong / Average / Weak / Poor",
        "tags": ["scout", "lineup"],
    },
]

_ALL_CATEGORIES = list(dict.fromkeys(s["category"] for s in _STAT_GLOSSARY))


def render_about() -> None:
    st.title("Scout — Stat Glossary")
    st.caption("Every metric used in Scout: what it is, how it's calculated, and why it matters.")

    col_search, col_cat = st.columns([3, 2])
    with col_search:
        search_q = st.text_input("Search stats", placeholder="e.g. FIP, barrel, BABIP, xwOBA…",
                                  label_visibility="collapsed").strip().lower()
    with col_cat:
        cat_filter = st.selectbox("Category", ["All"] + _ALL_CATEGORIES,
                                   label_visibility="collapsed")

    def _matches(stat: dict) -> bool:
        if cat_filter != "All" and stat["category"] != cat_filter:
            return False
        if search_q:
            haystack = (
                stat["name"] + stat["abbr"] + stat["what"] +
                stat["why"] + " ".join(stat.get("tags", []))
            ).lower()
            return search_q in haystack
        return True

    visible = [s for s in _STAT_GLOSSARY if _matches(s)]

    if not visible:
        st.info("No stats match your search.")
        return

    # Group by category
    by_cat: dict[str, list] = {}
    for s in visible:
        by_cat.setdefault(s["category"], []).append(s)

    for cat in _ALL_CATEGORIES:
        stats = by_cat.get(cat)
        if not stats:
            continue
        st.subheader(cat)
        for s in stats:
            same = s["abbr"].replace(" ", "") == s["name"].replace(" ", "")
            expander_label = s["name"] if same else f"**{s['abbr']}** — {s['name']}"
            with st.expander(expander_label):
                st.markdown(f"**What it is:** {s['what']}")
                st.markdown(f"**How it's calculated:** `{s['formula']}`")
                st.markdown(f"**Why it matters:** {s['why']}")
                st.markdown(
                    f"<div style='background:#1e2e3e;padding:8px 14px;border-radius:6px;"
                    f"font-size:13px;color:#aad4f5'>"
                    f"📊 {s['thresholds']}</div>",
                    unsafe_allow_html=True,
                )

    st.divider()
    st.caption(
        "Data sources: MLB Stats API · Baseball Savant (Statcast) · Baseball Reference · Open-Meteo  \n"
        "Projections are statistical estimates, not guarantees."
    )


# ---------------------------------------------------------------------------
# Game Context: weather + last 5 games
# ---------------------------------------------------------------------------

def _render_game_context(
    home_team_id: int, away_team_id: int,
    home_team: str, away_team: str, season: int,
) -> None:
    with st.expander("Park Conditions & Recent Form", expanded=True):
        wx_col, spacer, away_col, home_col = st.columns([2, 0.1, 2, 2])

        # --- Weather ---
        with wx_col:
            wx = fetch_weather(home_team_id)
            if wx:
                score = wx.get("rating_score", 0)
                rating = wx.get("rating", "Neutral")
                if score >= 2:
                    badge_color, text_color = "#c0392b", "white"
                elif score == 1:
                    badge_color, text_color = "#e67e22", "white"
                elif score <= -2:
                    badge_color, text_color = "#2980b9", "white"
                elif score == -1:
                    badge_color, text_color = "#5dade2", "#111"
                else:
                    badge_color, text_color = "#555", "white"

                st.markdown(
                    f"**{wx['park']}**  \n"
                    f'<span style="background:{badge_color};color:{text_color};'
                    f'padding:2px 10px;border-radius:8px;font-size:12px;font-weight:bold">'
                    f'{rating}</span>',
                    unsafe_allow_html=True,
                )
                if wx.get("controlled"):
                    st.caption("Roof closed / dome — controlled environment")
                else:
                    parts = []
                    if wx.get("temp_f") is not None:
                        parts.append(f"{wx['temp_f']:.0f}°F")
                    if wx.get("conditions"):
                        parts.append(wx["conditions"])
                    if wx.get("wind_mph") is not None and wx["wind_mph"] >= 3:
                        parts.append(f"{wx['wind_label']} {wx['wind_mph']:.0f} mph {wx['wind_dir']}")
                    if wx.get("altitude_ft", 0) >= 1000:
                        parts.append(f"{wx['altitude_ft']:,} ft elevation")
                    st.caption("  |  ".join(parts))

        # --- Last 5 Games ---
        def _game_rows(team_id: int, label: str, col) -> None:
            with col:
                st.markdown(f"**{label} — Last 5**")
                try:
                    games = get_team_last_games(team_id, season, 5)
                except Exception:
                    games = []
                if not games:
                    st.caption("No recent game data.")
                    return
                for g in reversed(games):
                    result = g["result"]
                    color  = "#2ecc71" if result == "W" else "#e74c3c"
                    score  = g["score_line"]
                    opp    = g["opponent"]
                    ha     = g["home_away"]
                    date   = g["date"][5:]   # MM-DD
                    st.markdown(
                        f'<span style="font-weight:bold;color:{color}">{result}</span> '
                        f'<span style="font-size:13px">{score} &nbsp; {ha} {opp} &nbsp;'
                        f'<span style="color:#888;font-size:11px">{date}</span></span>',
                        unsafe_allow_html=True,
                    )

        _game_rows(away_team_id, away_team, away_col)
        _game_rows(home_team_id, home_team, home_col)




# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.sidebar.markdown("## ⚾ Scout")
    st.sidebar.markdown("MLB Pitching & Lineup Analysis")

    today = datetime.date.today()
    selected_date = st.sidebar.date_input("Date", value=today, max_value=today + datetime.timedelta(days=1))

    page = st.sidebar.radio("Page", ["Game Preview", "Team Analysis", "About"], label_visibility="collapsed")

    if page == "About":
        render_about()
        return

    if page == "Team Analysis":
        render_team_browser()
        return

    if st.sidebar.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    game = render_game_selector(selected_date)

    if game is None:
        st.title("⚾ Scout — Today's Games")
        st.caption(f"{today.strftime('%A, %B %-d, %Y')}  ·  Select a game from the sidebar to load the full analysis.")
        render_today_schedule(season=CURRENT_SEASON)
        return

    home_team = game["home_team"]
    away_team = game["away_team"]
    game_id = game["game_id"]
    home_starter_name = game.get("home_starter")
    away_starter_name = game.get("away_starter")
    home_starter_id = game.get("home_starter_id")
    away_starter_id = game.get("away_starter_id")

    game_time = game.get("game_time_et", "")
    try:
        import datetime as dt
        from datetime import timezone
        gdt = dt.datetime.fromisoformat(game_time.replace("Z", "+00:00"))
        eastern = dt.timezone(dt.timedelta(hours=-4))
        gdt_et = gdt.astimezone(eastern)
        time_label = gdt_et.strftime("%-I:%M %p ET")
    except Exception:
        time_label = "TBD"

    st.title(f"{away_team} @ {home_team}")
    st.caption(f"{selected_date.strftime('%B %-d, %Y')} · {time_label}")

    # --- Weather + Last 5 Games ---
    _render_game_context(
        home_team_id=game["home_team_id"],
        away_team_id=game["away_team_id"],
        home_team=home_team,
        away_team=away_team,
        season=CURRENT_SEASON,
    )

    # Fetch handedness for starters
    starter_ids = [i for i in [home_starter_id, away_starter_id] if i]
    handedness = {}
    if starter_ids:
        try:
            handedness = fetch_handedness(starter_ids)
        except Exception:
            pass

    home_hand = handedness.get(home_starter_id, {}).get("pitch_hand", "R") if home_starter_id else "R"
    away_hand = handedness.get(away_starter_id, {}).get("pitch_hand", "R") if away_starter_id else "R"

    fg_pitching = _load_fg_pitching(CURRENT_SEASON)
    fg_batting = _load_fg_batting(CURRENT_SEASON)

    # Lineups
    home_lineup = get_confirmed_lineup(game_id, "home")
    away_lineup = get_confirmed_lineup(game_id, "away")

    # Build pitcher profiles (need opposing lineup K% first — use default if lineup missing)
    home_lineup_k_pct = 0.228
    away_lineup_k_pct = 0.228

    # Build profiles
    away_profile = _build_pitcher_profile(away_starter_name, away_starter_id, fg_pitching, CURRENT_SEASON, home_lineup_k_pct)
    home_profile = _build_pitcher_profile(home_starter_name, home_starter_id, fg_pitching, CURRENT_SEASON, away_lineup_k_pct)

    # Build lineup rows
    home_batter_rows, home_batter_statcast = _build_lineup_rows(
        home_lineup, fg_batting, away_hand,
        away_profile["k_pct"], None, CURRENT_SEASON,
    )
    away_batter_rows, away_batter_statcast = _build_lineup_rows(
        away_lineup, fg_batting, home_hand,
        home_profile["k_pct"], None, CURRENT_SEASON,
    )

    # Recalc lineup K% if we have data
    if home_batter_rows:
        k_vals = [r["k_pct"] for r in home_batter_rows if r.get("k_pct")]
        if k_vals:
            home_lineup_k_pct = sum(k_vals) / len(k_vals)
    if away_batter_rows:
        k_vals = [r["k_pct"] for r in away_batter_rows if r.get("k_pct")]
        if k_vals:
            away_lineup_k_pct = sum(k_vals) / len(k_vals)

    home_lineup_agg = compute_lineup_aggregate(home_batter_rows) if home_batter_rows else {}
    away_lineup_agg = compute_lineup_aggregate(away_batter_rows) if away_batter_rows else {}

    preview = build_game_preview(
        home_pitcher_profile=home_profile,
        away_pitcher_profile=away_profile,
        home_lineup_aggregate=home_lineup_agg,
        away_lineup_aggregate=away_lineup_agg,
        home_team=home_team,
        away_team=away_team,
    )

    # --- Prediction panel ---
    render_prediction_panel(preview, home_team, away_team)
    st.divider()

    # --- Pitcher tabs ---
    home_tab_label = f"⚾ {home_starter_name or home_team + ' SP'}"
    away_tab_label = f"⚾ {away_starter_name or away_team + ' SP'}"
    tab_away_p, tab_home_p = st.tabs([away_tab_label, home_tab_label])

    with tab_away_p:
        render_pitcher_analysis(
            pitcher_name=away_starter_name or "TBD",
            team=away_team,
            fg_row=away_profile["fg_row"],
            statcast_df=away_profile["statcast_df"],
            platoon_splits=away_profile["platoon_splits"],
            pitch_mix=away_profile["pitch_mix"],
            velocity_trend=away_profile["velocity_trend"],
            recent_form=away_profile["recent_form"],
            proj=away_profile["projection"],
            league_avg=LEAGUE_AVG,
        )

    with tab_home_p:
        render_pitcher_analysis(
            pitcher_name=home_starter_name or "TBD",
            team=home_team,
            fg_row=home_profile["fg_row"],
            statcast_df=home_profile["statcast_df"],
            platoon_splits=home_profile["platoon_splits"],
            pitch_mix=home_profile["pitch_mix"],
            velocity_trend=home_profile["velocity_trend"],
            recent_form=home_profile["recent_form"],
            proj=home_profile["projection"],
            league_avg=LEAGUE_AVG,
        )

    st.divider()

    # --- Lineup tabs ---
    tab_away_l, tab_home_l = st.tabs([f"🔢 {away_team} Lineup", f"🔢 {home_team} Lineup"])

    with tab_away_l:
        render_lineup_analysis(
            lineup=away_lineup,
            batter_fg_rows=fg_batting,
            batter_statcast=away_batter_statcast,
            opposing_pitcher_name=home_starter_name or "TBD",
            opposing_pitcher_hand=home_hand,
            batter_analysis_rows=away_batter_rows,
        )

    with tab_home_l:
        render_lineup_analysis(
            lineup=home_lineup,
            batter_fg_rows=fg_batting,
            batter_statcast=home_batter_statcast,
            opposing_pitcher_name=away_starter_name or "TBD",
            opposing_pitcher_hand=away_hand,
            batter_analysis_rows=home_batter_rows,
        )


if __name__ == "__main__":
    main()
