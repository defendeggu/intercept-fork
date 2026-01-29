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

    return jsonify({
        'available': available,
        'decoder': decoder.decoder_available,
        'running': decoder.is_running,
        'iss_frequency': ISS_SSTV_FREQ,
        'image_count': len(decoder.get_images()),
    })


@sstv_bp.route('/start', methods=['POST'])
def start_decoder():
    """
    Start SSTV decoder.

    JSON body (optional):
        {
            "frequency": 145.800,  // Frequency in MHz (default: ISS 145.800)
            "device": 0            // RTL-SDR device index
        }

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
            'frequency': ISS_SSTV_FREQ
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

    # Set callback and start
    decoder.set_callback(_progress_callback)
    success = decoder.start(frequency=frequency, device_index=device_index)

    if success:
        return jsonify({
            'status': 'started',
            'frequency': frequency,
            'device': device_index
        })
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
