"""Tests for game preview / narrative generation."""
from __future__ import annotations

from src.models.game_preview import build_game_preview


def _make_profile(name: str, quality_start: bool) -> dict:
    return {
        "name": name,
        "projection": {
            "proj_ip": 6.0 if quality_start else 4.5,
            "proj_k": 6.0,
            "proj_er": 2.5 if quality_start else 4.0,
            "quality_start": quality_start,
            "confidence": "High",
        },
    }


def _make_agg(threat_score: float, xwoba: float = 0.310) -> dict:
    return {
        "avg_xwoba": xwoba,
        "avg_k_pct": 0.22,
        "avg_bb_pct": 0.08,
        "avg_barrel_pct": 0.08,
        "avg_hard_hit_pct": 0.40,
        "lineup_threat_score": threat_score,
        "top_threats": ["Player A", "Player B"],
    }


def test_build_game_preview_pitcher_duel_narrative():
    preview = build_game_preview(
        home_pitcher_profile=_make_profile("Gerrit Cole", quality_start=True),
        away_pitcher_profile=_make_profile("Max Scherzer", quality_start=True),
        home_lineup_aggregate=_make_agg(5.5),
        away_lineup_aggregate=_make_agg(5.5),
        home_team="New York Yankees",
        away_team="Texas Rangers",
    )
    assert "pitcher's duel" in preview["narrative"].lower()


def test_build_game_preview_dominant_pitcher_narrative():
    preview = build_game_preview(
        home_pitcher_profile=_make_profile("Sandy Alcantara", quality_start=True),
        away_pitcher_profile=_make_profile("Some Pitcher", quality_start=False),
        home_lineup_aggregate=_make_agg(4.0),   # weak lineup threat
        away_lineup_aggregate=_make_agg(6.0),
        home_team="Miami Marlins",
        away_team="Pittsburgh Pirates",
    )
    # Away pitcher is dominant vs weak home lineup
    assert "clear favorite" in preview["narrative"].lower() or "mixed" in preview["narrative"].lower()
    assert preview["home_pitcher_proj"]["quality_start"] is True
