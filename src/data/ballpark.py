"""Park factor lookup by MLB team_id."""
from __future__ import annotations

# 5-year regressed park factor (100 = neutral, >100 = hitter-friendly)
PARK_FACTORS: dict[int, int] = {
    108: 97,   # Angels - Angel Stadium
    109: 100,  # Diamondbacks - Chase Field
    110: 97,   # Orioles - Camden Yards
    111: 104,  # Red Sox - Fenway Park
    112: 102,  # Cubs - Wrigley Field
    113: 103,  # Reds - Great American Ball Park
    114: 98,   # Guardians - Progressive Field
    115: 115,  # Rockies - Coors Field
    116: 97,   # Tigers - Comerica Park
    117: 101,  # Astros - Minute Maid Park
    118: 98,   # Royals - Kauffman Stadium
    119: 96,   # Dodgers - Dodger Stadium
    120: 101,  # Nationals - Nationals Park
    121: 99,   # Mets - Citi Field
    133: 100,  # Athletics - Sutter Health Park
    134: 97,   # Pirates - PNC Park
    135: 95,   # Padres - Petco Park
    136: 97,   # Mariners - T-Mobile Park
    137: 93,   # Giants - Oracle Park
    138: 99,   # Cardinals - Busch Stadium
    139: 97,   # Rays - Tropicana Field
    140: 101,  # Rangers - Globe Life Field
    141: 100,  # Blue Jays - Rogers Centre
    142: 100,  # Twins - Target Field
    143: 104,  # Phillies - Citizens Bank Park
    144: 101,  # Braves - Truist Park
    145: 101,  # White Sox - Guaranteed Rate Field
    146: 100,  # Marlins - loanDepot park
    147: 108,  # Yankees - Yankee Stadium
    158: 104,  # Brewers - American Family Field
}


def park_factor_label(team_id: int) -> str:
    pf = PARK_FACTORS.get(team_id, 100)
    if pf >= 110:
        return f"PF {pf} 🔥"
    if pf >= 105:
        return f"PF {pf} ↑"
    if pf <= 94:
        return f"PF {pf} ↓↓"
    if pf <= 97:
        return f"PF {pf} ↓"
    return f"PF {pf}"
