"""Weather satellite pass prediction utility.

Shared prediction logic used by both the API endpoint and the auto-scheduler.
"""

from __future__ import annotations

import datetime
from typing import Any

from utils.logging import get_logger
from utils.weather_sat import WEATHER_SATELLITES

logger = get_logger('intercept.weather_sat_predict')


def _format_utc_iso(dt: datetime.datetime) -> str:
    """Return an ISO8601 UTC timestamp with a single timezone designator."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.isoformat().replace('+00:00', 'Z')


def predict_passes(
    lat: float,
    lon: float,
    hours: int = 24,
    min_elevation: float = 15.0,
    include_trajectory: bool = False,
    include_ground_track: bool = False,
) -> list[dict[str, Any]]:
    """Predict upcoming weather satellite passes for an observer location.

    Args:
        lat: Observer latitude (-90 to 90)
        lon: Observer longitude (-180 to 180)
        hours: Hours ahead to predict (1-72)
        min_elevation: Minimum max elevation in degrees (0-90)
        include_trajectory: Include az/el trajectory points (30 points)
        include_ground_track: Include lat/lon ground track points (60 points)

    Returns:
        List of pass dicts sorted by start time.

    Raises:
        ImportError: If skyfield is not installed.
    """
    from skyfield.almanac import find_discrete
    from skyfield.api import EarthSatellite, load, wgs84

    from data.satellites import TLE_SATELLITES

    # Use live TLE cache from satellite module if available (refreshed from CelesTrak)
    tle_source = TLE_SATELLITES
    try:
        from routes.satellite import _tle_cache
        if _tle_cache:
            tle_source = _tle_cache
    except ImportError:
        pass

    ts = load.timescale()
    observer = wgs84.latlon(lat, lon)
    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + datetime.timedelta(hours=hours))

    all_passes: list[dict[str, Any]] = []

    for sat_key, sat_info in WEATHER_SATELLITES.items():
        if not sat_info['active']:
            continue

        tle_data = tle_source.get(sat_info['tle_key'])
        if not tle_data:
            continue

        satellite = EarthSatellite(tle_data[1], tle_data[2], tle_data[0], ts)

        def above_horizon(t, _sat=satellite):
            diff = _sat - observer
            topocentric = diff.at(t)
            alt, _, _ = topocentric.altaz()
            return alt.degrees > 0

        above_horizon.step_days = 1 / 720

        try:
            times, events = find_discrete(t0, t1, above_horizon)
        except Exception:
            continue

        i = 0
        while i < len(times):
            if i < len(events) and events[i]:  # Rising
                rise_time = times[i]
                set_time = None

                for j in range(i + 1, len(times)):
                    if not events[j]:  # Setting
                        set_time = times[j]
                        i = j
                        break
                else:
                    i += 1
                    continue

                if set_time is None:
                    i += 1
                    continue

                rise_dt = rise_time.utc_datetime()
                set_dt = set_time.utc_datetime()
                duration_seconds = (
                    set_dt - rise_dt
                ).total_seconds()
                duration_minutes = round(duration_seconds / 60, 1)

                # Calculate max elevation (always) and trajectory points (only if requested)
                max_el = 0.0
                max_el_az = 0.0
                trajectory: list[dict[str, float]] = []
                num_traj_points = 30

                for k in range(num_traj_points):
                    frac = k / (num_traj_points - 1)
                    t_point = ts.utc(
                        rise_time.utc_datetime()
                        + datetime.timedelta(seconds=duration_seconds * frac)
                    )
                    diff = satellite - observer
                    topocentric = diff.at(t_point)
                    alt, az, _ = topocentric.altaz()
                    if alt.degrees > max_el:
                        max_el = alt.degrees
                        max_el_az = az.degrees
                    if include_trajectory:
                        trajectory.append({
                            'el': float(max(0, alt.degrees)),
                            'az': float(az.degrees),
                        })

                if max_el < min_elevation:
                    i += 1
                    continue

                # Rise/set azimuths
                rise_topo = (satellite - observer).at(rise_time)
                _, rise_az, _ = rise_topo.altaz()

                set_topo = (satellite - observer).at(set_time)
                _, set_az, _ = set_topo.altaz()

                pass_data: dict[str, Any] = {
                    'id': f"{sat_key}_{rise_dt.strftime('%Y%m%d%H%M%S')}",
                    'satellite': sat_key,
                    'name': sat_info['name'],
                    'frequency': sat_info['frequency'],
                    'mode': sat_info['mode'],
                    'startTime': rise_dt.strftime('%Y-%m-%d %H:%M UTC'),
                    'startTimeISO': _format_utc_iso(rise_dt),
                    'endTimeISO': _format_utc_iso(set_dt),
                    'maxEl': round(max_el, 1),
                    'maxElAz': round(max_el_az, 1),
                    'riseAz': round(rise_az.degrees, 1),
                    'setAz': round(set_az.degrees, 1),
                    'duration': duration_minutes,
                    'quality': (
                        'excellent' if max_el >= 60
                        else 'good' if max_el >= 30
                        else 'fair'
                    ),
                }

                if include_trajectory:
                    pass_data['trajectory'] = trajectory

                if include_ground_track:
                    ground_track: list[dict[str, float]] = []
                    for k in range(60):
                        frac = k / 59
                        t_point = ts.utc(
                            rise_time.utc_datetime()
                            + datetime.timedelta(seconds=duration_seconds * frac)
                        )
                        geocentric = satellite.at(t_point)
                        subpoint = wgs84.subpoint(geocentric)
                        ground_track.append({
                            'lat': float(subpoint.latitude.degrees),
                            'lon': float(subpoint.longitude.degrees),
                        })
                    pass_data['groundTrack'] = ground_track

                all_passes.append(pass_data)

            i += 1

    all_passes.sort(key=lambda p: p['startTimeISO'])
    return all_passes
