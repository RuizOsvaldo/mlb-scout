"""Ties pitcher and lineup into a single game prediction dict."""
from __future__ import annotations


def build_game_preview(
    home_pitcher_profile: dict,
    away_pitcher_profile: dict,
    home_lineup_aggregate: dict,
    away_lineup_aggregate: dict,
    home_team: str,
    away_team: str,
) -> dict:
    """Produce the top-level game preview summary dict."""
    home_proj = home_pitcher_profile.get("projection", {})
    away_proj = away_pitcher_profile.get("projection", {})

    home_threat = home_lineup_aggregate.get("lineup_threat_score", 5.0) or 5.0
    away_threat = away_lineup_aggregate.get("lineup_threat_score", 5.0) or 5.0

    home_pitcher_name = home_pitcher_profile.get("name", home_team + " Starter")
    away_pitcher_name = away_pitcher_profile.get("name", away_team + " Starter")

    home_qs = home_proj.get("quality_start", False)
    away_qs = away_proj.get("quality_start", False)

    # Deterministic narrative
    if home_qs and away_threat < 5.0:
        narrative = (
            f"{home_pitcher_name} projects as a clear favorite tonight, with a lineup that "
            f"strikes out frequently and lacks consistent hard contact."
        )
    elif away_qs and home_threat < 5.0:
        narrative = (
            f"{away_pitcher_name} projects as a clear favorite tonight, with a lineup that "
            f"strikes out frequently and lacks consistent hard contact."
        )
    elif home_qs and away_qs:
        narrative = (
            f"A pitcher's duel is likely — both starters project deep into games with limited "
            f"offensive support from either lineup."
        )
    else:
        top_threat_team = home_team if home_threat >= away_threat else away_team
        narrative = (
            f"Mixed signals — {home_pitcher_name} and {away_pitcher_name} both carry risk, "
            f"with {top_threat_team}'s lineup posing the greatest threat."
        )

    return {
        "home_pitcher_proj": home_proj,
        "away_pitcher_proj": away_proj,
        "home_lineup_agg": home_lineup_aggregate,
        "away_lineup_agg": away_lineup_aggregate,
        "home_top_threats": home_lineup_aggregate.get("top_threats", []),
        "away_top_threats": away_lineup_aggregate.get("top_threats", []),
        "narrative": narrative,
    }
