"""Satellite tracking routes."""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from flask import Blueprint, jsonify, request, render_template, Response

from config import SHARED_OBSERVER_LOCATION_ENABLED

from data.satellites import TLE_SATELLITES
from utils.logging import satellite_logger as logger
from utils.validation import validate_latitude, validate_longitude, validate_hours, validate_elevation

satellite_bp = Blueprint('satellite', __name__, url_prefix='/satellite')

# Maximum response size for external requests (1MB)
MAX_RESPONSE_SIZE = 1024 * 1024

# Allowed hosts for TLE fetching
ALLOWED_TLE_HOSTS = ['celestrak.org', 'celestrak.com', 'www.celestrak.org', 'www.celestrak.com']

# Local TLE cache (can be updated via API)
_tle_cache = dict(TLE_SATELLITES)


def _fetch_iss_realtime(observer_lat: Optional[float] = None, observer_lon: Optional[float] = None) -> Optional[dict]:
    """
    Fetch real-time ISS position from external APIs.

    Returns position data dict or None if all APIs fail.
    """
    iss_lat = None
    iss_lon = None
    iss_alt = 420  # Default altitude in km
    source = None

    # Try primary API: Where The ISS At
    try:
        response = requests.get('https://api.wheretheiss.at/v1/satellites/25544', timeout=5)
        if response.status_code == 200:
            data = response.json()
            iss_lat = float(data['latitude'])
            iss_lon = float(data['longitude'])
            iss_alt = float(data.get('altitude', 420))
            source = 'wheretheiss'
    except Exception as e:
        logger.debug(f"Where The ISS At API failed: {e}")

    # Try fallback API: Open Notify
    if iss_lat is None:
        try:
            response = requests.get('http://api.open-notify.org/iss-now.json', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('message') == 'success':
                    iss_lat = float(data['iss_position']['latitude'])
                    iss_lon = float(data['iss_position']['longitude'])
                    source = 'open-notify'
        except Exception as e:
            logger.debug(f"Open Notify API failed: {e}")

    if iss_lat is None:
        return None

    result = {
        'satellite': 'ISS',
        'lat': iss_lat,
        'lon': iss_lon,
        'altitude': iss_alt,
        'source': source
    }

    # Calculate observer-relative data if location provided
    if observer_lat is not None and observer_lon is not None:
        # Earth radius in km
        earth_radius = 6371

        # Convert to radians
        lat1 = math.radians(observer_lat)
        lat2 = math.radians(iss_lat)
        lon1 = math.radians(observer_lon)
        lon2 = math.radians(iss_lon)

        # Haversine for ground distance
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        ground_distance = earth_radius * c

        # Calculate slant range
        slant_range = math.sqrt(ground_distance**2 + iss_alt**2)

        # Calculate elevation angle (simplified)
        if ground_distance > 0:
            elevation = math.degrees(math.atan2(iss_alt - (ground_distance**2 / (2 * earth_radius)), ground_distance))
        else:
            elevation = 90.0

        # Calculate azimuth
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        azimuth = math.degrees(math.atan2(y, x))
        azimuth = (azimuth + 360) % 360

        result['elevation'] = round(elevation, 1)
        result['azimuth'] = round(azimuth, 1)
        result['distance'] = round(slant_range, 1)
        result['visible'] = elevation > 0

    return result


@satellite_bp.route('/dashboard')
def satellite_dashboard():
    """Popout satellite tracking dashboard."""
    return render_template(
        'satellite_dashboard.html',
        shared_observer_location=SHARED_OBSERVER_LOCATION_ENABLED,
    )


@satellite_bp.route('/predict', methods=['POST'])
def predict_passes():
    """Calculate satellite passes using skyfield."""
    try:
        from skyfield.api import load, wgs84, EarthSatellite
        from skyfield.almanac import find_discrete
    except ImportError:
        return jsonify({
            'status': 'error',
            'message': 'skyfield library not installed. Run: pip install skyfield'
        }), 503

    data = request.json or {}

    # Validate inputs
    try:
        lat = validate_latitude(data.get('latitude', data.get('lat', 51.5074)))
        lon = validate_longitude(data.get('longitude', data.get('lon', -0.1278)))
        hours = validate_hours(data.get('hours', 24))
        min_el = validate_elevation(data.get('minEl', 10))
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

    norad_to_name = {
        25544: 'ISS',
        25338: 'NOAA-15',
        28654: 'NOAA-18',
        33591: 'NOAA-19',
        43013: 'NOAA-20',
        40069: 'METEOR-M2',
        57166: 'METEOR-M2-3'
    }

    sat_input = data.get('satellites', ['ISS', 'NOAA-15', 'NOAA-18', 'NOAA-19'])
    satellites = []
    for sat in sat_input:
        if isinstance(sat, int) and sat in norad_to_name:
            satellites.append(norad_to_name[sat])
        else:
            satellites.append(sat)

    passes = []
    colors = {
        'ISS': '#00ffff',
        'NOAA-15': '#00ff00',
        'NOAA-18': '#ff6600',
        'NOAA-19': '#ff3366',
        'NOAA-20': '#00ffaa',
        'METEOR-M2': '#9370DB',
        'METEOR-M2-3': '#ff00ff'
    }
    name_to_norad = {v: k for k, v in norad_to_name.items()}

    ts = load.timescale()
    observer = wgs84.latlon(lat, lon)

    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(hours=hours))

    for sat_name in satellites:
        if sat_name not in _tle_cache:
            continue

        tle_data = _tle_cache[sat_name]
        try:
            satellite = EarthSatellite(tle_data[1], tle_data[2], tle_data[0], ts)
        except Exception:
            continue

        def above_horizon(t):
            diff = satellite - observer
            topocentric = diff.at(t)
            alt, _, _ = topocentric.altaz()
            return alt.degrees > 0

        above_horizon.step_days = 1/720

        try:
            times, events = find_discrete(t0, t1, above_horizon)
        except Exception:
            continue

        i = 0
        while i < len(times):
            if i < len(events) and events[i]:
                rise_time = times[i]
                set_time = None
                for j in range(i + 1, len(times)):
                    if not events[j]:
                        set_time = times[j]
                        i = j
                        break

                if set_time is None:
                    i += 1
                    continue

                trajectory = []
                max_elevation = 0
                num_points = 30

                duration_seconds = (set_time.utc_datetime() - rise_time.utc_datetime()).total_seconds()

                for k in range(num_points):
                    frac = k / (num_points - 1)
                    t_point = ts.utc(rise_time.utc_datetime() + timedelta(seconds=duration_seconds * frac))

                    diff = satellite - observer
                    topocentric = diff.at(t_point)
                    alt, az, _ = topocentric.altaz()

                    el = alt.degrees
                    azimuth = az.degrees

                    if el > max_elevation:
                        max_elevation = el

                    trajectory.append({'el': float(max(0, el)), 'az': float(azimuth)})

                if max_elevation >= min_el:
                    duration_minutes = int(duration_seconds / 60)

                    ground_track = []
                    for k in range(60):
                        frac = k / 59
                        t_point = ts.utc(rise_time.utc_datetime() + timedelta(seconds=duration_seconds * frac))
                        geocentric = satellite.at(t_point)
                        subpoint = wgs84.subpoint(geocentric)
                        ground_track.append({
                            'lat': float(subpoint.latitude.degrees),
                            'lon': float(subpoint.longitude.degrees)
                        })

                    current_geo = satellite.at(ts.now())
                    current_subpoint = wgs84.subpoint(current_geo)

                    passes.append({
                        'satellite': sat_name,
                        'norad': name_to_norad.get(sat_name, 0),
                        'startTime': rise_time.utc_datetime().strftime('%Y-%m-%d %H:%M UTC'),
                        'startTimeISO': rise_time.utc_datetime().isoformat(),
                        'maxEl': float(round(max_elevation, 1)),
                        'duration': int(duration_minutes),
                        'trajectory': trajectory,
                        'groundTrack': ground_track,
                        'currentPos': {
                            'lat': float(current_subpoint.latitude.degrees),
                            'lon': float(current_subpoint.longitude.degrees)
                        },
                        'color': colors.get(sat_name, '#00ff00')
                    })

            i += 1

    passes.sort(key=lambda p: p['startTime'])

    return jsonify({
        'status': 'success',
        'passes': passes
    })


@satellite_bp.route('/position', methods=['POST'])
def get_satellite_position():
    """Get real-time positions of satellites."""
    try:
        from skyfield.api import load, wgs84, EarthSatellite
    except ImportError:
        return jsonify({'status': 'error', 'message': 'skyfield not installed'}), 503

    data = request.json or {}

    # Validate inputs
    try:
        lat = validate_latitude(data.get('latitude', data.get('lat', 51.5074)))
        lon = validate_longitude(data.get('longitude', data.get('lon', -0.1278)))
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

    sat_input = data.get('satellites', [])
    include_track = bool(data.get('includeTrack', True))

    norad_to_name = {
        25544: 'ISS',
        25338: 'NOAA-15',
        28654: 'NOAA-18',
        33591: 'NOAA-19',
        43013: 'NOAA-20',
        40069: 'METEOR-M2',
        57166: 'METEOR-M2-3'
    }

    satellites = []
    for sat in sat_input:
        if isinstance(sat, int) and sat in norad_to_name:
            satellites.append(norad_to_name[sat])
        else:
            satellites.append(sat)

    ts = load.timescale()
    observer = wgs84.latlon(lat, lon)
    now = ts.now()
    now_dt = now.utc_datetime()

    positions = []

    for sat_name in satellites:
        # Special handling for ISS - use real-time API for accurate position
        if sat_name == 'ISS':
            iss_data = _fetch_iss_realtime(lat, lon)
            if iss_data:
                # Add orbit track if requested (using TLE for track prediction)
                if include_track and 'ISS' in _tle_cache:
                    try:
                        tle_data = _tle_cache['ISS']
                        satellite = EarthSatellite(tle_data[1], tle_data[2], tle_data[0], ts)
                        orbit_track = []
                        for minutes_offset in range(-45, 46, 1):
                            t_point = ts.utc(now_dt + timedelta(minutes=minutes_offset))
                            try:
                                geo = satellite.at(t_point)
                                sp = wgs84.subpoint(geo)
                                orbit_track.append({
                                    'lat': float(sp.latitude.degrees),
                                    'lon': float(sp.longitude.degrees),
                                    'past': minutes_offset < 0
                                })
                            except Exception:
                                continue
                        iss_data['track'] = orbit_track
                    except Exception:
                        pass
                positions.append(iss_data)
            continue

        # Other satellites - use TLE data
        if sat_name not in _tle_cache:
            continue

        tle_data = _tle_cache[sat_name]
        try:
            satellite = EarthSatellite(tle_data[1], tle_data[2], tle_data[0], ts)

            geocentric = satellite.at(now)
            subpoint = wgs84.subpoint(geocentric)

            diff = satellite - observer
            topocentric = diff.at(now)
            alt, az, distance = topocentric.altaz()

            pos_data = {
                'satellite': sat_name,
                'lat': float(subpoint.latitude.degrees),
                'lon': float(subpoint.longitude.degrees),
                'altitude': float(geocentric.distance().km - 6371),
                'elevation': float(alt.degrees),
                'azimuth': float(az.degrees),
                'distance': float(distance.km),
                'visible': bool(alt.degrees > 0)
            }

            if include_track:
                orbit_track = []
                for minutes_offset in range(-45, 46, 1):
                    t_point = ts.utc(now_dt + timedelta(minutes=minutes_offset))
                    try:
                        geo = satellite.at(t_point)
                        sp = wgs84.subpoint(geo)
                        orbit_track.append({
                            'lat': float(sp.latitude.degrees),
                            'lon': float(sp.longitude.degrees),
                            'past': minutes_offset < 0
                        })
                    except Exception:
                        continue

                pos_data['track'] = orbit_track

            positions.append(pos_data)
        except Exception:
            continue

    return jsonify({
        'status': 'success',
        'positions': positions,
        'timestamp': datetime.utcnow().isoformat()
    })


def refresh_tle_data() -> list:
    """
    Refresh TLE data from CelesTrak.

    This can be called at startup or periodically to keep TLE data fresh.
    Returns list of satellite names that were updated.
    """
    global _tle_cache

    name_mappings = {
        'ISS (ZARYA)': 'ISS',
        'NOAA 15': 'NOAA-15',
        'NOAA 18': 'NOAA-18',
        'NOAA 19': 'NOAA-19',
        'NOAA 20 (JPSS-1)': 'NOAA-20',
        'NOAA 21 (JPSS-2)': 'NOAA-21',
        'METEOR-M 2': 'METEOR-M2',
        'METEOR-M2 3': 'METEOR-M2-3'
    }

    updated = []

    for group in ['stations', 'weather', 'noaa']:
        url = f'https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle'
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                content = response.read().decode('utf-8')
                lines = content.strip().split('\n')

                i = 0
                while i + 2 < len(lines):
                    name = lines[i].strip()
                    line1 = lines[i + 1].strip()
                    line2 = lines[i + 2].strip()

                    if not (line1.startswith('1 ') and line2.startswith('2 ')):
                        i += 1
                        continue

                    internal_name = name_mappings.get(name, name)

                    if internal_name in _tle_cache:
                        _tle_cache[internal_name] = (name, line1, line2)
                        if internal_name not in updated:
                            updated.append(internal_name)

                    i += 3
        except Exception as e:
            logger.warning(f"Error fetching TLE group {group}: {e}")
            continue

    return updated


@satellite_bp.route('/update-tle', methods=['POST'])
def update_tle():
    """Update TLE data from CelesTrak (API endpoint)."""
    try:
        updated = refresh_tle_data()
        return jsonify({
            'status': 'success',
            'updated': updated
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@satellite_bp.route('/celestrak/<category>')
def fetch_celestrak(category):
    """Fetch TLE data from CelesTrak for a category."""
    valid_categories = [
        'stations', 'weather', 'noaa', 'goes', 'resource', 'sarsat',
        'dmc', 'tdrss', 'argos', 'planet', 'spire', 'geo', 'intelsat',
        'ses', 'iridium', 'iridium-NEXT', 'starlink', 'oneweb',
        'amateur', 'cubesat', 'visual'
    ]

    if category not in valid_categories:
        return jsonify({'status': 'error', 'message': f'Invalid category. Valid: {valid_categories}'})

    try:
        url = f'https://celestrak.org/NORAD/elements/gp.php?GROUP={category}&FORMAT=tle'
        with urllib.request.urlopen(url, timeout=10) as response:
            content = response.read().decode('utf-8')

        satellites = []
        lines = content.strip().split('\n')

        i = 0
        while i + 2 < len(lines):
            name = lines[i].strip()
            line1 = lines[i + 1].strip()
            line2 = lines[i + 2].strip()

            if not (line1.startswith('1 ') and line2.startswith('2 ')):
                i += 1
                continue

            try:
                norad_id = int(line1[2:7])
                satellites.append({
                    'name': name,
                    'norad': norad_id,
                    'tle1': line1,
                    'tle2': line2
                })
            except (ValueError, IndexError):
                pass

            i += 3

        return jsonify({
            'status': 'success',
            'category': category,
            'satellites': satellites
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
