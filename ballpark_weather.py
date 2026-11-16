"""
ballpark_weather.py
Fetches game-time weather per MLB stadium from Open-Meteo (free, no API key) and
converts it into a HR/offense environment multiplier.

Two physical effects, both well-documented:
  1. TEMPERATURE: warm air is less dense -> ball carries farther.
     ~+1% HR probability per +1°F above a ~70°F baseline (Dartmouth / Alan Nathan).
  2. WIND: wind blowing OUT toward the outfield adds carry; blowing IN kills fly balls.
     We compare wind direction to each park's home-plate->center-field bearing.

Domed/retractable-closed parks are weather-neutral (multiplier 1.0).
"""
import requests
from datetime import datetime

# (lat, lon, cf_bearing_degrees, is_dome)
# cf_bearing = compass heading from home plate toward center field (0=N,90=E,180=S,270=W).
# Wind blowing FROM the opposite of this bearing = blowing OUT to center.
STADIUMS = {
    'ARI': (33.4455, -112.0667, 0,   True),   # Chase Field (retractable, usually closed in heat)
    'ATL': (33.8908, -84.4678, 25,   False),  # Truist Park
    'BAL': (39.2839, -76.6217, 30,   False),  # Camden Yards
    'BOS': (42.3467, -71.0972, 45,   False),  # Fenway
    'CHC': (41.9484, -87.6553, 30,   False),  # Wrigley — notoriously wind-driven
    'CWS': (41.8300, -87.6339, 135,  False),  # Rate Field
    'CIN': (39.0975, -84.5069, 100,  False),  # Great American
    'CLE': (41.4962, -81.6852, 0,    False),  # Progressive
    'COL': (39.7559, -104.9942, 0,   False),  # Coors — altitude already in park factor
    'DET': (42.3390, -83.0485, 150,  False),  # Comerica
    'HOU': (29.7572, -95.3556, 345,  True),   # Daikin Park (retractable)
    'KC':  (39.0517, -94.4803, 50,   False),  # Kauffman — wind suppresses HR per Statcast
    'LAA': (33.8003, -117.8827, 40,  False),  # Angel Stadium
    'LAD': (34.0739, -118.2400, 25,  False),  # Dodger Stadium
    'MIA': (25.7780, -80.2197, 30,   True),   # loanDepot (retractable)
    'MIL': (43.0280, -87.9712, 0,    True),   # American Family (retractable)
    'MIN': (44.9817, -93.2776, 90,   False),  # Target Field
    'NYM': (40.7571, -73.8458, 25,   False),  # Citi Field — wind aids HR per Statcast
    'NYY': (40.8296, -73.9262, 25,   False),  # Yankee Stadium
    'OAK': (38.5667, -121.5000, 60,  False),  # Sutter Health Park (Sacramento) — hot, hitter-friendly
    'PHI': (39.9061, -75.1665, 15,   False),  # Citizens Bank
    'PIT': (40.4469, -80.0057, 120,  False),  # PNC Park
    'SD':  (32.7073, -117.1566, 0,   False),  # Petco — marine layer, suppresses
    'SF':  (37.7786, -122.3893, 95,  False),  # Oracle — cold, heavy air, suppresses
    'SEA': (47.5914, -122.3325, 50,  True),   # T-Mobile (retractable)
    'STL': (38.6226, -90.1928, 60,   False),  # Busch
    'TB':  (27.7683, -82.6534, 0,    True),   # Tropicana — full dome, weather-neutral
    'TEX': (32.7473, -97.0847, 0,    True),   # Globe Life (retractable, usually closed in heat)
    'TOR': (43.6414, -79.3894, 0,    True),   # Rogers Centre (retractable)
    'WSH': (38.8730, -77.0074, 30,   False),  # Nationals Park
}


def _angular_diff(a, b):
    """Smallest absolute difference between two compass bearings, 0-180."""
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def fetch_game_weather(team_abbrev, game_hour_local=19):
    """Return a dict with temp_f, wind_mph, wind_out_component, and hr_mult for a team's park.
    game_hour_local: approximate local start hour (24h). Defaults to 7pm.
    Returns hr_mult=1.0 (neutral) for domes or on any failure — fail safe, never crash scoring."""
    info = STADIUMS.get(team_abbrev)
    if not info:
        return {'temp_f': None, 'wind_mph': None, 'wind_out': None, 'hr_mult': 1.0, 'note': 'no park'}
    lat, lon, cf_bearing, is_dome = info
    if is_dome:
        return {'temp_f': None, 'wind_mph': None, 'wind_out': None, 'hr_mult': 1.0, 'note': 'dome/neutral'}

    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
               f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m"
               f"&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto&forecast_days=2")
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return {'temp_f': None, 'wind_mph': None, 'wind_out': None, 'hr_mult': 1.0, 'note': f'http {r.status_code}'}
        data = r.json()['hourly']
        # Pick the hour nearest game time today
        times = data['time']
        target = None
        today = datetime.now().strftime('%Y-%m-%d')
        for i, t in enumerate(times):
            if t.startswith(today) and t.endswith(f"T{game_hour_local:02d}:00"):
                target = i; break
        if target is None:
            target = min(range(len(times)), key=lambda i: abs(i - game_hour_local))
        temp_f = data['temperature_2m'][target]
        wind_mph = data['wind_speed_10m'][target]
        wind_dir = data['wind_direction_10m'][target]  # direction wind is coming FROM

        # Wind blowing OUT to CF means it comes FROM home plate side = opposite of cf_bearing.
        # The "out" component = wind speed projected onto the home->CF axis.
        # If wind_from is opposite cf_bearing (diff ~180), it blows straight out.
        import math
        # angle between where wind comes FROM and the direction toward CF
        diff_from_cf = _angular_diff(wind_dir, cf_bearing)
        # wind blowing OUT = coming from behind home (diff near 180). component = cos.
        out_component = -math.cos(math.radians(diff_from_cf)) * wind_mph  # +out, -in

        # ── HR multiplier ──────────────────────────────────────────────────
        # Temperature: ~1% per °F vs 70°F baseline, capped.
        temp_mult = 1.0 + (temp_f - 70) * 0.010
        temp_mult = max(0.93, min(1.10, temp_mult))
        # Wind: each mph of OUT-carry ~ +1.3% HR, IN ~ symmetric; capped.
        wind_mult = 1.0 + out_component * 0.013
        wind_mult = max(0.85, min(1.18, wind_mult))
        hr_mult = round(temp_mult * wind_mult, 3)
        hr_mult = max(0.82, min(1.25, hr_mult))

        return {
            'temp_f': round(temp_f),
            'wind_mph': round(wind_mph),
            'wind_out': round(out_component, 1),   # + = blowing out, - = blowing in
            'hr_mult': hr_mult,
            'note': 'ok',
        }
    except Exception as e:
        return {'temp_f': None, 'wind_mph': None, 'wind_out': None, 'hr_mult': 1.0, 'note': f'err {str(e)[:30]}'}


def build_weather_table(team_abbrevs, game_hour_local=19):
    """Fetch weather for a set of team parks; return {team: weatherdict}. Used by the app."""
    out = {}
    for t in set(team_abbrevs):
        out[t] = fetch_game_weather(t, game_hour_local)
    return out


if __name__ == "__main__":
    # quick self-test
    for t in ['CHC', 'OAK', 'SF', 'TB', 'COL']:
        print(t, fetch_game_weather(t))
