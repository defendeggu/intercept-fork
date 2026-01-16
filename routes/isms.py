"""ISMS Listening Station routes for spectrum monitoring and tower mapping."""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Generator

from flask import Blueprint, Response, jsonify, request

from utils.logging import get_logger
from utils.sse import format_sse
from utils.constants import SSE_QUEUE_TIMEOUT, SSE_KEEPALIVE_INTERVAL
from utils.process import safe_terminate, register_process
from utils.gps import get_current_position
from utils.database import (
    create_isms_baseline,
    get_isms_baseline,
    get_all_isms_baselines,
    get_active_isms_baseline,
    set_active_isms_baseline,
    delete_isms_baseline,
    update_isms_baseline,
    create_isms_scan,
    update_isms_scan,
    get_isms_scan,
    get_recent_isms_scans,
    add_isms_finding,
    get_isms_findings,
    get_isms_findings_summary,
    acknowledge_isms_finding,
)
from utils.isms.spectrum import (
    run_rtl_power_scan,
    compute_band_metrics,
    detect_bursts,
    get_rtl_power_path,
    SpectrumBin,
    BandMetrics,
)
from utils.isms.towers import (
    query_nearby_towers,
    format_tower_info,
    build_ofcom_coverage_url,
    build_ofcom_emf_url,
    get_opencellid_token,
)
from utils.isms.rules import RulesEngine, create_default_engine
from utils.isms.baseline import (
    BaselineRecorder,
    compare_spectrum_baseline,
    compare_tower_baseline,
    save_baseline_to_db,
)
from utils.isms.gsm import (
    GsmCell,
    run_grgsm_scan,
    run_gsm_scan_blocking,
    get_grgsm_scanner_path,
    format_gsm_cell,
    deduplicate_cells,
    identify_gsm_anomalies,
)
from data.isms_presets import (
    ISMS_SCAN_PRESETS,
    get_preset,
    get_all_presets,
    identify_band,
)

logger = get_logger('intercept.isms')

isms_bp = Blueprint('isms', __name__, url_prefix='/isms')

# ============================================
# GLOBAL STATE
# ============================================

# Scanner state
isms_thread: threading.Thread | None = None
isms_running = False
isms_lock = threading.Lock()
isms_process: subprocess.Popen | None = None
isms_current_scan_id: int | None = None

# Scanner configuration
isms_config = {
    'preset': 'ism_433',
    'freq_start': 433.0,
    'freq_end': 434.8,
    'bin_size': 10000,
    'integration': 0.5,
    'device': 0,
    'gain': 40,
    'ppm': 0,
    'threshold': 50,  # Activity threshold (0-100)
    'lat': None,
    'lon': None,
    'baseline_id': None,
}

# SSE queue for real-time events
isms_queue: queue.Queue = queue.Queue(maxsize=100)

# Rules engine
rules_engine: RulesEngine = create_default_engine()

# Baseline recorder
baseline_recorder: BaselineRecorder = BaselineRecorder()

# Recent band metrics for display
recent_metrics: dict[str, BandMetrics] = {}
metrics_lock = threading.Lock()

# Findings count for current scan
current_findings_count = 0

# GSM scanner state
gsm_thread: threading.Thread | None = None
gsm_running = False
gsm_lock = threading.Lock()
gsm_detected_cells: list[GsmCell] = []
gsm_baseline_cells: list[GsmCell] = []


# ============================================
# HELPER FUNCTIONS
# ============================================

def emit_event(event_type: str, data: dict) -> None:
    """Emit an event to SSE queue."""
    try:
        isms_queue.put_nowait({
            'type': event_type,
            **data
        })
    except queue.Full:
        pass


def emit_finding(severity: str, text: str, **details) -> None:
    """Emit a finding event and store in database."""
    global current_findings_count

    emit_event('finding', {
        'severity': severity,
        'text': text,
        'details': details,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    })

    # Store in database if we have an active scan
    if isms_current_scan_id:
        add_isms_finding(
            scan_id=isms_current_scan_id,
            finding_type=details.get('finding_type', 'general'),
            severity=severity,
            description=text,
            band=details.get('band'),
            frequency=details.get('frequency'),
            details=details,
        )
        current_findings_count += 1


def emit_meter(band: str, level: float, noise_floor: float) -> None:
    """Emit a band meter update."""
    emit_event('meter', {
        'band': band,
        'level': min(100, max(0, level)),
        'noise_floor': noise_floor,
    })


def emit_peak(freq_mhz: float, power_db: float, band: str) -> None:
    """Emit a spectrum peak event."""
    emit_event('spectrum_peak', {
        'freq_mhz': round(freq_mhz, 3),
        'power_db': round(power_db, 1),
        'band': band,
    })


def emit_status(state: str, **data) -> None:
    """Emit a status update."""
    emit_event('status', {
        'state': state,
        **data
    })


# ============================================
# SCANNER LOOP
# ============================================

def isms_scan_loop() -> None:
    """Main ISMS scanning loop."""
    global isms_running, isms_process, current_findings_count

    logger.info("ISMS scan thread started")
    emit_status('starting')

    # Get preset configuration
    preset_name = isms_config.get('preset', 'ism_433')
    preset = get_preset(preset_name)

    if preset:
        freq_start = preset['freq_start']
        freq_end = preset['freq_end']
        bin_size = preset.get('bin_size', 10000)
        integration = preset.get('integration', 1.0)
        band_name = preset['name']
    else:
        freq_start = isms_config['freq_start']
        freq_end = isms_config['freq_end']
        bin_size = isms_config['bin_size']
        integration = isms_config['integration']
        band_name = f'{freq_start}-{freq_end} MHz'

    device = isms_config['device']
    gain = isms_config['gain']
    ppm = isms_config['ppm']
    threshold = isms_config['threshold']

    # Get active baseline for comparison
    active_baseline = None
    baseline_spectrum = None
    if isms_config.get('baseline_id'):
        active_baseline = get_isms_baseline(isms_config['baseline_id'])
        if active_baseline:
            baseline_spectrum = active_baseline.get('spectrum_profile', {}).get(band_name)

    emit_status('scanning', band=band_name, preset=preset_name)

    current_bins: list[SpectrumBin] = []
    sweep_count = 0

    try:
        # Run continuous spectrum scanning
        for spectrum_bin in run_rtl_power_scan(
            freq_start_mhz=freq_start,
            freq_end_mhz=freq_end,
            bin_size_hz=bin_size,
            integration_time=integration,
            device_index=device,
            gain=gain,
            ppm=ppm,
            single_shot=False,
        ):
            if not isms_running:
                break

            current_bins.append(spectrum_bin)

            # Process a sweep's worth of data
            if spectrum_bin.freq_hz >= (freq_end * 1_000_000 - bin_size):
                sweep_count += 1

                # Compute band metrics
                metrics = compute_band_metrics(current_bins, band_name)

                # Store in recent metrics
                with metrics_lock:
                    recent_metrics[band_name] = metrics

                # Add to baseline recorder if recording
                if baseline_recorder.is_recording:
                    baseline_recorder.add_spectrum_sample(band_name, metrics)

                # Emit meter update
                emit_meter(band_name, metrics.activity_score, metrics.noise_floor_db)

                # Emit peak if significant
                if metrics.peak_power_db > metrics.noise_floor_db + 6:
                    emit_peak(metrics.peak_frequency_mhz, metrics.peak_power_db, band_name)

                # Detect bursts
                bursts = detect_bursts(current_bins)
                if bursts:
                    emit_event('bursts_detected', {
                        'band': band_name,
                        'count': len(bursts),
                    })

                # Run rules engine
                findings = rules_engine.evaluate_spectrum(
                    band_name=band_name,
                    noise_floor=metrics.noise_floor_db,
                    peak_freq=metrics.peak_frequency_mhz,
                    peak_power=metrics.peak_power_db,
                    activity_score=metrics.activity_score,
                    baseline_noise=baseline_spectrum.get('noise_floor_db') if baseline_spectrum else None,
                    baseline_activity=baseline_spectrum.get('activity_score') if baseline_spectrum else None,
                    baseline_peaks=baseline_spectrum.get('peak_frequencies') if baseline_spectrum else None,
                    burst_count=len(bursts),
                )

                for finding in findings:
                    emit_finding(
                        finding.severity,
                        finding.description,
                        finding_type=finding.finding_type,
                        band=finding.band,
                        frequency=finding.frequency,
                    )

                # Emit progress
                if sweep_count % 5 == 0:
                    emit_status('scanning', band=band_name, sweeps=sweep_count)

                # Clear for next sweep
                current_bins.clear()

    except Exception as e:
        logger.error(f"ISMS scan error: {e}")
        emit_status('error', message=str(e))

    finally:
        isms_running = False
        emit_status('stopped', sweeps=sweep_count)

        # Update scan record
        if isms_current_scan_id:
            update_isms_scan(
                isms_current_scan_id,
                status='completed',
                findings_count=current_findings_count,
                completed=True,
            )

        logger.info(f"ISMS scan stopped after {sweep_count} sweeps")


# ============================================
# ROUTES: SCAN CONTROL
# ============================================

@isms_bp.route('/start_scan', methods=['POST'])
def start_scan():
    """Start ISMS spectrum scanning."""
    global isms_thread, isms_running, isms_current_scan_id, current_findings_count

    with isms_lock:
        if isms_running:
            return jsonify({
                'status': 'error',
                'message': 'Scan already running'
            }), 409

        # Get configuration from request
        data = request.get_json() or {}

        isms_config['preset'] = data.get('preset', isms_config['preset'])
        isms_config['device'] = data.get('device', isms_config['device'])
        isms_config['gain'] = data.get('gain', isms_config['gain'])
        isms_config['threshold'] = data.get('threshold', isms_config['threshold'])
        isms_config['baseline_id'] = data.get('baseline_id')

        # Custom frequency range
        if data.get('freq_start'):
            isms_config['freq_start'] = float(data['freq_start'])
        if data.get('freq_end'):
            isms_config['freq_end'] = float(data['freq_end'])

        # Location
        if data.get('lat') and data.get('lon'):
            isms_config['lat'] = float(data['lat'])
            isms_config['lon'] = float(data['lon'])

        # Check for rtl_power
        if not get_rtl_power_path():
            return jsonify({
                'status': 'error',
                'message': 'rtl_power not found. Install rtl-sdr tools.'
            }), 500

        # Clear queue
        while not isms_queue.empty():
            try:
                isms_queue.get_nowait()
            except queue.Empty:
                break

        # Create scan record
        gps_coords = None
        if isms_config.get('lat') and isms_config.get('lon'):
            gps_coords = {'lat': isms_config['lat'], 'lon': isms_config['lon']}

        isms_current_scan_id = create_isms_scan(
            scan_preset=isms_config['preset'],
            baseline_id=isms_config.get('baseline_id'),
            gps_coords=gps_coords,
        )
        current_findings_count = 0

        # Start scanning thread
        isms_running = True
        isms_thread = threading.Thread(target=isms_scan_loop, daemon=True)
        isms_thread.start()

        return jsonify({
            'status': 'started',
            'scan_id': isms_current_scan_id,
            'config': {
                'preset': isms_config['preset'],
                'device': isms_config['device'],
            }
        })


@isms_bp.route('/stop_scan', methods=['POST'])
def stop_scan():
    """Stop ISMS spectrum scanning."""
    global isms_running, isms_process

    with isms_lock:
        if not isms_running:
            return jsonify({
                'status': 'error',
                'message': 'No scan running'
            }), 400

        isms_running = False

        # Terminate any subprocess
        if isms_process:
            safe_terminate(isms_process)
            isms_process = None

    return jsonify({'status': 'stopped'})


@isms_bp.route('/status', methods=['GET'])
def get_status():
    """Get current scanner status."""
    with isms_lock:
        status = {
            'running': isms_running,
            'config': {
                'preset': isms_config['preset'],
                'device': isms_config['device'],
                'baseline_id': isms_config.get('baseline_id'),
            },
            'current_scan_id': isms_current_scan_id,
            'findings_count': current_findings_count,
        }

    # Add recent metrics
    with metrics_lock:
        status['metrics'] = {
            band: {
                'activity_score': m.activity_score,
                'noise_floor': m.noise_floor_db,
                'peak_freq': m.peak_frequency_mhz,
                'peak_power': m.peak_power_db,
            }
            for band, m in recent_metrics.items()
        }

    return jsonify(status)


# ============================================
# ROUTES: SSE STREAM
# ============================================

@isms_bp.route('/stream', methods=['GET'])
def stream():
    """SSE stream for real-time ISMS events."""
    def generate() -> Generator[str, None, None]:
        last_keepalive = time.time()

        while True:
            try:
                msg = isms_queue.get(timeout=SSE_QUEUE_TIMEOUT)
                last_keepalive = time.time()
                yield format_sse(msg)
            except queue.Empty:
                now = time.time()
                if now - last_keepalive >= SSE_KEEPALIVE_INTERVAL:
                    yield format_sse({'type': 'keepalive'})
                    last_keepalive = now

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    return response


# ============================================
# ROUTES: PRESETS
# ============================================

@isms_bp.route('/presets', methods=['GET'])
def list_presets():
    """List available scan presets."""
    return jsonify({
        'presets': get_all_presets()
    })


# ============================================
# ROUTES: TOWERS
# ============================================

@isms_bp.route('/towers', methods=['GET'])
def get_towers():
    """Query nearby cell towers from OpenCelliD."""
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius = request.args.get('radius', default=5.0, type=float)
    radio = request.args.get('radio')  # GSM, UMTS, LTE, NR

    if lat is None or lon is None:
        # Try to get from GPS
        pos = get_current_position()
        if pos:
            lat = pos.latitude
            lon = pos.longitude
        else:
            return jsonify({
                'status': 'error',
                'message': 'Location required (lat/lon parameters or GPS)'
            }), 400

    # Check for token
    token = get_opencellid_token()
    if not token:
        return jsonify({
            'status': 'error',
            'message': 'OpenCelliD token not configured. Set OPENCELLID_TOKEN environment variable.',
            'config_required': True,
        }), 400

    # Query towers
    towers = query_nearby_towers(
        lat=lat,
        lon=lon,
        radius_km=radius,
        radio=radio,
    )

    # Format for response
    formatted_towers = [format_tower_info(t) for t in towers]

    # Add to baseline recorder if recording
    if baseline_recorder.is_recording:
        for tower in towers:
            baseline_recorder.add_tower_sample(tower)

    return jsonify({
        'status': 'ok',
        'query': {
            'lat': lat,
            'lon': lon,
            'radius_km': radius,
        },
        'count': len(formatted_towers),
        'towers': formatted_towers,
        'links': {
            'ofcom_coverage': build_ofcom_coverage_url(),
            'ofcom_emf': build_ofcom_emf_url(),
        }
    })


# ============================================
# ROUTES: BASELINES
# ============================================

@isms_bp.route('/baselines', methods=['GET'])
def list_baselines():
    """List all ISMS baselines."""
    baselines = get_all_isms_baselines()
    return jsonify({
        'baselines': baselines
    })


@isms_bp.route('/baselines', methods=['POST'])
def create_baseline():
    """Create a new baseline manually."""
    data = request.get_json() or {}

    name = data.get('name')
    if not name:
        return jsonify({
            'status': 'error',
            'message': 'Name required'
        }), 400

    baseline_id = create_isms_baseline(
        name=name,
        location_name=data.get('location_name'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        spectrum_profile=data.get('spectrum_profile'),
        cellular_environment=data.get('cellular_environment'),
        known_towers=data.get('known_towers'),
    )

    return jsonify({
        'status': 'created',
        'baseline_id': baseline_id
    })


@isms_bp.route('/baseline/<int:baseline_id>', methods=['GET'])
def get_baseline(baseline_id: int):
    """Get a specific baseline."""
    baseline = get_isms_baseline(baseline_id)
    if not baseline:
        return jsonify({
            'status': 'error',
            'message': 'Baseline not found'
        }), 404

    return jsonify(baseline)


@isms_bp.route('/baseline/<int:baseline_id>', methods=['DELETE'])
def remove_baseline(baseline_id: int):
    """Delete a baseline."""
    if delete_isms_baseline(baseline_id):
        return jsonify({'status': 'deleted'})
    return jsonify({
        'status': 'error',
        'message': 'Baseline not found'
    }), 404


@isms_bp.route('/baseline/<int:baseline_id>/activate', methods=['POST'])
def activate_baseline(baseline_id: int):
    """Set a baseline as active."""
    if set_active_isms_baseline(baseline_id):
        return jsonify({'status': 'activated'})
    return jsonify({
        'status': 'error',
        'message': 'Baseline not found'
    }), 404


@isms_bp.route('/baseline/active', methods=['GET'])
def get_active_baseline():
    """Get the currently active baseline."""
    baseline = get_active_isms_baseline()
    if baseline:
        return jsonify(baseline)
    return jsonify({'status': 'none'})


@isms_bp.route('/baseline/record/start', methods=['POST'])
def start_baseline_recording():
    """Start recording a new baseline."""
    if baseline_recorder.is_recording:
        return jsonify({
            'status': 'error',
            'message': 'Already recording'
        }), 409

    baseline_recorder.start_recording()
    return jsonify({'status': 'recording_started'})


@isms_bp.route('/baseline/record/stop', methods=['POST'])
def stop_baseline_recording():
    """Stop recording and save baseline."""
    if not baseline_recorder.is_recording:
        return jsonify({
            'status': 'error',
            'message': 'Not recording'
        }), 400

    data = request.get_json() or {}
    name = data.get('name', f'Baseline {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    location_name = data.get('location_name')

    # Get current location
    lat = data.get('latitude') or isms_config.get('lat')
    lon = data.get('longitude') or isms_config.get('lon')

    if not lat or not lon:
        pos = get_current_position()
        if pos:
            lat = pos.latitude
            lon = pos.longitude

    # Stop recording and compile data
    baseline_data = baseline_recorder.stop_recording()

    # Save to database
    baseline_id = save_baseline_to_db(
        name=name,
        location_name=location_name,
        latitude=lat,
        longitude=lon,
        baseline_data=baseline_data,
    )

    return jsonify({
        'status': 'saved',
        'baseline_id': baseline_id,
        'summary': {
            'bands': len(baseline_data.get('spectrum_profile', {})),
            'cells': len(baseline_data.get('cellular_environment', [])),
            'towers': len(baseline_data.get('known_towers', [])),
        }
    })


# ============================================
# ROUTES: FINDINGS
# ============================================

@isms_bp.route('/findings', methods=['GET'])
def list_findings():
    """Get ISMS findings."""
    scan_id = request.args.get('scan_id', type=int)
    severity = request.args.get('severity')
    limit = request.args.get('limit', default=100, type=int)

    findings = get_isms_findings(
        scan_id=scan_id,
        severity=severity,
        limit=limit,
    )

    return jsonify({
        'findings': findings,
        'count': len(findings),
    })


@isms_bp.route('/findings/summary', methods=['GET'])
def findings_summary():
    """Get findings count summary."""
    summary = get_isms_findings_summary()
    return jsonify(summary)


@isms_bp.route('/finding/<int:finding_id>/acknowledge', methods=['POST'])
def acknowledge_finding(finding_id: int):
    """Acknowledge a finding."""
    if acknowledge_isms_finding(finding_id):
        return jsonify({'status': 'acknowledged'})
    return jsonify({
        'status': 'error',
        'message': 'Finding not found'
    }), 404


# ============================================
# ROUTES: SCANS
# ============================================

@isms_bp.route('/scans', methods=['GET'])
def list_scans():
    """List recent scans."""
    limit = request.args.get('limit', default=20, type=int)
    scans = get_recent_isms_scans(limit=limit)
    return jsonify({
        'scans': scans
    })


@isms_bp.route('/scan/<int:scan_id>', methods=['GET'])
def get_scan_details(scan_id: int):
    """Get details of a specific scan."""
    scan = get_isms_scan(scan_id)
    if not scan:
        return jsonify({
            'status': 'error',
            'message': 'Scan not found'
        }), 404

    # Include findings
    findings = get_isms_findings(scan_id=scan_id)
    scan['findings'] = findings

    return jsonify(scan)


# ============================================
# ROUTES: GSM SCANNING
# ============================================

def gsm_scan_loop(band: str, gain: int, ppm: int, timeout: float) -> None:
    """GSM scanning background thread."""
    global gsm_running, gsm_detected_cells

    logger.info(f"GSM scan thread started for band {band}")
    emit_status('gsm_scanning', band=band)

    cells: list[GsmCell] = []

    try:
        for cell in run_grgsm_scan(
            band=band,
            gain=gain,
            ppm=ppm,
            speed=4,
            timeout=timeout,
        ):
            if not gsm_running:
                break

            cells.append(cell)

            # Emit cell detection event
            emit_event('gsm_cell', {
                'cell': format_gsm_cell(cell),
            })

        # Deduplicate and store results
        gsm_detected_cells = deduplicate_cells(cells)

        # Run anomaly detection if baseline available
        if gsm_baseline_cells:
            anomalies = identify_gsm_anomalies(gsm_detected_cells, gsm_baseline_cells)
            for anomaly in anomalies:
                emit_finding(
                    anomaly['severity'],
                    anomaly['description'],
                    finding_type=anomaly['type'],
                    band='GSM',
                    frequency=anomaly.get('cell', {}).get('freq_mhz'),
                )

        # Emit summary
        emit_event('gsm_scan_complete', {
            'cell_count': len(gsm_detected_cells),
            'cells': [format_gsm_cell(c) for c in gsm_detected_cells[:10]],  # Top 10 by signal
        })

    except Exception as e:
        logger.error(f"GSM scan error: {e}")
        emit_status('gsm_error', message=str(e))

    finally:
        gsm_running = False
        emit_status('gsm_stopped', cell_count=len(gsm_detected_cells))
        logger.info(f"GSM scan stopped, found {len(gsm_detected_cells)} cells")


@isms_bp.route('/gsm/scan', methods=['POST'])
def start_gsm_scan():
    """Start GSM cell scanning with grgsm_scanner."""
    global gsm_thread, gsm_running

    with gsm_lock:
        if gsm_running:
            return jsonify({
                'status': 'error',
                'message': 'GSM scan already running'
            }), 409

        # Check for grgsm_scanner
        if not get_grgsm_scanner_path():
            gsm_running = False
            return jsonify({
                'status': 'error',
                'message': 'grgsm_scanner not found. Install gr-gsm package.',
                'install_hint': 'See setup.sh or install gr-gsm from https://github.com/ptrkrysik/gr-gsm',
                'grgsm_available': False
            }), 503

        # Get configuration from request
        data = request.get_json() or {}
        band = data.get('band', 'GSM900')
        gain = data.get('gain', isms_config['gain'])
        ppm = data.get('ppm', isms_config.get('ppm', 0))
        timeout = data.get('timeout', 60)

        # Validate band
        valid_bands = ['GSM900', 'EGSM900', 'GSM1800', 'GSM850', 'GSM1900']
        if band.upper() not in valid_bands:
            return jsonify({
                'status': 'error',
                'message': f'Invalid band. Must be one of: {", ".join(valid_bands)}'
            }), 400

        gsm_running = True
        gsm_thread = threading.Thread(
            target=gsm_scan_loop,
            args=(band.upper(), gain, ppm, timeout),
            daemon=True
        )
        gsm_thread.start()

        return jsonify({
            'status': 'started',
            'config': {
                'band': band.upper(),
                'gain': gain,
                'timeout': timeout,
            }
        })


@isms_bp.route('/gsm/scan', methods=['DELETE'])
def stop_gsm_scan():
    """Stop GSM scanning."""
    global gsm_running

    with gsm_lock:
        if not gsm_running:
            return jsonify({
                'status': 'error',
                'message': 'No GSM scan running'
            }), 400

        gsm_running = False

    return jsonify({'status': 'stopping'})


@isms_bp.route('/gsm/status', methods=['GET'])
def get_gsm_status():
    """Get GSM scanner status and detected cells."""
    with gsm_lock:
        return jsonify({
            'running': gsm_running,
            'cell_count': len(gsm_detected_cells),
            'cells': [format_gsm_cell(c) for c in gsm_detected_cells],
            'grgsm_available': get_grgsm_scanner_path() is not None,
        })


@isms_bp.route('/gsm/cells', methods=['GET'])
def get_gsm_cells():
    """Get all detected GSM cells from last scan."""
    return jsonify({
        'cells': [format_gsm_cell(c) for c in gsm_detected_cells],
        'count': len(gsm_detected_cells),
    })


@isms_bp.route('/gsm/baseline', methods=['POST'])
def set_gsm_baseline():
    """Save current GSM cells as baseline for comparison."""
    global gsm_baseline_cells

    if not gsm_detected_cells:
        return jsonify({
            'status': 'error',
            'message': 'No GSM cells detected. Run a scan first.'
        }), 400

    gsm_baseline_cells = gsm_detected_cells.copy()

    # Also add to baseline recorder if recording
    if baseline_recorder.is_recording:
        for cell in gsm_baseline_cells:
            baseline_recorder.add_gsm_cell(cell)

    return jsonify({
        'status': 'saved',
        'cell_count': len(gsm_baseline_cells),
        'cells': [format_gsm_cell(c) for c in gsm_baseline_cells],
    })


@isms_bp.route('/gsm/baseline', methods=['GET'])
def get_gsm_baseline():
    """Get current GSM baseline."""
    return jsonify({
        'cells': [format_gsm_cell(c) for c in gsm_baseline_cells],
        'count': len(gsm_baseline_cells),
    })


@isms_bp.route('/gsm/baseline', methods=['DELETE'])
def clear_gsm_baseline():
    """Clear GSM baseline."""
    global gsm_baseline_cells
    gsm_baseline_cells = []
    return jsonify({'status': 'cleared'})
