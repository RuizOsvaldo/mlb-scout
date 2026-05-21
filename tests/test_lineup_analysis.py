"""Tests for lineup analysis computations."""
from __future__ import annotations

import pytest

from src.models.lineup_analysis import (
    classify_lineup_strength,
    compute_batter_matchup_score,
    compute_lineup_aggregate,
)


def test_batter_matchup_score_platoon_bonus():
    score_with = compute_batter_matchup_score(
        batter_xwoba=0.320,
        batter_k_pct=0.20,
        batter_bb_pct=0.09,
        batter_barrel_pct=0.06,
        pitcher_k_pct=0.25,
        pitcher_bb_pct=0.08,
        pitcher_gb_pct=0.45,
        platoon_advantage=True,
    )
    score_without = compute_batter_matchup_score(
        batter_xwoba=0.320,
        batter_k_pct=0.20,
        batter_bb_pct=0.09,
        batter_barrel_pct=0.06,
        pitcher_k_pct=0.25,
        pitcher_bb_pct=0.08,
        pitcher_gb_pct=0.45,
        platoon_advantage=False,
    )
    assert score_with == score_without + 1.0


def test_batter_matchup_score_clamps_to_1_10():
    # Maximum possible inputs
    high = compute_batter_matchup_score(
        batter_xwoba=0.600,
        batter_k_pct=0.01,
        batter_bb_pct=0.20,
        batter_barrel_pct=0.20,
        pitcher_k_pct=0.15,
        pitcher_bb_pct=0.08,
        pitcher_gb_pct=None,
        platoon_advantage=True,
    )
    assert high <= 10.0

    # Minimum possible inputs
    low = compute_batter_matchup_score(
        batter_xwoba=0.100,
        batter_k_pct=0.50,
        batter_bb_pct=0.02,
        batter_barrel_pct=0.00,
        pitcher_k_pct=0.30,
        pitcher_bb_pct=0.08,
        pitcher_gb_pct=None,
        platoon_advantage=False,
    )
    assert low >= 1.0


def test_compute_lineup_aggregate_skips_none_values():
    rows = [
        {"xwoba": 0.320, "k_pct": 0.20, "bb_pct": 0.09, "barrel_pct": None, "hard_hit_pct": 0.40, "matchup_score": 5.0, "name": "A"},
        {"xwoba": 0.340, "k_pct": 0.18, "bb_pct": 0.10, "barrel_pct": 0.08, "hard_hit_pct": None, "matchup_score": 6.0, "name": "B"},
    ]
    agg = compute_lineup_aggregate(rows)
    # avg_barrel_pct should only use the non-None value
    assert abs(agg["avg_barrel_pct"] - 0.08) < 0.001
    # avg_hard_hit_pct should only use the non-None value
    assert abs(agg["avg_hard_hit_pct"] - 0.40) < 0.001


def test_classify_lineup_strength_boundaries():
    assert classify_lineup_strength(0.370) == "Elite"
    assert classify_lineup_strength(0.350) == "Above Avg"
    assert classify_lineup_strength(0.325) == "Average"
    assert classify_lineup_strength(0.295) == "Below Avg"
    assert classify_lineup_strength(0.280) == "Weak"
