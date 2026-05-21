"""Per-batter matchup scores and lineup aggregates."""
from __future__ import annotations


def compute_batter_matchup_score(
    batter_xwoba: float | None,
    batter_k_pct: float,
    batter_bb_pct: float,
    batter_barrel_pct: float | None,
    pitcher_k_pct: float,
    pitcher_bb_pct: float,
    pitcher_gb_pct: float | None,
    platoon_advantage: bool,
) -> float:
    """Compute a 1-10 matchup score for a batter vs. a starting pitcher (higher = better for batter)."""
    # xwOBA score (0-4)
    if batter_xwoba is None:
        xwoba_score = 2.0
    else:
        xwoba_score = ((batter_xwoba - 0.200) / (0.450 - 0.200)) * 4
        xwoba_score = max(0.0, min(4.0, xwoba_score))

    # Contact score (0-2)
    if batter_k_pct < pitcher_k_pct * 0.8:
        contact_score = 2.0
    elif batter_k_pct > pitcher_k_pct * 1.2:
        contact_score = 0.0
    else:
        contact_score = 1.0

    # Power score (0-3)
    if batter_barrel_pct is None:
        power_score = 0.0
    elif batter_barrel_pct >= 0.10:
        power_score = 3.0
    elif batter_barrel_pct >= 0.07:
        power_score = 2.0
    elif batter_barrel_pct >= 0.04:
        power_score = 1.0
    else:
        power_score = 0.0

    # Platoon bonus (0-1)
    platoon_bonus = 1.0 if platoon_advantage else 0.0

    raw = xwoba_score + contact_score + power_score + platoon_bonus
    return round(max(1.0, min(10.0, raw)), 1)


def compute_lineup_aggregate(batter_rows: list[dict]) -> dict:
    """Aggregate lineup-level metrics from a list of per-batter dicts."""
    def safe_avg(vals):
        clean = [v for v in vals if v is not None]
        return sum(clean) / len(clean) if clean else None

    xwoba_vals = [r.get("xwoba") for r in batter_rows]
    k_vals = [r.get("k_pct") for r in batter_rows]
    bb_vals = [r.get("bb_pct") for r in batter_rows]
    barrel_vals = [r.get("barrel_pct") for r in batter_rows]
    hh_vals = [r.get("hard_hit_pct") for r in batter_rows]
    score_vals = [r.get("matchup_score") for r in batter_rows]

    sorted_by_score = sorted(
        batter_rows, key=lambda r: r.get("matchup_score", 0), reverse=True
    )
    top_threats = [r["name"] for r in sorted_by_score[:3] if r.get("name")]

    return {
        "avg_xwoba": safe_avg(xwoba_vals),
        "avg_k_pct": safe_avg(k_vals),
        "avg_bb_pct": safe_avg(bb_vals),
        "avg_barrel_pct": safe_avg(barrel_vals),
        "avg_hard_hit_pct": safe_avg(hh_vals),
        "lineup_threat_score": safe_avg(score_vals),
        "top_threats": top_threats,
    }


def classify_lineup_strength(avg_xwoba: float) -> str:
    """Return lineup strength tier based on avg xwOBA."""
    if avg_xwoba >= 0.360:
        return "Elite"
    if avg_xwoba >= 0.340:
        return "Above Avg"
    if avg_xwoba >= 0.315:
        return "Average"
    if avg_xwoba >= 0.290:
        return "Below Avg"
    return "Weak"


def has_platoon_advantage(bat_side: str, pitcher_hand: str) -> bool:
    """True if batter has platoon advantage (bats opposite of pitcher's throwing hand)."""
    return bat_side != pitcher_hand


def build_threat_why(barrel_pct: float | None, platoon_advantage: bool, xwoba: float | None) -> str:
    """Generate deterministic 'why' explanation for a top threat batter."""
    if barrel_pct is not None and barrel_pct >= 0.10 and platoon_advantage:
        return "High barrel rate + platoon advantage creates significant damage risk."
    if barrel_pct is not None and barrel_pct >= 0.10:
        return "High barrel rate creates power threat regardless of platoon."
    if platoon_advantage and xwoba is not None and xwoba >= 0.340:
        return "Strong hitter with platoon advantage against this starter."
    return "Consistent hard contact makes this a tough matchup for the starter."
