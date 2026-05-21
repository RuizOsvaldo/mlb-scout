"""Stadium weather via Open-Meteo (free, no API key) + park factor analysis."""
from __future__ import annotations

import json
import math
import time

import requests

from src.data.cache import CACHE_DIR

_TIMEOUT = 10

# (lat, lon, altitude_ft, cf_bearing_deg, is_controlled, park_name)
# cf_bearing = compass direction from home plate toward center field
STADIUMS: dict[int, tuple] = {
    108: (33.8003, -118.1644,  160,  0,   False, "Angel Stadium"),
    109: (33.4453, -112.0667, 1090, 335,  True,  "Chase Field"),         # retractable
    110: (39.2838,  -76.6217,   20, 340,  False, "Oriole Park at Camden Yards"),
    111: (42.3467,  -71.0972,   20,  90,  False, "Fenway Park"),
    112: (41.9484,  -87.6553,  595,  95,  False, "Wrigley Field"),
    113: (39.0979,  -84.5065,  490, 335,  False, "Great American Ball Park"),
    114: (41.4962,  -81.6852,  640, 160,  False, "Progressive Field"),
    115: (39.7559, -104.9942, 5200, 292,  False, "Coors Field"),
    116: (42.3390,  -83.0485,  600, 345,  False, "Comerica Park"),
    117: (29.7572,  -95.3555,   22, 230,  True,  "Minute Maid Park"),    # retractable
    118: (39.0517,  -94.4803,  750, 310,  False, "Kauffman Stadium"),
    119: (34.0739, -118.2400,  515, 320,  False, "Dodger Stadium"),
    120: (38.8730,  -77.0074,   25, 330,  False, "Nationals Park"),
    121: (40.7571,  -73.8458,   20, 350,  False, "Citi Field"),
    133: (38.5931, -121.5672,   30, 340,  False, "Sutter Health Park"),
    134: (40.4468,  -80.0058,  730, 320,  False, "PNC Park"),
    135: (32.7073, -117.1566,   20, 310,  False, "Petco Park"),
    136: (47.5914, -122.3325,   20, 330,  True,  "T-Mobile Park"),       # retractable
    137: (37.7785, -122.3893,    0, 350,  False, "Oracle Park"),
    138: (38.6226,  -90.1928,  460, 350,  False, "Busch Stadium"),
    139: (27.7682,  -82.6534,    0,   0,  True,  "Tropicana Field"),     # fixed dome
    140: (32.7510,  -97.0832,  550, 330,  True,  "Globe Life Field"),    # retractable
    141: (43.6414,  -79.3894,  300, 350,  True,  "Rogers Centre"),       # retractable
    142: (44.9817,  -93.2784,  830, 340,  False, "Target Field"),
    143: (39.9061,  -75.1665,   20, 340,  False, "Citizens Bank Park"),
    144: (33.8908,  -84.4678, 1020, 280,  False, "Truist Park"),
    145: (41.8299,  -87.6338,  595,  20,  False, "Guaranteed Rate Field"),
    146: (25.7781,  -80.2197,    8, 330,  True,  "loanDepot park"),      # retractable
    147: (40.8296,  -73.9262,   55, 330,  False, "Yankee Stadium"),
    158: (43.0280,  -87.9712,  635, 340,  True,  "American Family Field"), # retractable
}

_WX_CODE_DESC: dict[int, str] = {
    0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Freezing Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow",
    80: "Showers", 81: "Heavy Showers", 82: "Violent Showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ Hail",
}

_COMPASS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]


def _compass(deg: float) -> str:
    idx = round(deg / 22.5) % 16
    return _COMPASS[idx]


def _wind_tendency(speed_mph: float, wind_from_deg: float, cf_bearing: float) -> tuple[str, int]:
    """Return ('Blowing Out'|'Blowing In'|'Crosswind'|'Calm', score_delta)."""
    if speed_mph < 5:
        return "Calm", 0

    # Wind blows *toward* (wind_from + 180)
    wind_toward = (wind_from_deg + 180) % 360
    diff = abs((wind_toward - cf_bearing + 180) % 360 - 180)  # 0=toward CF, 180=into CF

    intensity = 2 if speed_mph >= 15 else 1
    if diff <= 45:
        return "Blowing Out", intensity
    if diff >= 135:
        return "Blowing In", -intensity
    return "Crosswind", 0


def fetch_weather(team_id: int) -> dict:
    """Return current weather dict for the home team's stadium."""
    if team_id not in STADIUMS:
        return {}

    key = f"weather_{team_id}"
    path = CACHE_DIR / f"{key}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < 1800:  # 30-min cache
        return json.loads(path.read_text())

    lat, lon, alt_ft, cf_bearing, is_controlled, park_name = STADIUMS[team_id]

    if is_controlled:
        result = {
            "park": park_name,
            "controlled": True,
            "temp_f": None,
            "wind_mph": None,
            "wind_dir": None,
            "conditions": "Controlled Environment",
            "rating": "Neutral",
            "rating_score": 0,
            "altitude_ft": alt_ft,
        }
        _write(path, result)
        return result

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,wind_direction_10m,weather_code,precipitation",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        cur = resp.json()["current"]
    except Exception:
        return {}

    temp_f      = cur["temperature_2m"]
    wind_mph    = cur["wind_speed_10m"]
    wind_from   = cur["wind_direction_10m"]
    wx_code     = cur.get("weather_code", 0)
    conditions  = _WX_CODE_DESC.get(wx_code, "Unknown")

    # --- Score ---
    score = 0

    # Temperature
    if temp_f >= 85:   score += 2
    elif temp_f >= 72: score += 1
    elif temp_f < 50:  score -= 2
    elif temp_f < 60:  score -= 1

    # Altitude (ball carries further at higher altitude)
    if alt_ft >= 5000:  score += 3   # Coors
    elif alt_ft >= 1000: score += 1

    # Wind direction relative to CF
    wind_label, wind_score = _wind_tendency(wind_mph, wind_from, cf_bearing)
    score += wind_score

    # Precipitation penalty
    if wx_code in (61, 63, 65, 80, 81, 82, 95, 96):
        score -= 2

    if score >= 3:      rating = "Very Hitter Friendly"
    elif score >= 1:    rating = "Hitter Friendly"
    elif score <= -3:   rating = "Very Pitcher Friendly"
    elif score <= -1:   rating = "Pitcher Friendly"
    else:               rating = "Neutral"

    result = {
        "park": park_name,
        "controlled": False,
        "temp_f": temp_f,
        "wind_mph": wind_mph,
        "wind_dir": _compass(wind_from),
        "wind_label": wind_label,
        "conditions": conditions,
        "rating": rating,
        "rating_score": score,
        "altitude_ft": alt_ft,
    }
    _write(path, result)
    return result


def _write(path, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
