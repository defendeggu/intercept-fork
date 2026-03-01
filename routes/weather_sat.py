"""Weather Satellite decoder routes.

Provides endpoints for capturing and decoding weather satellite images
from NOAA (APT) and Meteor (LRPT) satellites using SatDump.
"""

from __future__ import annotations

import queue

from flask import Blueprint, jsonify, request, Response, send_file

from utils.logging import get_logger
from utils.sse import sse_stream
from utils.validation import validate_device_index, validate_gain, validate_latitude, validate_longitude, validate_elevation
from utils.weather_sat import (
    get_weather_sat_decoder,
    is_weather_sat_available,
    CaptureProgress,
    WEATHER_SATELLITES,
    DEFAULT_SAMPLE_RATE,
)

logger = get_logger('intercept.weather_sat')

weather_sat_bp = Blueprint('weather_sat', __name__, url_prefix='/weather-sat')

# Queue for SSE progress streaming
_weather_sat_queue: queue.Queue = queue.Queue(maxsize=100)


def _progress_callback(progress: CaptureProgress) -> None:
    """Callback to queue progress updates for SSE stream."""
    try:
        _weather_sat_queue.put_nowait(progress.to_dict())
    except queue.Full:
        try:
            _weather_sat_queue.get_nowait()
            _weather_sat_queue.put_nowait(progress.to_dict())
        except queue.Empty:
            pass


def _release_weather_sat_device(device_index: int) -> None:
    """Release an SDR device only if weather-sat currently owns it."""
    if device_index < 0:
        return

    try:
        import app as app_module
    except ImportError:
        return

    owner = None
    get_status = getattr(app_module, 'get_sdr_device_status', None)
    if callable(get_status):
        try:
            owner = get_status().get(device_index)
        except Exception:
            owner = None

    if owner and owner != 'weather_sat':
        logger.debug(
            'Skipping SDR release for device %s owned by %s',
            device_index,
            owner,
        )
        return

    app_module.release_sdr_device(device_index)


@weather_sat_bp.route('/status')
def get_status():
    """Get weather satellite decoder status.

    Returns:
        JSON with decoder availability and current status.
    """
    decoder = get_weather_sat_decoder()
    return jsonify(decoder.get_status())


@weather_sat_bp.route('/satellites')
def list_satellites():
    """Get list of supported weather satellites with frequencies.

    Returns:
        JSON with satellite definitions.
    """
    satellites = []
    for key, info in WEATHER_SATELLITES.items():
        satellites.append({
            'key': key,
            'name': info['name'],
            'frequency': info['frequency'],
            'mode': info['mode'],
            'description': info['description'],
            'active': info['active'],
        })

    return jsonify({
        'status': 'ok',
        'satellites': satellites,
    })


@weather_sat_bp.route('/start', methods=['POST'])
def start_capture():
    """Start weather satellite capture and decode.

    JSON body:
        {
            "satellite": "NOAA-18",    // Required: satellite key
            "device": 0,               // RTL-SDR device index (default: 0)
            "gain": 40.0,              // SDR gain in dB (default: 40)
            "bias_t": false            // Enable bias-T for LNA (default: false)
        }

    Returns:
        JSON with start status.
    """
    if not is_weather_sat_available():
        return jsonify({
            'status': 'error',
            'message': 'SatDump not installed. Build from source: https://github.com/SatDump/SatDump'
        }), 400

    decoder = get_weather_sat_decoder()

    if decoder.is_running:
        return jsonify({
            'status': 'already_running',
            'satellite': decoder.current_satellite,
            'frequency': decoder.current_frequency,
        })

    data = request.get_json(silent=True) or {}

    # Validate satellite
    satellite = data.get('satellite')
    if not satellite or satellite not in WEATHER_SATELLITES:
        return jsonify({
            'status': 'error',
            'message': f'Invalid satellite. Must be one of: {", ".join(WEATHER_SATELLITES.keys())}'
        }), 400

    # Validate device index and gain
    try:
        device_index = validate_device_index(data.get('device', 0))
        gain = validate_gain(data.get('gain', 40.0))
    except ValueError as e:
        logger.warning('Invalid parameter in start_capture: %s', e)
        return jsonify({
            'status': 'error',
            'message': 'Invalid parameter value'
        }), 400

    bias_t = bool(data.get('bias_t', False))

    # Claim SDR device
    try:
        import app as app_module
        error = app_module.claim_sdr_device(device_index, 'weather_sat')
        if error:
            return jsonify({
                'status': 'error',
                'error_type': 'DEVICE_BUSY',
                'message': error,
            }), 409
    except ImportError:
        pass

    # Clear queue
    while not _weather_sat_queue.empty():
        try:
            _weather_sat_queue.get_nowait()
        except queue.Empty:
            break

    # Set callback and on-complete handler for SDR release
    decoder.set_callback(_progress_callback)

    def _release_device():
        _release_weather_sat_device(device_index)

    decoder.set_on_complete(_release_device)

    success, error_msg = decoder.start(
        satellite=satellite,
        device_index=device_index,
        gain=gain,
        sample_rate=DEFAULT_SAMPLE_RATE,
        bias_t=bias_t,
    )

    if success:
        sat_info = WEATHER_SATELLITES[satellite]
        return jsonify({
            'status': 'started',
            'satellite': satellite,
            'frequency': sat_info['frequency'],
            'mode': sat_info['mode'],
            'device': device_index,
        })
    else:
        # Release device on failure
        _release_device()
        return jsonify({
            'status': 'error',
            'message': error_msg or 'Failed to start capture'
        }), 500


@weather_sat_bp.route('/test-decode', methods=['POST'])
def test_decode():
    """Start weather satellite decode from a pre-recorded file.

    No SDR hardware is required — decodes an IQ baseband or WAV file
    using SatDump offline mode.

    JSON body:
        {
            "satellite": "NOAA-18",       // Required: satellite key
            "input_file": "/path/to/file", // Required: server-side file path
            "sample_rate": 1000000         // Sample rate in Hz (default: 1000000)
        }

    Returns:
        JSON with start status.
    """
    if not is_weather_sat_available():
        return jsonify({
            'status': 'error',
            'message': 'SatDump not installed. Build from source: https://github.com/SatDump/SatDump'
        }), 400

    decoder = get_weather_sat_decoder()

    if decoder.is_running:
        return jsonify({
            'status': 'already_running',
            'satellite': decoder.current_satellite,
            'frequency': decoder.current_frequency,
        })

    data = request.get_json(silent=True) or {}

    # Validate satellite
    satellite = data.get('satellite')
    if not satellite or satellite not in WEATHER_SATELLITES:
        return jsonify({
            'status': 'error',
            'message': f'Invalid satellite. Must be one of: {", ".join(WEATHER_SATELLITES.keys())}'
        }), 400

    # Validate input file
    input_file = data.get('input_file')
    if not input_file:
        return jsonify({
            'status': 'error',
            'message': 'input_file is required'
        }), 400

    from pathlib import Path
    input_path = Path(input_file)

    # Security: restrict to data directory (anchored to app root, not CWD)
    allowed_base = Path(__file__).resolve().parent.parent / 'data'
    try:
        resolved = input_path.resolve()
        if not resolved.is_relative_to(allowed_base):
            return jsonify({
                'status': 'error',
                'message': 'input_file must be under the data/ directory'
            }), 403
    except (OSError, ValueError):
        return jsonify({
            'status': 'error',
            'message': 'Invalid file path'
        }), 400

    if not input_path.is_file():
        logger.warning("Test-decode file not found")
        return jsonify({
            'status': 'error',
            'message': 'File not found'
        }), 404

    # Validate sample rate
    sample_rate = data.get('sample_rate', 1000000)
    try:
        sample_rate = int(sample_rate)
        if sample_rate < 1000 or sample_rate > 20000000:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            'status': 'error',
            'message': 'Invalid sample_rate (1000-20000000)'
        }), 400

    # Clear queue
    while not _weather_sat_queue.empty():
        try:
            _weather_sat_queue.get_nowait()
        except queue.Empty:
            break

    # Set callback — no on_complete needed (no SDR to release)
    decoder.set_callback(_progress_callback)
    decoder.set_on_complete(None)

    success, error_msg = decoder.start_from_file(
        satellite=satellite,
        input_file=input_file,
        sample_rate=sample_rate,
    )

    if success:
        sat_info = WEATHER_SATELLITES[satellite]
        return jsonify({
            'status': 'started',
            'satellite': satellite,
            'frequency': sat_info['frequency'],
            'mode': sat_info['mode'],
            'source': 'file',
            'input_file': str(input_file),
        })
    else:
        return jsonify({
            'status': 'error',
            'message': error_msg or 'Failed to start file decode'
        }), 500


@weather_sat_bp.route('/stop', methods=['POST'])
def stop_capture():
    """Stop weather satellite capture.

    Returns:
        JSON confirmation.
    """
    decoder = get_weather_sat_decoder()
    device_index = decoder.device_index

    decoder.stop()

    _release_weather_sat_device(device_index)

    return jsonify({'status': 'stopped'})


@weather_sat_bp.route('/images')
def list_images():
    """Get list of decoded weather satellite images.

    Query parameters:
        limit: Maximum number of images (default: all)
        satellite: Filter by satellite key (optional)

    Returns:
        JSON with list of decoded images.
    """
    decoder = get_weather_sat_decoder()
    images = decoder.get_images()

    # Filter by satellite if specified
    satellite_filter = request.args.get('satellite')
    if satellite_filter:
        images = [img for img in images if img.satellite == satellite_filter]

    # Apply limit
    limit = request.args.get('limit', type=int)
    if limit and limit > 0:
        images = images[-limit:]

    return jsonify({
        'status': 'ok',
        'images': [img.to_dict() for img in images],
        'count': len(images),
    })


@weather_sat_bp.route('/images/<filename>')
def get_image(filename: str):
    """Serve a decoded weather satellite image file.

    Args:
        filename: Image filename

    Returns:
        Image file or 404.
    """
    decoder = get_weather_sat_decoder()

    # Security: only allow safe filenames
    if not filename.replace('_', '').replace('-', '').replace('.', '').isalnum():
        return jsonify({'status': 'error', 'message': 'Invalid filename'}), 400

    if not (filename.endswith('.png') or filename.endswith('.jpg') or filename.endswith('.jpeg')):
        return jsonify({'status': 'error', 'message': 'Only PNG/JPG files supported'}), 400

    image_path = decoder._output_dir / filename

    if not image_path.exists():
        return jsonify({'status': 'error', 'message': 'Image not found'}), 404

    mimetype = 'image/png' if filename.endswith('.png') else 'image/jpeg'
    return send_file(image_path, mimetype=mimetype)


@weather_sat_bp.route('/images/<filename>', methods=['DELETE'])
def delete_image(filename: str):
    """Delete a decoded image.

    Args:
        filename: Image filename

    Returns:
        JSON confirmation.
    """
    decoder = get_weather_sat_decoder()

    if not filename.replace('_', '').replace('-', '').replace('.', '').isalnum():
        return jsonify({'status': 'error', 'message': 'Invalid filename'}), 400

    if decoder.delete_image(filename):
        return jsonify({'status': 'deleted', 'filename': filename})
    else:
        return jsonify({'status': 'error', 'message': 'Image not found'}), 404


@weather_sat_bp.route('/images', methods=['DELETE'])
def delete_all_images():
    """Delete all decoded weather satellite images.

    Returns:
        JSON with count of deleted images.
    """
    decoder = get_weather_sat_decoder()
    count = decoder.delete_all_images()
    return jsonify({'status': 'ok', 'deleted': count})


@weather_sat_bp.route('/stream')
def stream_progress():
    """SSE stream of capture/decode progress.

    Returns:
        SSE stream (text/event-stream)
    """
    response = Response(sse_stream(_weather_sat_queue), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    return response


@weather_sat_bp.route('/passes')
def get_passes():
    """Get upcoming weather satellite passes for observer location.

    Query parameters:
        latitude: Observer latitude (required)
        longitude: Observer longitude (required)
        hours: Hours to predict ahead (default: 24, max: 72)
        min_elevation: Minimum elevation in degrees (default: 15)
        trajectory: Include az/el trajectory points (default: false)
        ground_track: Include lat/lon ground track points (default: false)

    Returns:
        JSON with upcoming passes for all weather satellites.
    """
    include_trajectory = request.args.get('trajectory', 'false').lower() in ('true', '1')
    include_ground_track = request.args.get('ground_track', 'false').lower() in ('true', '1')

    raw_lat = request.args.get('latitude')
    raw_lon = request.args.get('longitude')

    if raw_lat is None or raw_lon is None:
        return jsonify({
            'status': 'error',
            'message': 'latitude and longitude parameters required'
        }), 400

    try:
        lat = validate_latitude(raw_lat)
        lon = validate_longitude(raw_lon)
    except ValueError as e:
        logger.warning('Invalid coordinates in get_passes: %s', e)
        return jsonify({'status': 'error', 'message': 'Invalid coordinates'}), 400

    hours = max(1, min(request.args.get('hours', 24, type=int), 72))
    min_elevation = max(0, min(request.args.get('min_elevation', 15, type=float), 90))

    try:
        from utils.weather_sat_predict import predict_passes

        all_passes = predict_passes(
            lat=lat,
            lon=lon,
            hours=hours,
            min_elevation=min_elevation,
            include_trajectory=include_trajectory,
            include_ground_track=include_ground_track,
        )

        return jsonify({
            'status': 'ok',
            'passes': all_passes,
            'count': len(all_passes),
            'observer': {'latitude': lat, 'longitude': lon},
            'prediction_hours': hours,
            'min_elevation': min_elevation,
        })

    except ImportError:
        return jsonify({
            'status': 'error',
            'message': 'skyfield library not installed'
        }), 503

    except Exception as e:
        logger.error(f"Error predicting passes: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Pass prediction failed'
        }), 500


# ========================
# Auto-Scheduler Endpoints
# ========================


def _scheduler_event_callback(event: dict) -> None:
    """Forward scheduler events to the SSE queue."""
    try:
        _weather_sat_queue.put_nowait(event)
    except queue.Full:
        try:
            _weather_sat_queue.get_nowait()
            _weather_sat_queue.put_nowait(event)
        except queue.Empty:
            pass


@weather_sat_bp.route('/schedule/enable', methods=['POST'])
def enable_schedule():
    """Enable auto-scheduling of weather satellite captures.

    JSON body:
        {
            "latitude": 51.5,         // Required
            "longitude": -0.1,        // Required
            "min_elevation": 15,      // Minimum pass elevation (default: 15)
            "device": 0,              // RTL-SDR device index (default: 0)
            "gain": 40.0,             // SDR gain (default: 40)
            "bias_t": false           // Enable bias-T (default: false)
        }

    Returns:
        JSON with scheduler status.
    """
    from utils.weather_sat_scheduler import get_weather_sat_scheduler

    data = request.get_json(silent=True) or {}

    if data.get('latitude') is None or data.get('longitude') is None:
        return jsonify({
            'status': 'error',
            'message': 'latitude and longitude required'
        }), 400

    try:
        lat = validate_latitude(data.get('latitude'))
        lon = validate_longitude(data.get('longitude'))
        min_elev = validate_elevation(data.get('min_elevation', 15))
        device = validate_device_index(data.get('device', 0))
        gain_val = validate_gain(data.get('gain', 40.0))
    except ValueError as e:
        logger.warning('Invalid parameter in enable_schedule: %s', e)
        return jsonify({
            'status': 'error',
            'message': 'Invalid parameter value'
        }), 400

    scheduler = get_weather_sat_scheduler()
    scheduler.set_callbacks(_progress_callback, _scheduler_event_callback)

    try:
        result = scheduler.enable(
            lat=lat,
            lon=lon,
            min_elevation=min_elev,
            device=device,
            gain=gain_val,
            bias_t=bool(data.get('bias_t', False)),
        )
    except Exception as e:
        logger.exception("Failed to enable weather sat scheduler")
        return jsonify({
            'status': 'error',
            'message': 'Failed to enable scheduler'
        }), 500

    return jsonify({'status': 'ok', **result})


@weather_sat_bp.route('/schedule/disable', methods=['POST'])
def disable_schedule():
    """Disable auto-scheduling."""
    from utils.weather_sat_scheduler import get_weather_sat_scheduler

    scheduler = get_weather_sat_scheduler()
    result = scheduler.disable()
    return jsonify(result)


@weather_sat_bp.route('/schedule/status')
def schedule_status():
    """Get current scheduler state."""
    from utils.weather_sat_scheduler import get_weather_sat_scheduler

    scheduler = get_weather_sat_scheduler()
    return jsonify(scheduler.get_status())


@weather_sat_bp.route('/schedule/passes')
def schedule_passes():
    """List scheduled passes."""
    from utils.weather_sat_scheduler import get_weather_sat_scheduler

    scheduler = get_weather_sat_scheduler()
    passes = scheduler.get_passes()
    return jsonify({
        'status': 'ok',
        'passes': passes,
        'count': len(passes),
    })


@weather_sat_bp.route('/schedule/skip/<pass_id>', methods=['POST'])
def skip_pass(pass_id: str):
    """Skip a scheduled pass."""
    from utils.weather_sat_scheduler import get_weather_sat_scheduler

    if not pass_id.replace('_', '').replace('-', '').isalnum():
        return jsonify({'status': 'error', 'message': 'Invalid pass ID'}), 400

    scheduler = get_weather_sat_scheduler()
    if scheduler.skip_pass(pass_id):
        return jsonify({'status': 'skipped', 'pass_id': pass_id})
    else:
        return jsonify({'status': 'error', 'message': 'Pass not found or already processed'}), 404
