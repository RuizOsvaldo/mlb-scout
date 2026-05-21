"""Tests for pitcher profile computations."""
from __future__ import annotations

import pandas as pd
import pytest

from src.models.pitcher_profile import (
    compute_pitch_mix,
    compute_platoon_splits,
    compute_stuff_radar,
    project_pitcher_game,
)


def _make_statcast(n=50, pitch_type="FF", stand="R", balls=0, strikes=0) -> pd.DataFrame:
    return pd.DataFrame({
        "pitch_type": [pitch_type] * n,
        "stand": [stand] * n,
        "balls": [balls] * n,
        "strikes": [strikes] * n,
        "release_speed": [94.0] * n,
        "release_spin_rate": [2300.0] * n,
        "pfx_x": [0.5] * n,
        "pfx_z": [1.2] * n,
        "plate_x": [0.1] * n,
        "plate_z": [2.5] * n,
        "description": ["called_strike"] * n,
        "events": [None] * n,
        "game_date": ["2025-04-01"] * n,
    })


def test_compute_pitch_mix_counts_by_count_state():
    ahead = _make_statcast(20, "FF", balls=0, strikes=2)
    behind = _make_statcast(10, "SL", balls=3, strikes=0)
    neutral = _make_statcast(10, "FF", balls=1, strikes=1)
    df = pd.concat([ahead, behind, neutral], ignore_index=True)

    mix = compute_pitch_mix(df)
    assert not mix.empty
    ff_row = mix[mix["pitch_type"] == "FF"].iloc[0]
    assert ff_row["ahead_pct"] > 0
    sl_row = mix[mix["pitch_type"] == "SL"].iloc[0]
    assert sl_row["behind_pct"] > 0


def test_compute_platoon_splits_with_empty_df_raises():
    with pytest.raises(ValueError):
        compute_platoon_splits(pd.DataFrame())


def test_project_pitcher_game_quality_start_threshold():
    proj = project_pitcher_game(
        k_pct=0.27,
        bb_pct=0.08,
        fip=3.50,
        xfip=3.40,
        avg_ip_per_start=6.0,
        opposing_lineup_k_pct=0.22,
    )
    assert proj["quality_start"] is True
    assert proj["proj_ip"] == 6.0


def test_project_pitcher_game_confidence_low_ip():
    proj = project_pitcher_game(
        k_pct=0.25,
        bb_pct=0.09,
        fip=4.00,
        xfip=None,
        avg_ip_per_start=2.5,
        opposing_lineup_k_pct=0.22,
    )
    assert proj["confidence"] == "Low"


def test_compute_stuff_radar_clamps_to_100():
    row = pd.Series({
        "K%": 40.0,       # percentage form > 36% best → should clamp at 100
        "BB%": 1.0,       # very low → should clamp at 100
        "SwStr%": 25.0,   # above best
        "GB%": 70.0,      # above best
        "xFIP": 1.50,     # below best
    })
    scores = compute_stuff_radar(row, {})
    for key, val in scores.items():
        assert 0.0 <= val <= 100.0, f"{key} out of range: {val}"
