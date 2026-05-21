"""Pitcher metric computations from Statcast and FanGraphs data."""
from __future__ import annotations

import pandas as pd

FIP_CONSTANT = 3.15

# 2024 MLB league reference ranges for radar normalization
_RADAR_RANGES = {
    "k_pct":   {"worst": 0.14, "best": 0.36, "invert": False},
    "bb_pct":  {"worst": 0.12, "best": 0.04, "invert": True},
    "swstr":   {"worst": 0.06, "best": 0.18, "invert": False},
    "gb_pct":  {"worst": 0.30, "best": 0.62, "invert": False},
    "xfip":    {"worst": 5.50, "best": 2.80, "invert": True},
}

LEAGUE_AVG = {
    "era": 4.25, "fip": 4.20, "k_pct": 0.228, "bb_pct": 0.083,
    "whip": 1.30, "hr9": 1.20,
}


def compute_fip(hr: int, bb: int, hbp: int, k: int, ip: float) -> float | None:
    """Calculate FIP from raw counting stats."""
    if ip <= 0:
        return None
    return (13 * hr + 3 * (bb + hbp) - 2 * k) / ip + FIP_CONSTANT


def compute_babip_allowed(h: int, hr: int, ab: int, k: int, sf: int) -> float | None:
    """Calculate pitcher's allowed BABIP."""
    denom = ab - k - hr + sf
    if denom <= 0 or h < hr:
        return None
    return round((h - hr) / denom, 3)


def compute_pitch_mix(statcast_df: pd.DataFrame) -> pd.DataFrame:
    """Return pitch type usage % broken down by count state (ahead/behind/neutral)."""
    if statcast_df.empty:
        raise ValueError("statcast_df is empty")

    df = statcast_df.copy()
    df["count_state"] = "neutral"
    df.loc[df["strikes"] > df["balls"], "count_state"] = "ahead"
    df.loc[df["balls"] > df["strikes"], "count_state"] = "behind"

    total = len(df)
    rows = []
    for pt, group in df.groupby("pitch_type"):
        ahead = df[(df["pitch_type"] == pt) & (df["count_state"] == "ahead")]
        behind = df[(df["pitch_type"] == pt) & (df["count_state"] == "behind")]
        neutral = df[(df["pitch_type"] == pt) & (df["count_state"] == "neutral")]

        n_ahead = len(df[df["count_state"] == "ahead"])
        n_behind = len(df[df["count_state"] == "behind"])
        n_neutral = len(df[df["count_state"] == "neutral"])

        rows.append({
            "pitch_type": pt,
            "overall_pct": len(group) / total if total else 0.0,
            "ahead_pct": len(ahead) / n_ahead if n_ahead else 0.0,
            "behind_pct": len(behind) / n_behind if n_behind else 0.0,
            "neutral_pct": len(neutral) / n_neutral if n_neutral else 0.0,
            "avg_velocity": group["release_speed"].mean() if "release_speed" in group else None,
            "avg_spin_rate": group["release_spin_rate"].mean() if "release_spin_rate" in group else None,
            "avg_horizontal_break": group["pfx_x"].mean() if "pfx_x" in group else None,
            "avg_vertical_break": group["pfx_z"].mean() if "pfx_z" in group else None,
        })

    result = pd.DataFrame(rows).sort_values("overall_pct", ascending=False)
    return result.reset_index(drop=True)


def compute_velocity_trend(statcast_df: pd.DataFrame) -> pd.DataFrame:
    """Return avg 4-seam fastball velocity per game_date for the last 10 starts."""
    if statcast_df.empty:
        return pd.DataFrame(columns=["game_date", "avg_velo", "n_pitches"])

    ff = statcast_df[statcast_df["pitch_type"] == "FF"].copy()
    if ff.empty:
        return pd.DataFrame(columns=["game_date", "avg_velo", "n_pitches"])

    ff["game_date"] = pd.to_datetime(ff["game_date"])
    by_date = (
        ff.groupby("game_date")["release_speed"]
        .agg(avg_velo="mean", n_pitches="count")
        .reset_index()
        .sort_values("game_date")
        .tail(10)
    )
    return by_date.reset_index(drop=True)


def compute_platoon_splits(statcast_df: pd.DataFrame) -> dict:
    """Return K%, BB%, BABIP split by batter handedness."""
    if statcast_df.empty:
        raise ValueError("statcast_df is empty")

    result = {}
    for hand, label in [("L", "vs_lhh"), ("R", "vs_rhh")]:
        sub = statcast_df[statcast_df["stand"] == hand]
        if sub.empty:
            result[label] = {"k_pct": 0.0, "bb_pct": 0.0, "babip": 0.300, "n_pa": 0}
            continue

        pa_mask = sub["events"].notna() | (sub["description"] == "hit_into_play")
        pa_rows = sub[pa_mask]
        n_pa = len(pa_rows)

        k = (pa_rows["events"] == "strikeout").sum()
        bb = (pa_rows["events"] == "walk").sum()

        hit_events = {"single", "double", "triple", "home_run"}
        h = pa_rows["events"].isin(hit_events).sum()
        hr = (pa_rows["events"] == "home_run").sum()
        ab = pa_rows["events"].isin(hit_events | {"strikeout", "field_out", "force_out",
                                                   "grounded_into_double_play",
                                                   "double_play", "fielders_choice_out"}).sum()
        denom = ab - k - hr
        babip = round((h - hr) / denom, 3) if denom > 0 and h >= hr else 0.300

        result[label] = {
            "k_pct": k / n_pa if n_pa else 0.0,
            "bb_pct": bb / n_pa if n_pa else 0.0,
            "babip": babip,
            "n_pa": int(n_pa),
        }
    return result


def compute_recent_form(statcast_df: pd.DataFrame, n_starts: int = 5) -> pd.DataFrame:
    """Return per-start rolling stats for the last n_starts."""
    if statcast_df.empty:
        return pd.DataFrame(columns=["game_date", "ip_approx", "k_total", "bb_total", "hr_total", "avg_velo"])

    df = statcast_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])

    rows = []
    for date, group in df.groupby("game_date"):
        pa_rows = group[group["events"].notna()]
        rows.append({
            "game_date": date,
            "ip_approx": round(len(group) / 15, 1),
            "k_total": int((pa_rows["events"] == "strikeout").sum()),
            "bb_total": int((pa_rows["events"] == "walk").sum()),
            "hr_total": int((pa_rows["events"] == "home_run").sum()),
            "avg_velo": round(group["release_speed"].mean(), 1) if "release_speed" in group else None,
        })

    result = (
        pd.DataFrame(rows)
        .sort_values("game_date")
        .tail(n_starts)
        .reset_index(drop=True)
    )
    return result


def compute_zone_heatmap(statcast_df: pd.DataFrame, pitch_type: str | None = None) -> pd.DataFrame:
    """Return plate_x, plate_z coordinates for pitches, optionally filtered by pitch_type."""
    if statcast_df.empty:
        return pd.DataFrame(columns=["plate_x", "plate_z", "description"])

    df = statcast_df.copy()
    if pitch_type:
        df = df[df["pitch_type"] == pitch_type]

    cols = ["plate_x", "plate_z", "description"]
    available = [c for c in cols if c in df.columns]
    return df[available].dropna(subset=["plate_x", "plate_z"]).reset_index(drop=True)


def compute_stuff_radar(fg_row: pd.Series, league_avg: dict) -> dict:
    """Return normalized 0-100 percentile scores for 5 stuff dimensions."""
    def normalize(val, worst, best, invert=False):
        if val is None or pd.isna(val):
            return 50.0
        if invert:
            score = (worst - val) / (worst - best) * 100
        else:
            score = (val - worst) / (best - worst) * 100
        return max(0.0, min(100.0, score))

    k_pct = fg_row.get("K%") or fg_row.get("k_pct")
    bb_pct = fg_row.get("BB%") or fg_row.get("bb_pct")
    swstr = fg_row.get("SwStr%") or fg_row.get("swstr_pct")
    gb_pct = fg_row.get("GB%") or fg_row.get("gb_pct")
    xfip = fg_row.get("xFIP") or fg_row.get("xfip")

    # FanGraphs stores these as decimals or percentages — normalize to decimal
    def as_decimal(v):
        if v is None or pd.isna(v):
            return None
        return v / 100.0 if v > 1.0 else v

    k_pct = as_decimal(k_pct)
    bb_pct = as_decimal(bb_pct)
    swstr = as_decimal(swstr)
    gb_pct = as_decimal(gb_pct)

    return {
        "K%": normalize(k_pct, **{k: v for k, v in _RADAR_RANGES["k_pct"].items()}),
        "BB% (lower=better)": normalize(bb_pct, **{k: v for k, v in _RADAR_RANGES["bb_pct"].items()}),
        "SwStr%": normalize(swstr, **{k: v for k, v in _RADAR_RANGES["swstr"].items()}),
        "GB%": normalize(gb_pct, **{k: v for k, v in _RADAR_RANGES["gb_pct"].items()}),
        "xFIP (lower=better)": normalize(xfip, **{k: v for k, v in _RADAR_RANGES["xfip"].items()}),
    }


def project_pitcher_game(
    k_pct: float,
    bb_pct: float,
    fip: float,
    xfip: float | None,
    avg_ip_per_start: float,
    opposing_lineup_k_pct: float,
    park_hr_factor: float = 1.0,
) -> dict:
    """Project this starter's line for today's game."""
    blended_k = k_pct * 0.60 + opposing_lineup_k_pct * 0.40
    proj_k = blended_k * (avg_ip_per_start * 4.3)

    true_era = xfip if xfip is not None else fip
    proj_er = (true_era / 9.0) * avg_ip_per_start * park_hr_factor

    quality_start = avg_ip_per_start >= 6.0 and proj_er <= 3.0

    if avg_ip_per_start >= 5.0 and xfip is not None:
        confidence = "High"
    elif avg_ip_per_start < 3.0 or xfip is None:
        confidence = "Low"
    else:
        confidence = "Medium"

    return {
        "proj_ip": round(avg_ip_per_start, 1),
        "proj_k": round(proj_k, 1),
        "proj_er": round(proj_er, 1),
        "quality_start": quality_start,
        "confidence": confidence,
    }
