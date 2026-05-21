"""Statcast and FanGraphs data via pybaseball."""
from __future__ import annotations

import datetime

import pandas as pd
import pybaseball

from src.data.cache import cached

pybaseball.cache.enable()


def _season_dates(season: int) -> tuple[str, str]:
    start = f"{season}-03-20"
    today = datetime.date.today()
    end = today.strftime("%Y-%m-%d") if today.year == season else f"{season}-11-01"
    return start, end


def get_pitcher_statcast(pitcher_mlb_id: int, season: int, last_n_starts: int = 10) -> pd.DataFrame:
    """Fetch season pitch-level Statcast data for a pitcher."""
    start, end = _season_dates(season)

    def fetch():
        df = pybaseball.statcast_pitcher(start, end, player_id=pitcher_mlb_id)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.reset_index(drop=True)

    return cached(f"statcast_pitcher_{pitcher_mlb_id}_{season}", fetch, ttl_hours=12.0)


def get_batter_statcast(batter_mlb_id: int, season: int) -> pd.DataFrame:
    """Fetch season batted-ball Statcast data for a batter."""
    start, end = _season_dates(season)

    def fetch():
        df = pybaseball.statcast_batter(start, end, player_id=batter_mlb_id)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.reset_index(drop=True)
        if "launch_speed" in df.columns:
            df["hard_hit"] = df["launch_speed"] >= 95
        return df

    return cached(f"statcast_batter_{batter_mlb_id}_{season}", fetch, ttl_hours=12.0)


def _bref_pitching_to_fg_style(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Baseball Reference pitching columns to FanGraphs-compatible names."""
    df = df.copy()
    if "Lev" in df.columns:
        df = df[df["Lev"].str.startswith("Maj", na=False)].reset_index(drop=True)
    # Compute rate stats from counting stats
    if "SO" in df.columns and "BF" in df.columns:
        bf = df["BF"].replace(0, pd.NA)
        df["K%"] = df["SO"] / bf
        df["BB%"] = df["BB"] / bf if "BB" in df.columns else pd.NA
    # Rename traditional stats (including BR-specific column names)
    rename = {"ERA": "ERA", "WHIP": "WHIP", "IP": "IP", "BAbip": "BABIP"}
    for src, dst in rename.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]
    # Use ERA as FIP proxy when FIP unavailable
    if "FIP" not in df.columns and "ERA" in df.columns:
        df["FIP"] = df["ERA"]
    return df


def _bref_batting_to_fg_style(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Baseball Reference batting columns to FanGraphs-compatible names."""
    df = df.copy()
    if "Lev" in df.columns:
        df = df[df["Lev"].str.startswith("Maj", na=False)].reset_index(drop=True)
    # Compute rate stats
    if "SO" in df.columns and "PA" in df.columns:
        pa = df["PA"].replace(0, pd.NA)
        df["K%"] = df["SO"] / pa
        df["BB%"] = df["BB"] / pa if "BB" in df.columns else pd.NA
    # Rename traditional stats to FG names
    if "BA" in df.columns and "AVG" not in df.columns:
        df["AVG"] = df["BA"]
    return df


def _merge_statcast_expected(df: pd.DataFrame, sc_df: pd.DataFrame, id_col: str, sc_id_col: str) -> pd.DataFrame:
    """Merge xwOBA from Baseball Savant expected stats into a leaderboard df."""
    if sc_df.empty or id_col not in df.columns or sc_id_col not in sc_df.columns:
        return df
    sc_subset = sc_df[[sc_id_col, "est_woba"]].rename(
        columns={"est_woba": "xwOBA", sc_id_col: id_col}
    )
    sc_subset[id_col] = sc_subset[id_col].astype(str)
    df[id_col] = df[id_col].astype(str)
    return df.merge(sc_subset, on=id_col, how="left")


def get_pitcher_season_leaderboard(season: int) -> pd.DataFrame:
    """Pitcher leaderboard: FanGraphs first, Baseball Reference fallback."""
    def fetch():
        try:
            df = pybaseball.pitching_stats(season, season, qual=1)
            if df is not None and not df.empty:
                return df.reset_index(drop=True)
        except Exception:
            pass
        # Fallback: Baseball Reference
        df = pybaseball.pitching_stats_bref(season)
        if df is None or df.empty:
            return pd.DataFrame()
        df = _bref_pitching_to_fg_style(df)
        # Supplement with xERA from Statcast
        try:
            sc_df = pybaseball.statcast_pitcher_expected_stats(season)
            if sc_df is not None and not sc_df.empty and "mlbID" in df.columns:
                sc_subset = sc_df[["player_id", "xera"]].rename(
                    columns={"xera": "xFIP", "player_id": "mlbID"}
                )
                sc_subset["mlbID"] = sc_subset["mlbID"].astype(str)
                df["mlbID"] = df["mlbID"].astype(str)
                df = df.merge(sc_subset, on="mlbID", how="left")
        except Exception:
            pass
        return df.reset_index(drop=True)

    return cached(f"fg_pitching_{season}", fetch, ttl_hours=6.0)


def get_batter_season_leaderboard(season: int) -> pd.DataFrame:
    """Batter leaderboard: FanGraphs first, Baseball Reference fallback."""
    def fetch():
        try:
            df = pybaseball.batting_stats(season, season, qual=1)
            if df is not None and not df.empty:
                return df.reset_index(drop=True)
        except Exception:
            pass
        # Fallback: Baseball Reference
        df = pybaseball.batting_stats_bref(season)
        if df is None or df.empty:
            return pd.DataFrame()
        df = _bref_batting_to_fg_style(df)
        # Supplement with xwOBA from Statcast
        try:
            sc_df = pybaseball.statcast_batter_expected_stats(season)
            if sc_df is not None and not sc_df.empty and "mlbID" in df.columns:
                df = _merge_statcast_expected(df, sc_df, "mlbID", "player_id")
        except Exception:
            pass
        return df.reset_index(drop=True)

    return cached(f"fg_batting_{season}", fetch, ttl_hours=6.0)


def resolve_player_ids(name: str, leaderboard_df: pd.DataFrame | None = None) -> dict:
    """Return {'mlb_id': int, 'fg_id': int} for a player name."""
    import unicodedata

    def norm(s: str) -> str:
        return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()

    parts = name.strip().split()
    if len(parts) < 2:
        raise ValueError(f"Cannot parse name: {name!r}")
    last, first = parts[-1], parts[0]
    try:
        result = pybaseball.playerid_lookup(last, first)
        if result is not None and not result.empty:
            row = result.iloc[0]
            return {
                "mlb_id": int(row.get("key_mlbam", 0)),
                "fg_id": int(row.get("key_fangraphs", 0)),
            }
    except Exception:
        pass

    if leaderboard_df is not None and not leaderboard_df.empty and "Name" in leaderboard_df.columns:
        name_norm = norm(name)
        for _, row in leaderboard_df.iterrows():
            if norm(str(row.get("Name", ""))) == name_norm:
                return {"mlb_id": 0, "fg_id": int(row.get("IDfg", 0))}

    raise ValueError(f"Could not resolve player ID for {name!r}")
