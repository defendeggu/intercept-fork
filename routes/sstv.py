"""ISS SSTV (Slow-Scan Television) decoder routes.

Provides endpoints for decoding SSTV images from the International Space Station.
ISS SSTV events occur during special commemorations and typically transmit on 145.800 MHz FM.
"""

from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Generator

from flask import Blueprint, jsonify, request, Response, send_file

from utils.logging import get_logger
from utils.sse import format_sse
from utils.sstv import (
    get_sstv_decoder,
    is_sstv_available,
    ISS_SSTV_FREQ,
    DecodeProgress,
    DopplerInfo,
)

logger = get_logger('intercept.sstv')

sstv_bp = Blueprint('sstv', __name__, url_prefix='/sstv')

# Queue for SSE progress streaming
_sstv_queue: queue.Queue = queue.Queue(maxsize=100)


def _progress_callback(progress: DecodeProgress) -> None:
    """Callback to queue progress updates for SSE stream."""
    try:
        _sstv_queue.put_nowait(progress.to_dict())
    except queue.Full:
        try:
            _sstv_queue.get_nowait()
            _sstv_queue.put_nowait(progress.to_dict())
        except queue.Empty:
            pass


@sstv_bp.route('/status')
def get_status():
    """
    Get SSTV decoder status.

    Returns:
        JSON with decoder availability and current status.
    """
    available = is_sstv_available()
    decoder = get_sstv_decoder()

    result = {
        'available': available,
        'decoder': decoder.decoder_available,
        'running': decoder.is_running,
        'iss_frequency': ISS_SSTV_FREQ,
        'image_count': len(decoder.get_images()),
        'doppler_enabled': decoder.doppler_enabled,
    }

    # Include Doppler info if available
    doppler_info = decoder.last_doppler_info
    if doppler_info:
        result['doppler'] = doppler_info.to_dict()

    return jsonify(result)


@sstv_bp.route('/start', methods=['POST'])
def start_decoder():
    """
    Start SSTV decoder.

    JSON body (optional):
        {
            "frequency": 145.800,  // Frequency in MHz (default: ISS 145.800)
            "device": 0,           // RTL-SDR device index
            "latitude": 40.7128,   // Observer latitude for Doppler correction
            "longitude": -74.0060  // Observer longitude for Doppler correction
        }

    If latitude and longitude are provided, real-time Doppler shift compensation
    will be enabled, which improves reception by tracking the ISS frequency shift
    as it passes overhead (up to ±3.5 kHz at 145.800 MHz).

    Returns:
        JSON with start status.
    """
    if not is_sstv_available():
        return jsonify({
            'status': 'error',
            'message': 'SSTV decoder not available. Install slowrx: apt install slowrx'
        }), 400

    decoder = get_sstv_decoder()

    if decoder.is_running:
        return jsonify({
            'status': 'already_running',
            'frequency': ISS_SSTV_FREQ,
            'doppler_enabled': decoder.doppler_enabled
        })

    # Clear queue
    while not _sstv_queue.empty():
        try:
            _sstv_queue.get_nowait()
        except queue.Empty:
            break

    # Get parameters
    data = request.get_json(silent=True) or {}
    frequency = data.get('frequency', ISS_SSTV_FREQ)
    device_index = data.get('device', 0)
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    # Validate frequency
    try:
        frequency = float(frequency)
        if not (100 <= frequency <= 500):  # VHF range
            return jsonify({
                'status': 'error',
                'message': 'Frequency must be between 100-500 MHz'
            }), 400
    except (TypeError, ValueError):
        return jsonify({
            'status': 'error',
            'message': 'Invalid frequency'
        }), 400

    # Validate location if provided
    if latitude is not None and longitude is not None:
        try:
            latitude = float(latitude)
            longitude = float(longitude)
            if not (-90 <= latitude <= 90):
                return jsonify({
                    'status': 'error',
                    'message': 'Latitude must be between -90 and 90'
                }), 400
            if not (-180 <= longitude <= 180):
                return jsonify({
                    'status': 'error',
                    'message': 'Longitude must be between -180 and 180'
                }), 400
        except (TypeError, ValueError):
            return jsonify({
                'status': 'error',
                'message': 'Invalid latitude or longitude'
            }), 400
    else:
        latitude = None
        longitude = None

    # Set callback and start
    decoder.set_callback(_progress_callback)
    success = decoder.start(
        frequency=frequency,
        device_index=device_index,
        latitude=latitude,
        longitude=longitude
    )

    if success:
        result = {
            'status': 'started',
            'frequency': frequency,
            'device': device_index,
            'doppler_enabled': decoder.doppler_enabled
        }

        # Include initial Doppler info if available
        if decoder.doppler_enabled and decoder.last_doppler_info:
            result['doppler'] = decoder.last_doppler_info.to_dict()

        return jsonify(result)
    else:
        return jsonify({
            'status': 'error',
            'message': 'Failed to start decoder'
        }), 500


@sstv_bp.route('/stop', methods=['POST'])
def stop_decoder():
    """
    Stop SSTV decoder.

    Returns:
        JSON confirmation.
    """
    decoder = get_sstv_decoder()
    decoder.stop()
    return jsonify({'status': 'stopped'})


@sstv_bp.route('/doppler')
def get_doppler():
    """
    Get current Doppler shift information.

    Returns real-time Doppler shift data if tracking is enabled.

    Returns:
        JSON with Doppler shift information.
    """
    decoder = get_sstv_decoder()

    if not decoder.doppler_enabled:
        return jsonify({
            'status': 'disabled',
            'message': 'Doppler tracking not enabled. Provide latitude/longitude when starting decoder.'
        })

    doppler_info = decoder.last_doppler_info
    if not doppler_info:
        return jsonify({
            'status': 'unavailable',
            'message': 'Doppler data not yet available'
        })

    return jsonify({
        'status': 'ok',
        'doppler': doppler_info.to_dict(),
        'nominal_frequency_mhz': ISS_SSTV_FREQ,
        'corrected_frequency_mhz': doppler_info.frequency_hz / 1_000_000
    })


@sstv_bp.route('/images')
def list_images():
    """
    Get list of decoded SSTV images.

    Query parameters:
        limit: Maximum number of images to return (default: all)

    Returns:
        JSON with list of decoded images.
    """
    decoder = get_sstv_decoder()
    images = decoder.get_images()

    limit = request.args.get('limit', type=int)
    if limit and limit > 0:
        images = images[-limit:]

    return jsonify({
        'status': 'ok',
        'images': [img.to_dict() for img in images],
        'count': len(images)
    })


@sstv_bp.route('/images/<filename>')
def get_image(filename: str):
    """
    Get a decoded SSTV image file.

    Args:
        filename: Image filename

    Returns:
        Image file or 404.
    """
    decoder = get_sstv_decoder()

    # Security: only allow alphanumeric filenames with .png extension
    if not filename.replace('_', '').replace('-', '').replace('.', '').isalnum():
        return jsonify({'status': 'error', 'message': 'Invalid filename'}), 400

    if not filename.endswith('.png'):
        return jsonify({'status': 'error', 'message': 'Only PNG files supported'}), 400

    # Find image in decoder's output directory
    image_path = decoder._output_dir / filename

    if not image_path.exists():
        return jsonify({'status': 'error', 'message': 'Image not found'}), 404

    return send_file(image_path, mimetype='image/png')


@sstv_bp.route('/stream')
def stream_progress():
    """
    SSE stream of SSTV decode progress.

    Provides real-time Server-Sent Events stream of decode progress.

    Event format:
        data: {"type": "sstv_progress", "status": "decoding", "mode": "PD120", ...}

    Returns:
        SSE stream (text/event-stream)
    """
    def generate() -> Generator[str, None, None]:
        last_keepalive = time.time()
        keepalive_interval = 30.0

        while True:
            try:
                progress = _sstv_queue.get(timeout=1)
                last_keepalive = time.time()
                yield format_sse(progress)
            except queue.Empty:
                now = time.time()
                if now - last_keepalive >= keepalive_interval:
                    yield format_sse({'type': 'keepalive'})
                    last_keepalive = now

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    return response


@sstv_bp.route('/iss-schedule')
def iss_schedule():
    """
    Get ISS pass schedule for SSTV reception.

    Calculates ISS passes directly using skyfield.

    Query parameters:
        latitude: Observer latitude (required)
        longitude: Observer longitude (required)
        hours: Hours to look ahead (default: 48)

    Returns:
        JSON with ISS pass schedule.
    """
    lat = request.args.get('latitude', type=float)
    lon = request.args.get('longitude', type=float)
    hours = request.args.get('hours', 48, type=int)

    if lat is None or lon is None:
        return jsonify({
            'status': 'error',
            'message': 'latitude and longitude parameters required'
        }), 400

    try:
        from skyfield.api import load, wgs84, EarthSatellite
        from skyfield.almanac import find_discrete
        from datetime import timedelta
        from data.satellites import TLE_SATELLITES

        # Get ISS TLE
        iss_tle = TLE_SATELLITES.get('ISS')
        if not iss_tle:
            return jsonify({
                'status': 'error',
                'message': 'ISS TLE data not available'
            }), 500

        ts = load.timescale()
        satellite = EarthSatellite(iss_tle[1], iss_tle[2], iss_tle[0], ts)
        observer = wgs84.latlon(lat, lon)

        t0 = ts.now()
        t1 = ts.utc(t0.utc_datetime() + timedelta(hours=hours))

        def above_horizon(t):
            diff = satellite - observer
            topocentric = diff.at(t)
            alt, _, _ = topocentric.altaz()
            return alt.degrees > 0

        above_horizon.step_days = 1/720

        times, events = find_discrete(t0, t1, above_horizon)

        passes = []
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

                # Calculate max elevation
                max_el = 0
                duration_seconds = (set_time.utc_datetime() - rise_time.utc_datetime()).total_seconds()
                duration_minutes = int(duration_seconds / 60)

                for k in range(30):
                    frac = k / 29
                    t_point = ts.utc(rise_time.utc_datetime() + timedelta(seconds=duration_seconds * frac))
                    diff = satellite - observer
                    topocentric = diff.at(t_point)
                    alt, _, _ = topocentric.altaz()
                    if alt.degrees > max_el:
                        max_el = alt.degrees

                if max_el >= 10:  # Min elevation filter
                    passes.append({
                        'satellite': 'ISS',
                        'startTime': rise_time.utc_datetime().strftime('%Y-%m-%d %H:%M UTC'),
                        'startTimeISO': rise_time.utc_datetime().isoformat(),
                        'maxEl': round(max_el, 1),
                        'duration': duration_minutes,
                        'color': '#00ffff'
                    })

            i += 1

        return jsonify({
            'status': 'ok',
            'passes': passes,
            'count': len(passes),
            'sstv_frequency': ISS_SSTV_FREQ,
            'note': 'ISS SSTV events are not continuous. Check ARISS.org for scheduled events.'
        })

    except ImportError:
        return jsonify({
            'status': 'error',
            'message': 'skyfield library not installed'
        }), 503

    except Exception as e:
        logger.error(f"Error getting ISS schedule: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@sstv_bp.route('/iss-position')
def iss_position():
    """
    Get current ISS position from real-time API.

    Uses the Open Notify API for accurate real-time position,
    with fallback to "Where The ISS At" API.

    Query parameters:
        latitude: Observer latitude (optional, for elevation calc)
        longitude: Observer longitude (optional, for elevation calc)

    Returns:
        JSON with ISS current position.
    """
    import requests
    from datetime import datetime

    observer_lat = request.args.get('latitude', type=float)
    observer_lon = request.args.get('longitude', type=float)

    # Try primary API: Open Notify
    try:
        response = requests.get('http://api.open-notify.org/iss-now.json', timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('message') == 'success':
                iss_lat = float(data['iss_position']['latitude'])
                iss_lon = float(data['iss_position']['longitude'])

                result = {
                    'status': 'ok',
                    'lat': iss_lat,
                    'lon': iss_lon,
                    'altitude': 420,  # Approximate ISS altitude in km
                    'timestamp': datetime.utcnow().isoformat(),
                    'source': 'open-notify'
                }

                # Calculate observer-relative data if location provided
                if observer_lat is not None and observer_lon is not None:
                    result.update(_calculate_observer_data(iss_lat, iss_lon, observer_lat, observer_lon))

                return jsonify(result)
    except Exception as e:
        logger.warning(f"Open Notify API failed: {e}")

    # Try fallback API: Where The ISS At
    try:
        response = requests.get('https://api.wheretheiss.at/v1/satellites/25544', timeout=5)
        if response.status_code == 200:
            data = response.json()
            iss_lat = float(data['latitude'])
            iss_lon = float(data['longitude'])

            result = {
                'status': 'ok',
                'lat': iss_lat,
                'lon': iss_lon,
                'altitude': float(data.get('altitude', 420)),
                'timestamp': datetime.utcnow().isoformat(),
                'source': 'wheretheiss'
            }

            # Calculate observer-relative data if location provided
            if observer_lat is not None and observer_lon is not None:
                result.update(_calculate_observer_data(iss_lat, iss_lon, observer_lat, observer_lon))

            return jsonify(result)
    except Exception as e:
        logger.warning(f"Where The ISS At API failed: {e}")

    # Both APIs failed
    return jsonify({
        'status': 'error',
        'message': 'Unable to fetch ISS position from real-time APIs'
    }), 503


def _calculate_observer_data(iss_lat: float, iss_lon: float, obs_lat: float, obs_lon: float) -> dict:
    """Calculate elevation, azimuth, and distance from observer to ISS."""
    import math

    # ISS altitude in km
    iss_alt_km = 420

    # Earth radius in km
    earth_radius = 6371

    # Convert to radians
    lat1 = math.radians(obs_lat)
    lat2 = math.radians(iss_lat)
    lon1 = math.radians(obs_lon)
    lon2 = math.radians(iss_lon)

    # Haversine for ground distance
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    ground_distance = earth_radius * c

    # Calculate elevation angle (simplified)
    # Using spherical geometry approximation
    iss_height = iss_alt_km
    slant_range = math.sqrt(ground_distance**2 + iss_height**2)

    if ground_distance > 0:
        elevation = math.degrees(math.atan2(iss_height - (ground_distance**2 / (2 * earth_radius)), ground_distance))
    else:
        elevation = 90.0

    # Calculate azimuth
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    azimuth = math.degrees(math.atan2(y, x))
    azimuth = (azimuth + 360) % 360

    return {
        'elevation': round(elevation, 1),
        'azimuth': round(azimuth, 1),
        'distance': round(slant_range, 1)
    }


@sstv_bp.route('/decode-file', methods=['POST'])
def decode_file():
    """
    Decode SSTV from an uploaded audio file.

    Expects multipart/form-data with 'audio' file field.

    Returns:
        JSON with decoded images.
    """
    if 'audio' not in request.files:
        return jsonify({
            'status': 'error',
            'message': 'No audio file provided'
        }), 400

    audio_file = request.files['audio']

    if not audio_file.filename:
        return jsonify({
            'status': 'error',
            'message': 'No file selected'
        }), 400

    # Save to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        decoder = get_sstv_decoder()
        images = decoder.decode_file(tmp_path)

        return jsonify({
            'status': 'ok',
            'images': [img.to_dict() for img in images],
            'count': len(images)
        })

    except Exception as e:
        logger.error(f"Error decoding file: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass
