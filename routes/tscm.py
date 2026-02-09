"""
TSCM (Technical Surveillance Countermeasures) Routes

Provides endpoints for counter-surveillance sweeps, baseline management,
threat detection, and reporting.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, Response, jsonify, request

from data.tscm_frequencies import (
    SWEEP_PRESETS,
    get_all_sweep_presets,
    get_sweep_preset,
)
from utils.database import (
    add_device_timeline_entry,
    add_tscm_threat,
    acknowledge_tscm_threat,
    cleanup_old_timeline_entries,
    create_tscm_schedule,
    create_tscm_sweep,
    delete_tscm_baseline,
    delete_tscm_schedule,
    get_active_tscm_baseline,
    get_all_tscm_baselines,
    get_all_tscm_schedules,
    get_tscm_baseline,
    get_tscm_schedule,
    get_tscm_sweep,
    get_tscm_threat_summary,
    get_tscm_threats,
    set_active_tscm_baseline,
    update_tscm_schedule,
    update_tscm_sweep,
)
from utils.tscm.baseline import (
    BaselineComparator,
    BaselineRecorder,
    get_comparison_for_active_baseline,
)
from utils.tscm.correlation import (
    CorrelationEngine,
    get_correlation_engine,
    reset_correlation_engine,
)
from utils.tscm.detector import ThreatDetector
from utils.tscm.device_identity import (
    get_identity_engine,
    reset_identity_engine,
    ingest_ble_dict,
    ingest_wifi_dict,
)
from utils.event_pipeline import process_event

# Import unified Bluetooth scanner helper for TSCM integration
try:
    from routes.bluetooth_v2 import get_tscm_bluetooth_snapshot
    _USE_UNIFIED_BT_SCANNER = True
except ImportError:
    _USE_UNIFIED_BT_SCANNER = False

logger = logging.getLogger('intercept.tscm')

tscm_bp = Blueprint('tscm', __name__, url_prefix='/tscm')

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - fallback for older Python
    ZoneInfo = None

# =============================================================================
# Global State (will be initialized from app.py)
# =============================================================================

# These will be set by app.py
tscm_queue: queue.Queue | None = None
tscm_lock: threading.Lock | None = None

# Local state
_sweep_thread: threading.Thread | None = None
_sweep_running = False
_current_sweep_id: int | None = None
_baseline_recorder = BaselineRecorder()
_schedule_thread: threading.Thread | None = None
_schedule_running = False


def init_tscm_state(tscm_q: queue.Queue, lock: threading.Lock) -> None:
    """Initialize TSCM state from app.py."""
    global tscm_queue, tscm_lock
    tscm_queue = tscm_q
    tscm_lock = lock
    start_tscm_scheduler()


def _emit_event(event_type: str, data: dict) -> None:
    """Emit an event to the SSE queue."""
    if tscm_queue:
        try:
            tscm_queue.put_nowait({
                'type': event_type,
                'timestamp': datetime.now().isoformat(),
                **data
            })
        except queue.Full:
            logger.warning("TSCM queue full, dropping event")


# =============================================================================
# Schedule Helpers
# =============================================================================

def _get_schedule_timezone(zone_name: str | None) -> Any:
    """Resolve schedule timezone from a zone name or fallback to local."""
    if zone_name and ZoneInfo:
        try:
            return ZoneInfo(zone_name)
        except Exception:
            logger.warning(f"Invalid timezone '{zone_name}', using local time")
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_cron_field(field: str, min_value: int, max_value: int) -> set[int]:
    """Parse a single cron field into a set of valid integers."""
    field = field.strip()
    if not field:
        raise ValueError("Empty cron field")

    values: set[int] = set()
    parts = field.split(',')
    for part in parts:
        part = part.strip()
        if part == '*':
            values.update(range(min_value, max_value + 1))
            continue
        if part.startswith('*/'):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("Invalid step value")
            values.update(range(min_value, max_value + 1, step))
            continue
        range_part = part
        step = 1
        if '/' in part:
            range_part, step_str = part.split('/', 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError("Invalid step value")
        if '-' in range_part:
            start_str, end_str = range_part.split('-', 1)
            start = int(start_str)
            end = int(end_str)
            if start > end:
                start, end = end, start
            values.update(range(start, end + 1, step))
        else:
            values.add(int(range_part))

    return {v for v in values if min_value <= v <= max_value}


def _parse_cron_expression(expr: str) -> tuple[dict[str, set[int]], dict[str, bool]]:
    """Parse a cron expression into value sets and wildcard flags."""
    fields = (expr or '').split()
    if len(fields) != 5:
        raise ValueError("Cron expression must have 5 fields")

    minute_field, hour_field, dom_field, month_field, dow_field = fields

    sets = {
        'minute': _parse_cron_field(minute_field, 0, 59),
        'hour': _parse_cron_field(hour_field, 0, 23),
        'dom': _parse_cron_field(dom_field, 1, 31),
        'month': _parse_cron_field(month_field, 1, 12),
        'dow': _parse_cron_field(dow_field, 0, 7),
    }

    # Normalize Sunday (7 -> 0)
    if 7 in sets['dow']:
        sets['dow'].add(0)
        sets['dow'].discard(7)

    wildcards = {
        'dom': dom_field.strip() == '*',
        'dow': dow_field.strip() == '*',
    }
    return sets, wildcards


def _cron_matches(dt: datetime, sets: dict[str, set[int]], wildcards: dict[str, bool]) -> bool:
    """Check if a datetime matches cron sets."""
    if dt.minute not in sets['minute']:
        return False
    if dt.hour not in sets['hour']:
        return False
    if dt.month not in sets['month']:
        return False

    dom_match = dt.day in sets['dom']
    # Cron DOW: Sunday=0
    cron_dow = (dt.weekday() + 1) % 7
    dow_match = cron_dow in sets['dow']

    if wildcards['dom'] and wildcards['dow']:
        return True
    if wildcards['dom']:
        return dow_match
    if wildcards['dow']:
        return dom_match
    return dom_match or dow_match


def _next_run_from_cron(expr: str, after_dt: datetime) -> datetime | None:
    """Calculate next run time from cron expression after a given datetime."""
    sets, wildcards = _parse_cron_expression(expr)
    # Round to next minute
    candidate = after_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Search up to 366 days ahead
    for _ in range(366 * 24 * 60):
        if _cron_matches(candidate, sets, wildcards):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def _parse_schedule_timestamp(value: Any) -> datetime | None:
    """Parse stored schedule timestamp to aware datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _schedule_loop() -> None:
    """Background loop to trigger scheduled sweeps."""
    global _schedule_running

    while _schedule_running:
        try:
            schedules = get_all_tscm_schedules(enabled=True, limit=200)
            now_utc = datetime.now(timezone.utc)

            for schedule in schedules:
                schedule_id = schedule.get('id')
                cron_expr = schedule.get('cron_expression') or ''
                tz = _get_schedule_timezone(schedule.get('zone_name'))
                now_local = datetime.now(tz)

                next_run = _parse_schedule_timestamp(schedule.get('next_run'))

                if not next_run:
                    try:
                        computed = _next_run_from_cron(cron_expr, now_local)
                    except Exception as e:
                        logger.error(f"Schedule {schedule_id} cron parse error: {e}")
                        continue
                    if computed:
                        update_tscm_schedule(
                            schedule_id,
                            next_run=computed.astimezone(timezone.utc).isoformat()
                        )
                    continue

                if next_run <= now_utc:
                    if _sweep_running:
                        logger.info(f"Schedule {schedule_id} due but sweep running; skipping")
                        try:
                            computed = _next_run_from_cron(cron_expr, now_local)
                        except Exception as e:
                            logger.error(f"Schedule {schedule_id} cron parse error: {e}")
                            continue
                        if computed:
                            update_tscm_schedule(
                                schedule_id,
                                next_run=computed.astimezone(timezone.utc).isoformat()
                            )
                        continue

                    # Trigger sweep
                    result = _start_sweep_internal(
                        sweep_type=schedule.get('sweep_type') or 'standard',
                        baseline_id=schedule.get('baseline_id'),
                        wifi_enabled=True,
                        bt_enabled=True,
                        rf_enabled=True,
                        wifi_interface='',
                        bt_interface='',
                        sdr_device=None,
                        verbose_results=False
                    )

                    if result.get('status') == 'success':
                        try:
                            computed = _next_run_from_cron(cron_expr, now_local)
                        except Exception as e:
                            logger.error(f"Schedule {schedule_id} cron parse error: {e}")
                            computed = None

                        update_tscm_schedule(
                            schedule_id,
                            last_run=now_utc.isoformat(),
                            next_run=computed.astimezone(timezone.utc).isoformat() if computed else None
                        )
                        logger.info(f"Scheduled sweep started for schedule {schedule_id}")
                    else:
                        try:
                            computed = _next_run_from_cron(cron_expr, now_local)
                        except Exception as e:
                            logger.error(f"Schedule {schedule_id} cron parse error: {e}")
                            computed = None
                        if computed:
                            update_tscm_schedule(
                                schedule_id,
                                next_run=computed.astimezone(timezone.utc).isoformat()
                            )
                        logger.warning(f"Scheduled sweep failed for schedule {schedule_id}: {result.get('message')}")

        except Exception as e:
            logger.error(f"TSCM schedule loop error: {e}")

        time.sleep(30)


def start_tscm_scheduler() -> None:
    """Start background scheduler thread for TSCM sweeps."""
    global _schedule_thread, _schedule_running
    if _schedule_thread and _schedule_thread.is_alive():
        return
    _schedule_running = True
    _schedule_thread = threading.Thread(target=_schedule_loop, daemon=True)
    _schedule_thread.start()


# =============================================================================
# Sweep Endpoints
# =============================================================================

def _check_available_devices(wifi: bool, bt: bool, rf: bool) -> dict:
    """Check which scanning devices are available."""
    import os
    import platform
    import shutil
    import subprocess

    available = {
        'wifi': False,
        'bluetooth': False,
        'rf': False,
        'wifi_reason': 'Not checked',
        'bt_reason': 'Not checked',
        'rf_reason': 'Not checked',
    }

    # Check WiFi - use the same scanner singleton that performs actual scans
    if wifi:
        try:
            from utils.wifi.scanner import get_wifi_scanner
            scanner = get_wifi_scanner()
            interfaces = scanner._detect_interfaces()
            if interfaces:
                available['wifi'] = True
                available['wifi_reason'] = f'WiFi available ({interfaces[0]["name"]})'
            else:
                available['wifi_reason'] = 'No wireless interfaces found'
        except Exception as e:
            available['wifi_reason'] = f'WiFi detection error: {e}'

    # Check Bluetooth
    if bt:
        if platform.system() == 'Darwin':
            # macOS: Check for Bluetooth via system_profiler
            try:
                result = subprocess.run(
                    ['system_profiler', 'SPBluetoothDataType'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if 'Bluetooth' in result.stdout and result.returncode == 0:
                    available['bluetooth'] = True
                    available['bt_reason'] = 'macOS Bluetooth available'
                else:
                    available['bt_reason'] = 'Bluetooth not available'
            except (subprocess.TimeoutExpired, FileNotFoundError):
                available['bt_reason'] = 'Cannot detect Bluetooth'
        else:
            # Linux: Check for Bluetooth tools
            if shutil.which('bluetoothctl') or shutil.which('hcitool') or shutil.which('hciconfig'):
                try:
                    result = subprocess.run(
                        ['hciconfig'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if 'hci' in result.stdout.lower():
                        available['bluetooth'] = True
                        available['bt_reason'] = 'Bluetooth adapter detected'
                    else:
                        available['bt_reason'] = 'No Bluetooth adapters found'
                except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                    # Try bluetoothctl as fallback
                    try:
                        result = subprocess.run(
                            ['bluetoothctl', 'list'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.stdout.strip():
                            available['bluetooth'] = True
                            available['bt_reason'] = 'Bluetooth adapter detected'
                        else:
                            # Check /sys for Bluetooth
                            try:
                                import glob
                                bt_devs = glob.glob('/sys/class/bluetooth/hci*')
                                if bt_devs:
                                    available['bluetooth'] = True
                                    available['bt_reason'] = 'Bluetooth adapter detected'
                                else:
                                    available['bt_reason'] = 'No Bluetooth adapters found'
                            except Exception:
                                available['bt_reason'] = 'No Bluetooth adapters found'
                    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                        # Check /sys for Bluetooth
                        try:
                            import glob
                            bt_devs = glob.glob('/sys/class/bluetooth/hci*')
                            if bt_devs:
                                available['bluetooth'] = True
                                available['bt_reason'] = 'Bluetooth adapter detected'
                            else:
                                available['bt_reason'] = 'Cannot detect Bluetooth adapters'
                        except Exception:
                            available['bt_reason'] = 'Cannot detect Bluetooth adapters'
            else:
                # Fallback: check /sys even without tools
                try:
                    import glob
                    bt_devs = glob.glob('/sys/class/bluetooth/hci*')
                    if bt_devs:
                        available['bluetooth'] = True
                        available['bt_reason'] = 'Bluetooth adapter detected (no scan tools)'
                    else:
                        available['bt_reason'] = 'Bluetooth tools not installed (bluez)'
                except Exception:
                    available['bt_reason'] = 'Bluetooth tools not installed (bluez)'

    # Check RF/SDR
    if rf:
        try:
            from utils.sdr import SDRFactory
            devices = SDRFactory.detect_devices()
            if devices:
                available['rf'] = True
                available['rf_reason'] = f'{len(devices)} SDR device(s) detected'
            else:
                available['rf_reason'] = 'No SDR devices found'
        except ImportError:
            available['rf_reason'] = 'SDR detection unavailable'

    return available


def _start_sweep_internal(
    sweep_type: str,
    baseline_id: int | None,
    wifi_enabled: bool,
    bt_enabled: bool,
    rf_enabled: bool,
    wifi_interface: str = '',
    bt_interface: str = '',
    sdr_device: int | None = None,
    verbose_results: bool = False,
) -> dict:
    """Start a TSCM sweep without request context."""
    global _sweep_running, _sweep_thread, _current_sweep_id

    if _sweep_running:
        return {'status': 'error', 'message': 'Sweep already running', 'http_status': 409}

    # Check for available devices
    devices = _check_available_devices(wifi_enabled, bt_enabled, rf_enabled)

    warnings = []
    if wifi_enabled and not devices['wifi']:
        warnings.append(f"WiFi: {devices['wifi_reason']}")
    if bt_enabled and not devices['bluetooth']:
        warnings.append(f"Bluetooth: {devices['bt_reason']}")
    if rf_enabled and not devices['rf']:
        warnings.append(f"RF: {devices['rf_reason']}")

    # If no devices available at all, return error
    if not any([devices['wifi'], devices['bluetooth'], devices['rf']]):
        return {
            'status': 'error',
            'message': 'No scanning devices available',
            'details': warnings,
            'http_status': 400,
        }

    # Create sweep record
    _current_sweep_id = create_tscm_sweep(
        sweep_type=sweep_type,
        baseline_id=baseline_id,
        wifi_enabled=wifi_enabled,
        bt_enabled=bt_enabled,
        rf_enabled=rf_enabled
    )

    _sweep_running = True

    # Start sweep thread
    _sweep_thread = threading.Thread(
        target=_run_sweep,
        args=(sweep_type, baseline_id, wifi_enabled, bt_enabled, rf_enabled,
              wifi_interface, bt_interface, sdr_device, verbose_results),
        daemon=True
    )
    _sweep_thread.start()

    logger.info(f"Started TSCM sweep: type={sweep_type}, id={_current_sweep_id}")

    return {
        'status': 'success',
        'message': 'Sweep started',
        'sweep_id': _current_sweep_id,
        'sweep_type': sweep_type,
        'warnings': warnings if warnings else None,
        'devices': {
            'wifi': devices['wifi'],
            'bluetooth': devices['bluetooth'],
            'rf': devices['rf']
        }
    }


@tscm_bp.route('/status')
def tscm_status():
    """Check if any TSCM operation is currently running."""
    return jsonify({'running': _sweep_running})


@tscm_bp.route('/sweep/start', methods=['POST'])
def start_sweep():
    """Start a TSCM sweep."""
    data = request.get_json() or {}
    sweep_type = data.get('sweep_type', 'standard')
    baseline_id = data.get('baseline_id')
    if baseline_id in ('', None):
        baseline_id = None
    wifi_enabled = data.get('wifi', True)
    bt_enabled = data.get('bluetooth', True)
    rf_enabled = data.get('rf', True)
    verbose_results = bool(data.get('verbose_results', False))

    # Get interface selections
    wifi_interface = data.get('wifi_interface', '')
    bt_interface = data.get('bt_interface', '')
    sdr_device = data.get('sdr_device')

    result = _start_sweep_internal(
        sweep_type=sweep_type,
        baseline_id=baseline_id,
        wifi_enabled=wifi_enabled,
        bt_enabled=bt_enabled,
        rf_enabled=rf_enabled,
        wifi_interface=wifi_interface,
        bt_interface=bt_interface,
        sdr_device=sdr_device,
        verbose_results=verbose_results,
    )
    http_status = result.pop('http_status', 200)
    return jsonify(result), http_status


@tscm_bp.route('/sweep/stop', methods=['POST'])
def stop_sweep():
    """Stop the current TSCM sweep."""
    global _sweep_running

    if not _sweep_running:
        return jsonify({'status': 'error', 'message': 'No sweep running'})

    _sweep_running = False

    if _current_sweep_id:
        update_tscm_sweep(_current_sweep_id, status='aborted', completed=True)

    _emit_event('sweep_stopped', {'reason': 'user_requested'})

    logger.info("TSCM sweep stopped by user")

    return jsonify({'status': 'success', 'message': 'Sweep stopped'})


@tscm_bp.route('/sweep/status')
def sweep_status():
    """Get current sweep status."""
    status = {
        'running': _sweep_running,
        'sweep_id': _current_sweep_id,
    }

    if _current_sweep_id:
        sweep = get_tscm_sweep(_current_sweep_id)
        if sweep:
            status['sweep'] = sweep

    return jsonify(status)


@tscm_bp.route('/sweep/stream')
def sweep_stream():
    """SSE stream for real-time sweep updates."""
    def generate():
        while True:
            try:
                if tscm_queue:
                    msg = tscm_queue.get(timeout=1)
                    try:
                        process_event('tscm', msg, msg.get('type'))
                    except Exception:
                        pass
                    yield f"data: {json.dumps(msg)}\n\n"
                else:
                    time.sleep(1)
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


# =============================================================================
# Schedule Endpoints
# =============================================================================

@tscm_bp.route('/schedules', methods=['GET'])
def list_schedules():
    """List all TSCM sweep schedules."""
    enabled_param = request.args.get('enabled')
    enabled = None
    if enabled_param is not None:
        enabled = enabled_param.lower() in ('1', 'true', 'yes')

    schedules = get_all_tscm_schedules(enabled=enabled, limit=200)
    return jsonify({
        'status': 'success',
        'count': len(schedules),
        'schedules': schedules,
    })


@tscm_bp.route('/schedules', methods=['POST'])
def create_schedule():
    """Create a new sweep schedule."""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    cron_expression = (data.get('cron_expression') or '').strip()
    sweep_type = data.get('sweep_type', 'standard')
    baseline_id = data.get('baseline_id')
    zone_name = data.get('zone_name')
    enabled = bool(data.get('enabled', True))
    notify_on_threat = bool(data.get('notify_on_threat', True))
    notify_email = data.get('notify_email')

    if not name:
        return jsonify({'status': 'error', 'message': 'Schedule name required'}), 400
    if not cron_expression:
        return jsonify({'status': 'error', 'message': 'cron_expression required'}), 400

    next_run = None
    if enabled:
        try:
            tz = _get_schedule_timezone(zone_name)
            next_local = _next_run_from_cron(cron_expression, datetime.now(tz))
            next_run = next_local.astimezone(timezone.utc).isoformat() if next_local else None
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Invalid cron: {e}'}), 400

    schedule_id = create_tscm_schedule(
        name=name,
        cron_expression=cron_expression,
        sweep_type=sweep_type,
        baseline_id=baseline_id,
        zone_name=zone_name,
        enabled=enabled,
        notify_on_threat=notify_on_threat,
        notify_email=notify_email,
        next_run=next_run,
    )
    schedule = get_tscm_schedule(schedule_id)
    return jsonify({
        'status': 'success',
        'message': 'Schedule created',
        'schedule': schedule
    })


@tscm_bp.route('/schedules/<int:schedule_id>', methods=['PUT', 'PATCH'])
def update_schedule(schedule_id: int):
    """Update a sweep schedule."""
    schedule = get_tscm_schedule(schedule_id)
    if not schedule:
        return jsonify({'status': 'error', 'message': 'Schedule not found'}), 404

    data = request.get_json() or {}
    updates: dict[str, Any] = {}

    for key in ('name', 'cron_expression', 'sweep_type', 'baseline_id', 'zone_name', 'notify_email'):
        if key in data:
            updates[key] = data[key]

    if 'baseline_id' in updates and updates['baseline_id'] in ('', None):
        updates['baseline_id'] = None

    if 'enabled' in data:
        updates['enabled'] = 1 if data['enabled'] else 0
    if 'notify_on_threat' in data:
        updates['notify_on_threat'] = 1 if data['notify_on_threat'] else 0

    # Recalculate next_run when cron/zone/enabled changes
    if any(k in updates for k in ('cron_expression', 'zone_name', 'enabled')):
        if updates.get('enabled', schedule.get('enabled', 1)):
            cron_expr = updates.get('cron_expression', schedule.get('cron_expression', ''))
            zone_name = updates.get('zone_name', schedule.get('zone_name'))
            try:
                tz = _get_schedule_timezone(zone_name)
                next_local = _next_run_from_cron(cron_expr, datetime.now(tz))
                updates['next_run'] = next_local.astimezone(timezone.utc).isoformat() if next_local else None
            except Exception as e:
                return jsonify({'status': 'error', 'message': f'Invalid cron: {e}'}), 400
        else:
            updates['next_run'] = None

    if not updates:
        return jsonify({'status': 'error', 'message': 'No updates provided'}), 400

    update_tscm_schedule(schedule_id, **updates)
    schedule = get_tscm_schedule(schedule_id)
    return jsonify({'status': 'success', 'schedule': schedule})


@tscm_bp.route('/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id: int):
    """Delete a sweep schedule."""
    success = delete_tscm_schedule(schedule_id)
    if not success:
        return jsonify({'status': 'error', 'message': 'Schedule not found'}), 404
    return jsonify({'status': 'success', 'message': 'Schedule deleted'})


@tscm_bp.route('/schedules/<int:schedule_id>/run', methods=['POST'])
def run_schedule_now(schedule_id: int):
    """Trigger a scheduled sweep immediately."""
    schedule = get_tscm_schedule(schedule_id)
    if not schedule:
        return jsonify({'status': 'error', 'message': 'Schedule not found'}), 404

    result = _start_sweep_internal(
        sweep_type=schedule.get('sweep_type') or 'standard',
        baseline_id=schedule.get('baseline_id'),
        wifi_enabled=True,
        bt_enabled=True,
        rf_enabled=True,
        wifi_interface='',
        bt_interface='',
        sdr_device=None,
        verbose_results=False,
    )

    if result.get('status') != 'success':
        status_code = result.pop('http_status', 400)
        return jsonify(result), status_code

    # Update schedule run timestamps
    cron_expr = schedule.get('cron_expression') or ''
    tz = _get_schedule_timezone(schedule.get('zone_name'))
    now_utc = datetime.now(timezone.utc)
    try:
        next_local = _next_run_from_cron(cron_expr, datetime.now(tz))
    except Exception:
        next_local = None

    update_tscm_schedule(
        schedule_id,
        last_run=now_utc.isoformat(),
        next_run=next_local.astimezone(timezone.utc).isoformat() if next_local else None,
    )

    return jsonify(result)


@tscm_bp.route('/devices')
def get_tscm_devices():
    """Get available scanning devices for TSCM sweeps."""
    import platform
    import shutil
    import subprocess

    devices = {
        'wifi_interfaces': [],
        'bt_adapters': [],
        'sdr_devices': []
    }

    # Detect WiFi interfaces
    if platform.system() == 'Darwin':  # macOS
        try:
            result = subprocess.run(
                ['networksetup', '-listallhardwareports'],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if 'Wi-Fi' in line or 'AirPort' in line:
                    # Get the hardware port name (e.g., "Wi-Fi")
                    port_name = line.replace('Hardware Port:', '').strip()
                    for j in range(i + 1, min(i + 3, len(lines))):
                        if 'Device:' in lines[j]:
                            device = lines[j].split('Device:')[1].strip()
                            devices['wifi_interfaces'].append({
                                'name': device,
                                'display_name': f'{port_name} ({device})',
                                'type': 'internal',
                                'monitor_capable': False
                            })
                            break
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
    else:  # Linux
        try:
            result = subprocess.run(
                ['iw', 'dev'],
                capture_output=True, text=True, timeout=5
            )
            current_iface = None
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Interface'):
                    current_iface = line.split()[1]
                elif current_iface and 'type' in line:
                    iface_type = line.split()[-1]
                    devices['wifi_interfaces'].append({
                        'name': current_iface,
                        'display_name': f'Wireless ({current_iface}) - {iface_type}',
                        'type': iface_type,
                        'monitor_capable': True
                    })
                    current_iface = None
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            # Fall back to iwconfig
            try:
                result = subprocess.run(
                    ['iwconfig'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'IEEE 802.11' in line:
                        iface = line.split()[0]
                        devices['wifi_interfaces'].append({
                            'name': iface,
                            'display_name': f'Wireless ({iface})',
                            'type': 'managed',
                            'monitor_capable': True
                        })
            except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    # Detect Bluetooth adapters
    if platform.system() == 'Linux':
        try:
            result = subprocess.run(
                ['hciconfig'],
                capture_output=True, text=True, timeout=5
            )
            import re
            blocks = re.split(r'(?=^hci\d+:)', result.stdout, flags=re.MULTILINE)
            for idx, block in enumerate(blocks):
                if block.strip():
                    first_line = block.split('\n')[0]
                    match = re.match(r'(hci\d+):', first_line)
                    if match:
                        iface_name = match.group(1)
                        is_up = 'UP RUNNING' in block or '\tUP ' in block
                        devices['bt_adapters'].append({
                            'name': iface_name,
                            'display_name': f'Bluetooth Adapter ({iface_name})',
                            'type': 'hci',
                            'status': 'up' if is_up else 'down'
                        })
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            # Try bluetoothctl as fallback
            try:
                result = subprocess.run(
                    ['bluetoothctl', 'list'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'Controller' in line:
                        # Format: Controller XX:XX:XX:XX:XX:XX Name
                        parts = line.split()
                        if len(parts) >= 3:
                            addr = parts[1]
                            name = ' '.join(parts[2:]) if len(parts) > 2 else 'Bluetooth'
                            devices['bt_adapters'].append({
                                'name': addr,
                                'display_name': f'{name} ({addr[-8:]})',
                                'type': 'controller',
                                'status': 'available'
                            })
            except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass
    elif platform.system() == 'Darwin':
        # macOS has built-in Bluetooth - get more info via system_profiler
        try:
            result = subprocess.run(
                ['system_profiler', 'SPBluetoothDataType'],
                capture_output=True, text=True, timeout=10
            )
            # Extract controller info
            bt_name = 'Built-in Bluetooth'
            bt_addr = ''
            for line in result.stdout.split('\n'):
                if 'Address:' in line:
                    bt_addr = line.split('Address:')[1].strip()
                    break
            devices['bt_adapters'].append({
                'name': 'default',
                'display_name': f'{bt_name}' + (f' ({bt_addr[-8:]})' if bt_addr else ''),
                'type': 'macos',
                'status': 'available'
            })
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            devices['bt_adapters'].append({
                'name': 'default',
                'display_name': 'Built-in Bluetooth',
                'type': 'macos',
                'status': 'available'
            })

    # Detect SDR devices
    try:
        from utils.sdr import SDRFactory
        sdr_list = SDRFactory.detect_devices()
        for sdr in sdr_list:
            # SDRDevice is a dataclass with attributes, not a dict
            sdr_type_name = sdr.sdr_type.value if hasattr(sdr.sdr_type, 'value') else str(sdr.sdr_type)
            # Create a friendly display name
            display_name = sdr.name
            if sdr.serial and sdr.serial not in ('N/A', 'Unknown'):
                display_name = f'{sdr.name} (SN: {sdr.serial[-8:]})'
            devices['sdr_devices'].append({
                'index': sdr.index,
                'name': sdr.name,
                'display_name': display_name,
                'type': sdr_type_name,
                'serial': sdr.serial,
                'driver': sdr.driver
            })
    except ImportError:
        logger.debug("SDR module not available")
    except Exception as e:
        logger.warning(f"Error detecting SDR devices: {e}")

    # Check if running as root
    import os
    from flask import current_app
    running_as_root = current_app.config.get('RUNNING_AS_ROOT', os.geteuid() == 0)

    warnings = []
    if not running_as_root:
        warnings.append({
            'type': 'privileges',
            'message': 'Not running as root. WiFi monitor mode and some Bluetooth features require sudo.',
            'action': 'Run with: sudo -E venv/bin/python intercept.py'
        })

    return jsonify({
        'status': 'success',
        'devices': devices,
        'running_as_root': running_as_root,
        'warnings': warnings
    })


def _scan_wifi_networks(interface: str) -> list[dict]:
    """
    Scan for WiFi networks using the unified WiFi scanner.

    This is a facade that maintains backwards compatibility with TSCM
    while using the new unified scanner module.

    Automatically detects monitor mode interfaces and uses deep scan
    (airodump-ng) when appropriate.

    Args:
        interface: WiFi interface name (optional).

    Returns:
        List of network dicts with: bssid, essid, power, channel, privacy
    """
    try:
        from utils.wifi import get_wifi_scanner

        scanner = get_wifi_scanner()

        # Check if interface is in monitor mode
        is_monitor = False
        if interface:
            is_monitor = scanner._is_monitor_mode_interface(interface)

        if is_monitor:
            # Use deep scan for monitor mode interfaces
            logger.info(f"Interface {interface} is in monitor mode, using deep scan")

            # Check if airodump-ng is available
            caps = scanner.check_capabilities()
            if not caps.has_airodump_ng:
                logger.warning("airodump-ng not available for monitor mode scanning")
                return []

            # Start a short deep scan
            if not scanner.is_scanning:
                scanner.start_deep_scan(interface=interface, band='all')

            # Wait briefly for some results
            import time
            time.sleep(5)

            # Get current access points
            networks = []
            for ap in scanner.access_points:
                networks.append(ap.to_legacy_dict())

            logger.info(f"WiFi deep scan found {len(networks)} networks")
            return networks
        else:
            # Use quick scan for managed mode interfaces
            result = scanner.quick_scan(interface=interface, timeout=15)

            if result.error:
                logger.warning(f"WiFi scan error: {result.error}")

            # Convert to legacy format for TSCM
            networks = []
            for ap in result.access_points:
                networks.append(ap.to_legacy_dict())

            logger.info(f"WiFi scan found {len(networks)} networks")
            return networks

    except ImportError as e:
        logger.error(f"Failed to import wifi scanner: {e}")
        return []
    except Exception as e:
        logger.exception(f"WiFi scan failed: {e}")
        return []


def _scan_wifi_clients(interface: str) -> list[dict]:
    """
    Get WiFi client observations from the unified WiFi scanner.

    Clients are only available when monitor-mode scanning is active.
    """
    try:
        from utils.wifi import get_wifi_scanner

        scanner = get_wifi_scanner()
        if interface:
            try:
                if not scanner._is_monitor_mode_interface(interface):
                    return []
            except Exception:
                return []

        return [client.to_dict() for client in scanner.clients]
    except ImportError as e:
        logger.error(f"Failed to import wifi scanner: {e}")
        return []
    except Exception as e:
        logger.exception(f"WiFi client scan failed: {e}")
        return []


def _scan_bluetooth_devices(interface: str, duration: int = 10) -> list[dict]:
    """
    Scan for Bluetooth devices with manufacturer data detection.

    Uses the BLE scanner module (bleak library) for proper manufacturer ID
    detection, with fallback to system tools if bleak is unavailable.
    """
    import platform
    import os
    import re
    import shutil
    import subprocess

    devices = []
    seen_macs = set()

    logger.info(f"Starting Bluetooth scan (duration={duration}s, interface={interface})")

    # Try the BLE scanner module first (uses bleak for proper manufacturer detection)
    try:
        from utils.tscm.ble_scanner import get_ble_scanner, scan_ble_devices

        logger.info("Using BLE scanner module with manufacturer detection")
        ble_devices = scan_ble_devices(duration)

        for ble_dev in ble_devices:
            mac = ble_dev.get('mac', '').upper()
            if mac and mac not in seen_macs:
                seen_macs.add(mac)

                device = {
                    'mac': mac,
                    'name': ble_dev.get('name', 'Unknown'),
                    'rssi': ble_dev.get('rssi'),
                    'type': 'ble',
                    'manufacturer': ble_dev.get('manufacturer_name'),
                    'manufacturer_id': ble_dev.get('manufacturer_id'),
                    'is_tracker': ble_dev.get('is_tracker', False),
                    'tracker_type': ble_dev.get('tracker_type'),
                    'is_airtag': ble_dev.get('is_airtag', False),
                    'is_tile': ble_dev.get('is_tile', False),
                    'is_smarttag': ble_dev.get('is_smarttag', False),
                    'is_espressif': ble_dev.get('is_espressif', False),
                    'service_uuids': ble_dev.get('service_uuids', []),
                }
                devices.append(device)

        if devices:
            logger.info(f"BLE scanner found {len(devices)} devices")
            trackers = [d for d in devices if d.get('is_tracker')]
            if trackers:
                logger.info(f"Trackers detected: {[d.get('tracker_type') for d in trackers]}")
            return devices

    except ImportError:
        logger.warning("BLE scanner module not available, using fallback")
    except Exception as e:
        logger.warning(f"BLE scanner failed: {e}, using fallback")

    if platform.system() == 'Darwin':
        # macOS: Use system_profiler for basic Bluetooth info
        try:
            result = subprocess.run(
                ['system_profiler', 'SPBluetoothDataType', '-json'],
                capture_output=True, text=True, timeout=15
            )
            import json
            data = json.loads(result.stdout)
            bt_data = data.get('SPBluetoothDataType', [{}])[0]

            # Get connected/paired devices
            for section in ['device_connected', 'device_title']:
                section_data = bt_data.get(section, {})
                if isinstance(section_data, dict):
                    for name, info in section_data.items():
                        if isinstance(info, dict):
                            mac = info.get('device_address', '')
                            if mac and mac not in seen_macs:
                                seen_macs.add(mac)
                                devices.append({
                                    'mac': mac.upper(),
                                    'name': name,
                                    'type': info.get('device_minorType', 'unknown'),
                                    'connected': section == 'device_connected'
                                })
            logger.info(f"macOS Bluetooth scan found {len(devices)} devices")
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError) as e:
            logger.warning(f"macOS Bluetooth scan failed: {e}")

    else:
        # Linux: Try multiple methods
        iface = interface or 'hci0'

        # Method 1: Try hcitool scan (simpler, more reliable)
        if shutil.which('hcitool'):
            try:
                logger.info("Trying hcitool scan...")
                result = subprocess.run(
                    ['hcitool', '-i', iface, 'scan', '--flush'],
                    capture_output=True, text=True, timeout=duration + 5
                )
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line and '\t' in line:
                        parts = line.split('\t')
                        if len(parts) >= 1 and ':' in parts[0]:
                            mac = parts[0].strip().upper()
                            name = parts[1].strip() if len(parts) > 1 else 'Unknown'
                            if mac not in seen_macs:
                                seen_macs.add(mac)
                                devices.append({'mac': mac, 'name': name})
                logger.info(f"hcitool scan found {len(devices)} classic BT devices")
            except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
                logger.warning(f"hcitool scan failed: {e}")

        # Method 2: Try btmgmt for BLE devices
        if shutil.which('btmgmt'):
            try:
                logger.info("Trying btmgmt find...")
                result = subprocess.run(
                    ['btmgmt', 'find'],
                    capture_output=True, text=True, timeout=duration + 5
                )
                for line in result.stdout.split('\n'):
                    # Parse btmgmt output: "dev_found: XX:XX:XX:XX:XX:XX type LE..."
                    if 'dev_found' in line.lower() or ('type' in line.lower() and ':' in line):
                        mac_match = re.search(
                            r'([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:'
                            r'[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})',
                            line
                        )
                        if mac_match:
                            mac = mac_match.group(1).upper()
                            if mac not in seen_macs:
                                seen_macs.add(mac)
                                # Try to extract name
                                name_match = re.search(r'name\s+(.+?)(?:\s|$)', line, re.I)
                                name = name_match.group(1) if name_match else 'Unknown BLE'
                                devices.append({
                                    'mac': mac,
                                    'name': name,
                                    'type': 'ble' if 'le' in line.lower() else 'classic'
                                })
                logger.info(f"btmgmt found {len(devices)} total devices")
            except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
                logger.warning(f"btmgmt find failed: {e}")

        # Method 3: Try bluetoothctl as last resort
        if not devices and shutil.which('bluetoothctl'):
            try:
                import pty
                import select

                logger.info("Trying bluetoothctl scan...")
                master_fd, slave_fd = pty.openpty()
                process = subprocess.Popen(
                    ['bluetoothctl'],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True
                )
                os.close(slave_fd)

                # Start scanning
                time.sleep(0.3)
                os.write(master_fd, b'power on\n')
                time.sleep(0.3)
                os.write(master_fd, b'scan on\n')

                # Collect devices for specified duration
                scan_end = time.time() + min(duration, 10)  # Cap at 10 seconds
                buffer = ''

                while time.time() < scan_end:
                    readable, _, _ = select.select([master_fd], [], [], 1.0)
                    if readable:
                        try:
                            data = os.read(master_fd, 4096)
                            if not data:
                                break
                            buffer += data.decode('utf-8', errors='replace')

                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()

                                if 'Device' in line:
                                    match = re.search(
                                        r'([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:'
                                        r'[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})\s*(.*)',
                                        line
                                    )
                                    if match:
                                        mac = match.group(1).upper()
                                        name = match.group(2).strip()
                                        # Remove RSSI from name if present
                                        name = re.sub(r'\s*RSSI:\s*-?\d+\s*', '', name).strip()

                                        if mac not in seen_macs:
                                            seen_macs.add(mac)
                                            devices.append({
                                                'mac': mac,
                                                'name': name or '[Unknown]'
                                            })
                        except OSError:
                            break

                # Stop scanning and cleanup
                try:
                    os.write(master_fd, b'scan off\n')
                    time.sleep(0.2)
                    os.write(master_fd, b'quit\n')
                except OSError:
                    pass

                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()

                try:
                    os.close(master_fd)
                except OSError:
                    pass

                logger.info(f"bluetoothctl scan found {len(devices)} devices")

            except (FileNotFoundError, subprocess.SubprocessError) as e:
                logger.warning(f"bluetoothctl scan failed: {e}")

    return devices


def _scan_rf_signals(
    sdr_device: int | None,
    duration: int = 30,
    stop_check: callable | None = None,
    sweep_ranges: list[dict] | None = None
) -> list[dict]:
    """
    Scan for RF signals using SDR (rtl_power).

    Scans common surveillance frequency bands:
    - 88-108 MHz: FM broadcast (potential FM bugs)
    - 315 MHz: Common ISM band (wireless devices)
    - 433 MHz: ISM band (European wireless devices, car keys)
    - 868 MHz: European ISM band
    - 915 MHz: US ISM band
    - 1.2 GHz: Video transmitters
    - 2.4 GHz: WiFi, Bluetooth, video transmitters

    Args:
        sdr_device: SDR device index
        duration: Scan duration per band
        stop_check: Optional callable that returns True if scan should stop.
                   Defaults to checking module-level _sweep_running.
        sweep_ranges: Optional preset ranges (MHz) from SWEEP_PRESETS.
    """
    # Default stop check uses module-level _sweep_running
    if stop_check is None:
        stop_check = lambda: not _sweep_running
    import os
    import shutil
    import subprocess
    import tempfile

    signals = []

    logger.info(f"Starting RF scan (device={sdr_device})")

    rtl_power_path = shutil.which('rtl_power')
    if not rtl_power_path:
        logger.warning("rtl_power not found in PATH, RF scanning unavailable")
        _emit_event('rf_status', {
            'status': 'error',
            'message': 'rtl_power not installed. Install rtl-sdr package for RF scanning.',
        })
        return signals

    logger.info(f"Found rtl_power at: {rtl_power_path}")

    # Test if RTL-SDR device is accessible
    rtl_test_path = shutil.which('rtl_test')
    if rtl_test_path:
        try:
            test_result = subprocess.run(
                [rtl_test_path, '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if 'No supported devices found' in test_result.stderr or test_result.returncode != 0:
                logger.warning("No RTL-SDR device found")
                _emit_event('rf_status', {
                    'status': 'error',
                    'message': 'No RTL-SDR device connected. Connect an RTL-SDR dongle for RF scanning.',
                })
                return signals
        except subprocess.TimeoutExpired:
            pass  # Device might be busy, continue anyway
        except Exception as e:
            logger.debug(f"rtl_test check failed: {e}")

    # Define frequency bands to scan (in Hz)
    # Format: (start_freq, end_freq, bin_size, description)
    scan_bands: list[tuple[int, int, int, str]] = []

    if sweep_ranges:
        for rng in sweep_ranges:
            try:
                start_mhz = float(rng.get('start', 0))
                end_mhz = float(rng.get('end', 0))
                step_mhz = float(rng.get('step', 0.1))
                name = rng.get('name') or f"{start_mhz:.1f}-{end_mhz:.1f} MHz"
                if start_mhz > 0 and end_mhz > start_mhz:
                    bin_size = max(1000, int(step_mhz * 1_000_000))
                    scan_bands.append((
                        int(start_mhz * 1_000_000),
                        int(end_mhz * 1_000_000),
                        bin_size,
                        name
                    ))
            except (TypeError, ValueError):
                continue

    if not scan_bands:
        # Fallback: focus on common bug frequencies
        scan_bands = [
            (88000000, 108000000, 100000, 'FM Broadcast'),       # FM bugs
            (315000000, 316000000, 10000, '315 MHz ISM'),        # US ISM
            (433000000, 434000000, 10000, '433 MHz ISM'),        # EU ISM
            (868000000, 869000000, 10000, '868 MHz ISM'),        # EU ISM
            (902000000, 928000000, 100000, '915 MHz ISM'),       # US ISM
            (1200000000, 1300000000, 100000, '1.2 GHz Video'),   # Video TX
            (2400000000, 2500000000, 500000, '2.4 GHz ISM'),     # WiFi/BT/Video
        ]

    # Create temp file for output
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Build device argument
        device_arg = ['-d', str(sdr_device if sdr_device is not None else 0)]

        # Scan each band and look for strong signals
        for start_freq, end_freq, bin_size, band_name in scan_bands:
            if stop_check():
                break

            logger.info(f"Scanning {band_name} ({start_freq/1e6:.1f}-{end_freq/1e6:.1f} MHz)")

            try:
                # Run rtl_power for a quick sweep of this band
                cmd = [
                    rtl_power_path,
                    '-f', f'{start_freq}:{end_freq}:{bin_size}',
                    '-g', '40',           # Gain
                    '-i', '1',            # Integration interval (1 second)
                    '-1',                 # Single shot mode
                    '-c', '20%',          # Crop 20% of edges
                ] + device_arg + [tmp_path]

                logger.debug(f"Running: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    logger.warning(f"rtl_power returned {result.returncode}: {result.stderr}")

                # Parse the CSV output
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    with open(tmp_path, 'r') as f:
                        for line in f:
                            parts = line.strip().split(',')
                            if len(parts) >= 7:
                                try:
                                    # CSV format: date, time, hz_low, hz_high, hz_step, samples, db_values...
                                    hz_low = int(parts[2])
                                    hz_high = int(parts[3])
                                    hz_step = float(parts[4])
                                    db_values = [float(x) for x in parts[6:] if x.strip()]

                                    # Find peaks above noise floor
                                    # RTL-SDR dongles have higher noise figures, so use permissive thresholds
                                    noise_floor = sum(db_values) / len(db_values) if db_values else -100
                                    threshold = noise_floor + 6  # Signal must be 6dB above noise

                                    for idx, db in enumerate(db_values):
                                        if db > threshold and db > -90:  # Detect signals above -90dBm
                                            freq_hz = hz_low + (idx * hz_step)
                                            freq_mhz = freq_hz / 1000000

                                            signals.append({
                                                'frequency': freq_mhz,
                                                'frequency_hz': freq_hz,
                                                'power': db,
                                                'band': band_name,
                                                'noise_floor': noise_floor,
                                                'signal_strength': db - noise_floor
                                            })
                                except (ValueError, IndexError):
                                    continue

                    # Clear file for next band
                    open(tmp_path, 'w').close()

            except subprocess.TimeoutExpired:
                logger.warning(f"RF scan timeout for band {band_name}")
            except Exception as e:
                logger.warning(f"RF scan error for band {band_name}: {e}")

    finally:
        # Cleanup temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Deduplicate nearby frequencies (within 100kHz)
    if signals:
        signals.sort(key=lambda x: x['frequency'])
        deduped = [signals[0]]
        for sig in signals[1:]:
            if sig['frequency'] - deduped[-1]['frequency'] > 0.1:  # 100 kHz
                deduped.append(sig)
            elif sig['power'] > deduped[-1]['power']:
                deduped[-1] = sig  # Keep stronger signal
        signals = deduped

    logger.info(f"RF scan found {len(signals)} signals")
    return signals


def _run_sweep(
    sweep_type: str,
    baseline_id: int | None,
    wifi_enabled: bool,
    bt_enabled: bool,
    rf_enabled: bool,
    wifi_interface: str = '',
    bt_interface: str = '',
    sdr_device: int | None = None,
    verbose_results: bool = False
) -> None:
    """
    Run the TSCM sweep in a background thread.

    This orchestrates data collection from WiFi, BT, and RF sources,
    then analyzes results for threats using the correlation engine.
    """
    global _sweep_running, _current_sweep_id

    try:
        # Get baseline for comparison if specified
        baseline = None
        if baseline_id:
            baseline = get_tscm_baseline(baseline_id)

        # Get sweep preset
        preset = get_sweep_preset(sweep_type) or SWEEP_PRESETS.get('standard')
        duration = preset.get('duration_seconds', 300)

        _emit_event('sweep_started', {
            'sweep_id': _current_sweep_id,
            'sweep_type': sweep_type,
            'duration': duration,
            'wifi': wifi_enabled,
            'bluetooth': bt_enabled,
            'rf': rf_enabled,
        })

        # Initialize detector and correlation engine
        detector = ThreatDetector(baseline)
        correlation = get_correlation_engine()
        # Clear old profiles from previous sweeps (keep 24h history)
        correlation.clear_old_profiles(24)

        # Initialize device identity engine for MAC-randomization resistant detection
        identity_engine = get_identity_engine()
        identity_engine.clear()  # Start fresh for this sweep
        from utils.tscm.advanced import get_timeline_manager
        timeline_manager = get_timeline_manager()
        try:
            cleanup_old_timeline_entries(72)
        except Exception as e:
            logger.debug(f"TSCM timeline cleanup skipped: {e}")

        last_timeline_write: dict[str, float] = {}
        timeline_bucket = getattr(timeline_manager, 'bucket_seconds', 30)

        def _maybe_store_timeline(
            identifier: str,
            protocol: str,
            rssi: int | None = None,
            channel: int | None = None,
            frequency: float | None = None,
            attributes: dict | None = None
        ) -> None:
            if not identifier:
                return

            identifier_norm = identifier.upper() if isinstance(identifier, str) else str(identifier)
            key = f"{protocol}:{identifier_norm}"
            now_ts = time.time()
            last_ts = last_timeline_write.get(key)
            if last_ts and (now_ts - last_ts) < timeline_bucket:
                return

            last_timeline_write[key] = now_ts
            try:
                add_device_timeline_entry(
                    device_identifier=identifier_norm,
                    protocol=protocol,
                    sweep_id=_current_sweep_id,
                    rssi=rssi,
                    channel=channel,
                    frequency=frequency,
                    attributes=attributes
                )
            except Exception as e:
                logger.debug(f"TSCM timeline store error: {e}")

        # Collect and analyze data
        threats_found = 0
        severity_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        all_wifi = {}  # Use dict for deduplication by BSSID
        all_wifi_clients = {}  # Use dict for deduplication by client MAC
        all_bt = {}    # Use dict for deduplication by MAC
        all_rf = []

        start_time = time.time()
        last_wifi_scan = 0
        last_bt_scan = 0
        last_rf_scan = 0
        wifi_scan_interval = 15  # Scan WiFi every 15 seconds
        bt_scan_interval = 20   # Scan Bluetooth every 20 seconds
        rf_scan_interval = 30   # Scan RF every 30 seconds

        while _sweep_running and (time.time() - start_time) < duration:
            current_time = time.time()

            # Perform WiFi scan
            if wifi_enabled and (current_time - last_wifi_scan) >= wifi_scan_interval:
                try:
                    wifi_networks = _scan_wifi_networks(wifi_interface)
                    last_wifi_scan = current_time
                    if not wifi_networks and not all_wifi:
                        logger.warning("TSCM WiFi scan returned 0 networks")
                    _emit_event('sweep_progress', {
                        'progress': min(95, int(((current_time - start_time) / duration) * 100)),
                        'status': f'Scanning WiFi... ({len(wifi_networks)} found)',
                        'wifi_count': len(all_wifi) + len([n for n in wifi_networks if n.get('bssid') and n.get('bssid') not in all_wifi]),
                        'bt_count': len(all_bt),
                        'rf_count': len(all_rf),
                    })
                    for network in wifi_networks:
                        try:
                            bssid = network.get('bssid', '')
                            ssid = network.get('essid', network.get('ssid'))
                            try:
                                rssi_val = int(network.get('power', network.get('signal')))
                            except (ValueError, TypeError):
                                rssi_val = None
                            if bssid:
                                try:
                                    timeline_manager.add_observation(
                                        identifier=bssid,
                                        protocol='wifi',
                                        rssi=rssi_val,
                                        channel=network.get('channel'),
                                        name=ssid,
                                        attributes={'ssid': ssid, 'encryption': network.get('privacy')}
                                    )
                                except Exception as e:
                                    logger.debug(f"WiFi timeline observation error: {e}")
                                _maybe_store_timeline(
                                    identifier=bssid,
                                    protocol='wifi',
                                    rssi=rssi_val,
                                    channel=network.get('channel'),
                                    attributes={'ssid': ssid, 'encryption': network.get('privacy')}
                                )
                            if bssid and bssid not in all_wifi:
                                all_wifi[bssid] = network
                                # Emit device event for frontend
                                is_threat = False
                                # Analyze for threats
                                threat = detector.analyze_wifi_device(network)
                                if threat:
                                    _handle_threat(threat)
                                    threats_found += 1
                                    is_threat = True
                                    sev = threat.get('severity', 'low').lower()
                                    if sev in severity_counts:
                                        severity_counts[sev] += 1
                                # Classify device and get correlation profile
                                classification = detector.classify_wifi_device(network)
                                profile = correlation.analyze_wifi_device(network)

                                # Feed to identity engine for MAC-randomization resistant clustering
                                # Note: WiFi APs don't typically use randomized MACs, but clients do
                                try:
                                    wifi_obs = {
                                        'timestamp': datetime.now().isoformat(),
                                        'src_mac': bssid,
                                        'bssid': bssid,
                                        'ssid': network.get('essid'),
                                        'rssi': network.get('power'),
                                        'channel': network.get('channel'),
                                        'encryption': network.get('privacy'),
                                        'frame_type': 'beacon',
                                    }
                                    ingest_wifi_dict(wifi_obs)
                                except Exception as e:
                                    logger.debug(f"Identity engine WiFi ingest error: {e}")

                                # Send device to frontend
                                _emit_event('wifi_device', {
                                    'bssid': bssid,
                                    'ssid': network.get('essid', 'Hidden'),
                                    'channel': network.get('channel', ''),
                                    'signal': network.get('power', ''),
                                    'security': network.get('privacy', ''),
                                    'vendor': network.get('vendor'),
                                    'is_threat': is_threat,
                                    'is_new': not classification.get('in_baseline', False),
                                    'classification': profile.risk_level.value,
                                    'reasons': classification.get('reasons', []),
                                    'score': profile.total_score,
                                    'score_modifier': profile.score_modifier,
                                    'known_device': profile.known_device,
                                    'known_device_name': profile.known_device_name,
                                    'indicators': [{'type': i.type.value, 'desc': i.description} for i in profile.indicators],
                                    'recommended_action': profile.recommended_action,
                                })
                        except Exception as e:
                            logger.error(f"WiFi device processing error for {network.get('bssid', '?')}: {e}")

                    # WiFi clients (monitor mode only)
                    try:
                        wifi_clients = _scan_wifi_clients(wifi_interface)
                        for client in wifi_clients:
                            mac = (client.get('mac') or '').upper()
                            if not mac or mac in all_wifi_clients:
                                continue
                            all_wifi_clients[mac] = client

                            rssi_val = client.get('rssi_current')
                            if rssi_val is None:
                                rssi_val = client.get('rssi_median') or client.get('rssi_ema')

                            client_device = {
                                'mac': mac,
                                'vendor': client.get('vendor'),
                                'name': client.get('vendor') or 'WiFi Client',
                                'rssi': rssi_val,
                                'associated_bssid': client.get('associated_bssid'),
                                'probed_ssids': client.get('probed_ssids', []),
                                'probe_count': client.get('probe_count', len(client.get('probed_ssids', []))),
                                'is_client': True,
                            }

                            try:
                                timeline_manager.add_observation(
                                    identifier=mac,
                                    protocol='wifi',
                                    rssi=rssi_val,
                                    name=client_device.get('vendor') or f'WiFi Client {mac[-5:]}',
                                    attributes={'client': True, 'associated_bssid': client_device.get('associated_bssid')}
                                )
                            except Exception as e:
                                logger.debug(f"WiFi client timeline observation error: {e}")
                            _maybe_store_timeline(
                                identifier=mac,
                                protocol='wifi',
                                rssi=rssi_val,
                                attributes={'client': True, 'associated_bssid': client_device.get('associated_bssid')}
                            )

                            profile = correlation.analyze_wifi_device(client_device)
                            client_device['classification'] = profile.risk_level.value
                            client_device['score'] = profile.total_score
                            client_device['score_modifier'] = profile.score_modifier
                            client_device['known_device'] = profile.known_device
                            client_device['known_device_name'] = profile.known_device_name
                            client_device['indicators'] = [
                                {'type': i.type.value, 'desc': i.description}
                                for i in profile.indicators
                            ]
                            client_device['recommended_action'] = profile.recommended_action

                            # Feed to identity engine for MAC-randomization resistant clustering
                            try:
                                wifi_obs = {
                                    'timestamp': datetime.now().isoformat(),
                                    'src_mac': mac,
                                    'bssid': client_device.get('associated_bssid'),
                                    'rssi': rssi_val,
                                    'frame_type': 'probe_request',
                                    'probed_ssids': client_device.get('probed_ssids', []),
                                }
                                ingest_wifi_dict(wifi_obs)
                            except Exception as e:
                                logger.debug(f"Identity engine WiFi client ingest error: {e}")

                            _emit_event('wifi_client', client_device)
                    except Exception as e:
                        logger.debug(f"WiFi client scan error: {e}")
                except Exception as e:
                    last_wifi_scan = current_time
                    logger.error(f"WiFi scan error: {e}")

            # Perform Bluetooth scan
            if bt_enabled and (current_time - last_bt_scan) >= bt_scan_interval:
                try:
                    # Use unified Bluetooth scanner if available
                    if _USE_UNIFIED_BT_SCANNER:
                        logger.info("TSCM: Using unified BT scanner for snapshot")
                        bt_devices = get_tscm_bluetooth_snapshot(duration=8)
                        logger.info(f"TSCM: Unified scanner returned {len(bt_devices)} devices")
                    else:
                        logger.info(f"TSCM: Using legacy BT scanner on {bt_interface}")
                        bt_devices = _scan_bluetooth_devices(bt_interface, duration=8)
                        logger.info(f"TSCM: Legacy scanner returned {len(bt_devices)} devices")
                    last_bt_scan = current_time
                    for device in bt_devices:
                        try:
                            mac = device.get('mac', '')
                            try:
                                rssi_val = int(device.get('rssi', device.get('signal')))
                            except (ValueError, TypeError):
                                rssi_val = None
                            if mac:
                                try:
                                    timeline_manager.add_observation(
                                        identifier=mac,
                                        protocol='bluetooth',
                                        rssi=rssi_val,
                                        name=device.get('name'),
                                        attributes={'device_type': device.get('type')}
                                    )
                                except Exception as e:
                                    logger.debug(f"BT timeline observation error: {e}")
                                _maybe_store_timeline(
                                    identifier=mac,
                                    protocol='bluetooth',
                                    rssi=rssi_val,
                                    attributes={'device_type': device.get('type')}
                                )
                            if mac and mac not in all_bt:
                                all_bt[mac] = device
                                is_threat = False
                                # Analyze for threats
                                threat = detector.analyze_bt_device(device)
                                if threat:
                                    _handle_threat(threat)
                                    threats_found += 1
                                    is_threat = True
                                    sev = threat.get('severity', 'low').lower()
                                    if sev in severity_counts:
                                        severity_counts[sev] += 1
                                # Classify device and get correlation profile
                                classification = detector.classify_bt_device(device)
                                profile = correlation.analyze_bluetooth_device(device)

                                # Feed to identity engine for MAC-randomization resistant clustering
                                try:
                                    ble_obs = {
                                        'timestamp': datetime.now().isoformat(),
                                        'addr': mac,
                                        'rssi': device.get('rssi'),
                                        'manufacturer_id': device.get('manufacturer_id') or device.get('company_id'),
                                        'manufacturer_data': device.get('manufacturer_data'),
                                        'service_uuids': device.get('services', []),
                                        'local_name': device.get('name'),
                                    }
                                    ingest_ble_dict(ble_obs)
                                except Exception as e:
                                    logger.debug(f"Identity engine BLE ingest error: {e}")

                                # Send device to frontend
                                _emit_event('bt_device', {
                                    'mac': mac,
                                    'name': device.get('name', 'Unknown'),
                                    'device_type': device.get('type', ''),
                                    'rssi': device.get('rssi', ''),
                                    'manufacturer': device.get('manufacturer'),
                                    'tracker': device.get('tracker'),
                                    'tracker_type': device.get('tracker_type'),
                                    'is_threat': is_threat,
                                    'is_new': not classification.get('in_baseline', False),
                                    'classification': profile.risk_level.value,
                                    'reasons': classification.get('reasons', []),
                                    'is_audio_capable': classification.get('is_audio_capable', False),
                                    'score': profile.total_score,
                                    'score_modifier': profile.score_modifier,
                                    'known_device': profile.known_device,
                                    'known_device_name': profile.known_device_name,
                                    'indicators': [{'type': i.type.value, 'desc': i.description} for i in profile.indicators],
                                    'recommended_action': profile.recommended_action,
                                })
                        except Exception as e:
                            logger.error(f"BT device processing error for {device.get('mac', '?')}: {e}")
                except Exception as e:
                    last_bt_scan = current_time
                    import traceback
                    logger.error(f"Bluetooth scan error: {e}\n{traceback.format_exc()}")

            # Perform RF scan using SDR
            if rf_enabled and (current_time - last_rf_scan) >= rf_scan_interval:
                try:
                    _emit_event('sweep_progress', {
                        'progress': min(100, int(((current_time - start_time) / duration) * 100)),
                        'status': 'Scanning RF spectrum...',
                        'wifi_count': len(all_wifi),
                        'bt_count': len(all_bt),
                        'rf_count': len(all_rf),
                    })
                    # Try RF scan even if sdr_device is None (will use device 0)
                    rf_signals = _scan_rf_signals(sdr_device, sweep_ranges=preset.get('ranges'))

                    # If no signals and this is first RF scan, send info event
                    if not rf_signals and last_rf_scan == 0:
                        _emit_event('rf_status', {
                            'status': 'no_signals',
                            'message': 'RF scan completed - no signals above threshold. This may be normal in a quiet RF environment.',
                        })

                    for signal in rf_signals:
                        freq_key = f"{signal['frequency']:.3f}"
                        try:
                            power_val = int(float(signal.get('power', signal.get('level'))))
                        except (ValueError, TypeError):
                            power_val = None
                        try:
                            timeline_manager.add_observation(
                                identifier=freq_key,
                                protocol='rf',
                                rssi=power_val,
                                frequency=signal.get('frequency'),
                                name=f"{freq_key} MHz",
                                attributes={'band': signal.get('band')}
                            )
                        except Exception as e:
                            logger.debug(f"RF timeline observation error: {e}")
                        _maybe_store_timeline(
                            identifier=freq_key,
                            protocol='rf',
                            rssi=power_val,
                            frequency=signal.get('frequency'),
                            attributes={'band': signal.get('band')}
                        )
                        if freq_key not in [f"{s['frequency']:.3f}" for s in all_rf]:
                            all_rf.append(signal)
                            is_threat = False
                            # Analyze RF signal for threats
                            threat = detector.analyze_rf_signal(signal)
                            if threat:
                                _handle_threat(threat)
                                threats_found += 1
                                is_threat = True
                                sev = threat.get('severity', 'low').lower()
                                if sev in severity_counts:
                                    severity_counts[sev] += 1
                            # Classify signal and get correlation profile
                            classification = detector.classify_rf_signal(signal)
                            profile = correlation.analyze_rf_signal(signal)
                            # Send signal to frontend
                            _emit_event('rf_signal', {
                                'frequency': signal['frequency'],
                                'power': signal['power'],
                                'band': signal['band'],
                                'signal_strength': signal.get('signal_strength', 0),
                                'is_threat': is_threat,
                                'is_new': not classification.get('in_baseline', False),
                                'classification': profile.risk_level.value,
                                'reasons': classification.get('reasons', []),
                                'score': profile.total_score,
                                'score_modifier': profile.score_modifier,
                                'known_device': profile.known_device,
                                'known_device_name': profile.known_device_name,
                                'indicators': [{'type': i.type.value, 'desc': i.description} for i in profile.indicators],
                                'recommended_action': profile.recommended_action,
                            })
                    last_rf_scan = current_time
                except Exception as e:
                    logger.error(f"RF scan error: {e}")

            # Update progress
            elapsed = time.time() - start_time
            progress = min(100, int((elapsed / duration) * 100))

            _emit_event('sweep_progress', {
                'progress': progress,
                'elapsed': int(elapsed),
                'duration': duration,
                'wifi_count': len(all_wifi),
                'bt_count': len(all_bt),
                'rf_count': len(all_rf),
                'threats_found': threats_found,
                'severity_counts': severity_counts,
            })

            time.sleep(2)  # Update every 2 seconds

        # Complete sweep (run even if stopped by user so correlations/clusters are computed)
        if _current_sweep_id:
            # Run cross-protocol correlation analysis
            correlations = correlation.correlate_devices()
            findings = correlation.get_all_findings()

            # Run baseline comparison if a baseline was provided
            baseline_comparison = None
            if baseline:
                comparator = BaselineComparator(baseline)
                baseline_comparison = comparator.compare_all(
                    wifi_devices=list(all_wifi.values()),
                    wifi_clients=list(all_wifi_clients.values()),
                    bt_devices=list(all_bt.values()),
                    rf_signals=all_rf
                )
                logger.info(
                    f"Baseline comparison: {baseline_comparison['total_new']} new, "
                    f"{baseline_comparison['total_missing']} missing"
                )

            # Finalize identity engine and get MAC-randomization resistant clusters
            identity_engine.finalize_all_sessions()
            identity_summary = identity_engine.get_summary()
            identity_clusters = [c.to_dict() for c in identity_engine.get_clusters()]

            if verbose_results:
                wifi_payload = list(all_wifi.values())
                wifi_client_payload = list(all_wifi_clients.values())
                bt_payload = list(all_bt.values())
                rf_payload = list(all_rf)
            else:
                wifi_payload = [
                    {
                        'bssid': d.get('bssid') or d.get('mac'),
                        'essid': d.get('essid') or d.get('ssid'),
                        'ssid': d.get('ssid') or d.get('essid'),
                        'channel': d.get('channel'),
                        'power': d.get('power', d.get('signal')),
                        'privacy': d.get('privacy', d.get('encryption')),
                        'encryption': d.get('encryption', d.get('privacy')),
                    }
                    for d in all_wifi.values()
                ]
                wifi_client_payload = []
                for client in all_wifi_clients.values():
                    mac = client.get('mac') or client.get('address')
                    if isinstance(mac, str):
                        mac = mac.upper()
                    probed_ssids = client.get('probed_ssids') or []
                    rssi = client.get('rssi')
                    if rssi is None:
                        rssi = client.get('rssi_current')
                    if rssi is None:
                        rssi = client.get('rssi_median')
                    if rssi is None:
                        rssi = client.get('rssi_ema')
                    wifi_client_payload.append({
                        'mac': mac,
                        'vendor': client.get('vendor'),
                        'rssi': rssi,
                        'associated_bssid': client.get('associated_bssid'),
                        'is_associated': client.get('is_associated'),
                        'probed_ssids': probed_ssids,
                        'probe_count': client.get('probe_count', len(probed_ssids)),
                    })
                bt_payload = [
                    {
                        'mac': d.get('mac') or d.get('address'),
                        'name': d.get('name'),
                        'rssi': d.get('rssi'),
                        'manufacturer': d.get('manufacturer', d.get('manufacturer_name')),
                    }
                    for d in all_bt.values()
                ]
                rf_payload = [
                    {
                        'frequency': s.get('frequency'),
                        'power': s.get('power', s.get('level')),
                        'modulation': s.get('modulation'),
                        'band': s.get('band'),
                    }
                    for s in all_rf
                ]

            update_tscm_sweep(
                _current_sweep_id,
                status='completed',
                results={
                    'wifi_devices': wifi_payload,
                    'wifi_clients': wifi_client_payload,
                    'bt_devices': bt_payload,
                    'rf_signals': rf_payload,
                    'wifi_count': len(all_wifi),
                    'wifi_client_count': len(all_wifi_clients),
                    'bt_count': len(all_bt),
                    'rf_count': len(all_rf),
                    'severity_counts': severity_counts,
                    'correlation_summary': findings.get('summary', {}),
                    'identity_summary': identity_summary.get('statistics', {}),
                    'baseline_comparison': baseline_comparison,
                    'results_detail_level': 'full' if verbose_results else 'compact',
                },
                threats_found=threats_found,
                completed=True
            )

            # Emit correlation findings
            _emit_event('correlation_findings', {
                'correlations': correlations,
                'high_interest_count': findings['summary'].get('high_interest', 0),
                'needs_review_count': findings['summary'].get('needs_review', 0),
            })

            # Emit baseline comparison if a baseline was used
            if baseline_comparison:
                _emit_event('baseline_comparison', {
                    'baseline_id': baseline.get('id'),
                    'baseline_name': baseline.get('name'),
                    'total_new': baseline_comparison['total_new'],
                    'total_missing': baseline_comparison['total_missing'],
                    'wifi': baseline_comparison.get('wifi'),
                    'wifi_clients': baseline_comparison.get('wifi_clients'),
                    'bluetooth': baseline_comparison.get('bluetooth'),
                    'rf': baseline_comparison.get('rf'),
                })

            # Emit device identity cluster findings (MAC-randomization resistant)
            _emit_event('identity_clusters', {
                'total_clusters': identity_summary.get('statistics', {}).get('total_clusters', 0),
                'high_risk_count': identity_summary.get('statistics', {}).get('high_risk_count', 0),
                'medium_risk_count': identity_summary.get('statistics', {}).get('medium_risk_count', 0),
                'unique_fingerprints': identity_summary.get('statistics', {}).get('unique_fingerprints', 0),
                'clusters': identity_clusters,
            })

            _emit_event('sweep_completed', {
                'sweep_id': _current_sweep_id,
                'threats_found': threats_found,
                'wifi_count': len(all_wifi),
                'wifi_client_count': len(all_wifi_clients),
                'bt_count': len(all_bt),
                'rf_count': len(all_rf),
                'severity_counts': severity_counts,
                'high_interest_devices': findings['summary'].get('high_interest', 0),
                'needs_review_devices': findings['summary'].get('needs_review', 0),
                'correlations_found': len(correlations),
                'identity_clusters': identity_summary['statistics'].get('total_clusters', 0),
                'baseline_new_devices': baseline_comparison['total_new'] if baseline_comparison else 0,
                'baseline_missing_devices': baseline_comparison['total_missing'] if baseline_comparison else 0,
            })

    except Exception as e:
        logger.error(f"Sweep error: {e}")
        _emit_event('sweep_error', {'error': str(e)})
        if _current_sweep_id:
            update_tscm_sweep(_current_sweep_id, status='error', completed=True)

    finally:
        _sweep_running = False


def _handle_threat(threat: dict) -> None:
    """Handle a detected threat."""
    if not _current_sweep_id:
        return

    # Add to database
    threat_id = add_tscm_threat(
        sweep_id=_current_sweep_id,
        threat_type=threat['threat_type'],
        severity=threat['severity'],
        source=threat['source'],
        identifier=threat['identifier'],
        name=threat.get('name'),
        signal_strength=threat.get('signal_strength'),
        frequency=threat.get('frequency'),
        details=threat.get('details')
    )

    # Emit event
    _emit_event('threat_detected', {
        'threat_id': threat_id,
        **threat
    })

    logger.warning(
        f"TSCM threat detected: {threat['threat_type']} - "
        f"{threat['identifier']} ({threat['severity']})"
    )


# =============================================================================
# Baseline Endpoints
# =============================================================================

@tscm_bp.route('/baseline/record', methods=['POST'])
def record_baseline():
    """Start recording a new baseline."""
    data = request.get_json() or {}
    name = data.get('name', f'Baseline {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    location = data.get('location')
    description = data.get('description')

    baseline_id = _baseline_recorder.start_recording(name, location, description)

    return jsonify({
        'status': 'success',
        'message': 'Baseline recording started',
        'baseline_id': baseline_id
    })


@tscm_bp.route('/baseline/stop', methods=['POST'])
def stop_baseline():
    """Stop baseline recording."""
    result = _baseline_recorder.stop_recording()

    if 'error' in result:
        return jsonify({'status': 'error', 'message': result['error']})

    return jsonify({
        'status': 'success',
        'message': 'Baseline recording complete',
        **result
    })


@tscm_bp.route('/baseline/status')
def baseline_status():
    """Get baseline recording status."""
    return jsonify(_baseline_recorder.get_recording_status())


@tscm_bp.route('/baselines')
def list_baselines():
    """List all baselines."""
    baselines = get_all_tscm_baselines()
    return jsonify({'status': 'success', 'baselines': baselines})


@tscm_bp.route('/baseline/<int:baseline_id>')
def get_baseline(baseline_id: int):
    """Get a specific baseline."""
    baseline = get_tscm_baseline(baseline_id)
    if not baseline:
        return jsonify({'status': 'error', 'message': 'Baseline not found'}), 404

    return jsonify({'status': 'success', 'baseline': baseline})


@tscm_bp.route('/baseline/<int:baseline_id>/activate', methods=['POST'])
def activate_baseline(baseline_id: int):
    """Set a baseline as active."""
    success = set_active_tscm_baseline(baseline_id)
    if not success:
        return jsonify({'status': 'error', 'message': 'Baseline not found'}), 404

    return jsonify({'status': 'success', 'message': 'Baseline activated'})


@tscm_bp.route('/baseline/<int:baseline_id>', methods=['DELETE'])
def remove_baseline(baseline_id: int):
    """Delete a baseline."""
    success = delete_tscm_baseline(baseline_id)
    if not success:
        return jsonify({'status': 'error', 'message': 'Baseline not found'}), 404

    return jsonify({'status': 'success', 'message': 'Baseline deleted'})


@tscm_bp.route('/baseline/active')
def get_active_baseline():
    """Get the currently active baseline."""
    baseline = get_active_tscm_baseline()
    if not baseline:
        return jsonify({'status': 'success', 'baseline': None})

    return jsonify({'status': 'success', 'baseline': baseline})


@tscm_bp.route('/baseline/compare', methods=['POST'])
def compare_against_baseline():
    """
    Compare provided device data against the active baseline.

    Expects JSON body with:
    - wifi_devices: list of WiFi devices (optional)
    - wifi_clients: list of WiFi clients (optional)
    - bt_devices: list of Bluetooth devices (optional)
    - rf_signals: list of RF signals (optional)

    Returns comparison showing new, missing, and matching devices.
    """
    data = request.get_json() or {}

    wifi_devices = data.get('wifi_devices')
    wifi_clients = data.get('wifi_clients')
    bt_devices = data.get('bt_devices')
    rf_signals = data.get('rf_signals')

    # Use the convenience function that gets active baseline
    comparison = get_comparison_for_active_baseline(
        wifi_devices=wifi_devices,
        wifi_clients=wifi_clients,
        bt_devices=bt_devices,
        rf_signals=rf_signals
    )

    if comparison is None:
        return jsonify({
            'status': 'error',
            'message': 'No active baseline set'
        }), 400

    return jsonify({
        'status': 'success',
        'comparison': comparison
    })


# =============================================================================
# Threat Endpoints
# =============================================================================

@tscm_bp.route('/threats')
def list_threats():
    """List threats with optional filters."""
    sweep_id = request.args.get('sweep_id', type=int)
    severity = request.args.get('severity')
    acknowledged = request.args.get('acknowledged')
    limit = request.args.get('limit', 100, type=int)

    ack_filter = None
    if acknowledged is not None:
        ack_filter = acknowledged.lower() in ('true', '1', 'yes')

    threats = get_tscm_threats(
        sweep_id=sweep_id,
        severity=severity,
        acknowledged=ack_filter,
        limit=limit
    )

    return jsonify({'status': 'success', 'threats': threats})


@tscm_bp.route('/threats/summary')
def threat_summary():
    """Get threat count summary by severity."""
    summary = get_tscm_threat_summary()
    return jsonify({'status': 'success', 'summary': summary})


@tscm_bp.route('/threats/<int:threat_id>', methods=['PUT'])
def update_threat(threat_id: int):
    """Update a threat (acknowledge, add notes)."""
    data = request.get_json() or {}

    if data.get('acknowledge'):
        notes = data.get('notes')
        success = acknowledge_tscm_threat(threat_id, notes)
        if not success:
            return jsonify({'status': 'error', 'message': 'Threat not found'}), 404

    return jsonify({'status': 'success', 'message': 'Threat updated'})


# =============================================================================
# Preset Endpoints
# =============================================================================

@tscm_bp.route('/presets')
def list_presets():
    """List available sweep presets."""
    presets = get_all_sweep_presets()
    return jsonify({'status': 'success', 'presets': presets})


@tscm_bp.route('/presets/<preset_name>')
def get_preset(preset_name: str):
    """Get details for a specific preset."""
    preset = get_sweep_preset(preset_name)
    if not preset:
        return jsonify({'status': 'error', 'message': 'Preset not found'}), 404

    return jsonify({'status': 'success', 'preset': preset})


# =============================================================================
# Data Feed Endpoints (for adding data during sweeps/baselines)
# =============================================================================

@tscm_bp.route('/feed/wifi', methods=['POST'])
def feed_wifi():
    """Feed WiFi device data for baseline recording."""
    data = request.get_json()
    if data:
        if data.get('is_client'):
            _baseline_recorder.add_wifi_client(data)
        else:
            _baseline_recorder.add_wifi_device(data)
    return jsonify({'status': 'success'})


@tscm_bp.route('/feed/bluetooth', methods=['POST'])
def feed_bluetooth():
    """Feed Bluetooth device data for baseline recording."""
    data = request.get_json()
    if data:
        _baseline_recorder.add_bt_device(data)
    return jsonify({'status': 'success'})


@tscm_bp.route('/feed/rf', methods=['POST'])
def feed_rf():
    """Feed RF signal data for baseline recording."""
    data = request.get_json()
    if data:
        _baseline_recorder.add_rf_signal(data)
    return jsonify({'status': 'success'})


# =============================================================================
# Correlation & Findings Endpoints
# =============================================================================

@tscm_bp.route('/findings')
def get_findings():
    """
    Get comprehensive TSCM findings from the correlation engine.

    Returns all device profiles organized by risk level, cross-protocol
    correlations, and summary statistics with client-safe disclaimers.
    """
    correlation = get_correlation_engine()
    findings = correlation.get_all_findings()

    # Add client-safe disclaimer
    findings['legal_disclaimer'] = (
        "DISCLAIMER: This TSCM screening system identifies wireless and RF anomalies "
        "and indicators. Results represent potential items of interest, NOT confirmed "
        "surveillance devices. No content has been intercepted or decoded. Findings "
        "require professional analysis and verification. This tool does not prove "
        "malicious intent or illegal activity."
    )

    return jsonify({
        'status': 'success',
        'findings': findings
    })


@tscm_bp.route('/findings/high-interest')
def get_high_interest():
    """Get only high-interest devices (score >= 6)."""
    correlation = get_correlation_engine()
    high_interest = correlation.get_high_interest_devices()

    return jsonify({
        'status': 'success',
        'count': len(high_interest),
        'devices': [d.to_dict() for d in high_interest],
        'disclaimer': (
            "High-interest classification indicates multiple indicators warrant "
            "investigation. This does NOT confirm surveillance activity."
        )
    })


@tscm_bp.route('/findings/correlations')
def get_correlations():
    """Get cross-protocol correlation analysis."""
    correlation = get_correlation_engine()
    correlations = correlation.correlate_devices()

    return jsonify({
        'status': 'success',
        'count': len(correlations),
        'correlations': correlations,
        'explanation': (
            "Correlations identify devices across different protocols (Bluetooth, "
            "WiFi, RF) that exhibit related behavior patterns. Cross-protocol "
            "activity is one indicator among many in TSCM analysis."
        )
    })


@tscm_bp.route('/findings/device/<identifier>')
def get_device_profile(identifier: str):
    """Get detailed profile for a specific device."""
    correlation = get_correlation_engine()

    # Search all protocols for the identifier
    for protocol in ['bluetooth', 'wifi', 'rf']:
        key = f"{protocol}:{identifier}"
        if key in correlation.device_profiles:
            profile = correlation.device_profiles[key]
            return jsonify({
                'status': 'success',
                'profile': profile.to_dict()
            })

    return jsonify({
        'status': 'error',
        'message': 'Device not found'
    }), 404


# =============================================================================
# Meeting Window Endpoints (for time correlation)
# =============================================================================

@tscm_bp.route('/meeting/start', methods=['POST'])
def start_meeting():
    """
    Mark the start of a sensitive period (meeting, briefing, etc.).

    Devices detected during this window will receive additional scoring
    for meeting-correlated activity.
    """
    correlation = get_correlation_engine()
    correlation.start_meeting_window()

    _emit_event('meeting_started', {
        'timestamp': datetime.now().isoformat(),
        'message': 'Sensitive period monitoring active'
    })

    return jsonify({
        'status': 'success',
        'message': 'Meeting window started - devices detected now will be flagged'
    })


@tscm_bp.route('/meeting/end', methods=['POST'])
def end_meeting():
    """Mark the end of a sensitive period."""
    correlation = get_correlation_engine()
    correlation.end_meeting_window()

    _emit_event('meeting_ended', {
        'timestamp': datetime.now().isoformat()
    })

    return jsonify({
        'status': 'success',
        'message': 'Meeting window ended'
    })


@tscm_bp.route('/meeting/status')
def meeting_status():
    """Check if currently in a meeting window."""
    correlation = get_correlation_engine()
    in_meeting = correlation.is_during_meeting()

    return jsonify({
        'status': 'success',
        'in_meeting': in_meeting,
        'windows': [
            {
                'start': start.isoformat(),
                'end': end.isoformat() if end else None
            }
            for start, end in correlation.meeting_windows
        ]
    })


# =============================================================================
# Report Generation Endpoints
# =============================================================================

@tscm_bp.route('/report')
def generate_report():
    """
    Generate a comprehensive TSCM sweep report.

    Includes all findings, correlations, indicators, and recommended actions
    in a client-presentable format with appropriate disclaimers.
    """
    correlation = get_correlation_engine()
    findings = correlation.get_all_findings()

    # Build the report structure
    report = {
        'generated_at': datetime.now().isoformat(),
        'report_type': 'TSCM Wireless Surveillance Screening',

        'executive_summary': {
            'total_devices_analyzed': findings['summary']['total_devices'],
            'high_interest_items': findings['summary']['high_interest'],
            'items_requiring_review': findings['summary']['needs_review'],
            'cross_protocol_correlations': findings['summary']['correlations_found'],
            'assessment': _generate_assessment(findings['summary']),
        },

        'methodology': {
            'protocols_scanned': ['Bluetooth Low Energy', 'WiFi 802.11', 'RF Spectrum'],
            'analysis_techniques': [
                'Device fingerprinting',
                'Signal stability analysis',
                'Cross-protocol correlation',
                'Time-based pattern detection',
                'Manufacturer identification',
            ],
            'scoring_model': {
                'informational': '0-2 points - Known or expected devices',
                'needs_review': '3-5 points - Unusual devices requiring assessment',
                'high_interest': '6+ points - Multiple indicators warrant investigation',
            }
        },

        'findings': {
            'high_interest': findings['devices']['high_interest'],
            'needs_review': findings['devices']['needs_review'],
            'informational': findings['devices']['informational'],
        },

        'correlations': findings['correlations'],

        'disclaimers': {
            'legal': (
                "This report documents findings from a wireless and RF surveillance "
                "screening. Results indicate anomalies and items of interest, NOT "
                "confirmed surveillance devices. No communications content has been "
                "intercepted, recorded, or decoded. This screening does not prove "
                "malicious intent, illegal activity, or the presence of surveillance "
                "equipment. All findings require professional verification."
            ),
            'technical': (
                "Detection capabilities are limited by equipment sensitivity, "
                "environmental factors, and the technical sophistication of any "
                "potential devices. Absence of findings does NOT guarantee absence "
                "of surveillance equipment."
            ),
            'recommendations': (
                "High-interest items should be investigated by qualified TSCM "
                "professionals using appropriate physical inspection techniques. "
                "This electronic sweep is one component of comprehensive TSCM."
            )
        }
    }

    return jsonify({
        'status': 'success',
        'report': report
    })


def _generate_assessment(summary: dict) -> str:
    """Generate an assessment summary based on findings."""
    high = summary.get('high_interest', 0)
    review = summary.get('needs_review', 0)
    correlations = summary.get('correlations_found', 0)

    if high > 0 or correlations > 0:
        return (
            f"ELEVATED CONCERN: {high} high-interest item(s) and "
            f"{correlations} cross-protocol correlation(s) detected. "
            "Professional TSCM inspection recommended."
        )
    elif review > 3:
        return (
            f"MODERATE CONCERN: {review} items requiring review. "
            "Further analysis recommended to characterize unknown devices."
        )
    elif review > 0:
        return (
            f"LOW CONCERN: {review} item(s) flagged for review. "
            "Likely benign but verification recommended."
        )
    else:
        return (
            "BASELINE ENVIRONMENT: No significant anomalies detected. "
            "Environment appears consistent with expected wireless activity."
        )


# =============================================================================
# Device Identity Endpoints (MAC-Randomization Resistant Detection)
# =============================================================================

@tscm_bp.route('/identity/ingest/ble', methods=['POST'])
def ingest_ble_observation():
    """
    Ingest a BLE observation for device identity clustering.

    This endpoint accepts BLE advertisement data and feeds it into the
    MAC-randomization resistant device detection engine.

    Expected JSON payload:
    {
        "timestamp": "2024-01-01T12:00:00",  // ISO format or omit for now
        "addr": "AA:BB:CC:DD:EE:FF",         // BLE address (may be randomized)
        "addr_type": "rpa",                   // public/random_static/rpa/nrpa/unknown
        "rssi": -65,                          // dBm
        "tx_power": -10,                      // dBm (optional)
        "adv_type": "ADV_IND",               // Advertisement type
        "manufacturer_id": 1234,              // Company ID (optional)
        "manufacturer_data": "0102030405",   // Hex string (optional)
        "service_uuids": ["uuid1", "uuid2"], // List of UUIDs (optional)
        "local_name": "Device Name",          // Advertised name (optional)
        "appearance": 960,                    // BLE appearance (optional)
        "packet_length": 31                   // Total packet length (optional)
    }
    """
    try:
        from utils.tscm.device_identity import ingest_ble_dict

        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        session = ingest_ble_dict(data)

        return jsonify({
            'status': 'success',
            'session_id': session.session_id,
            'observation_count': len(session.observations),
        })

    except Exception as e:
        logger.error(f"BLE ingestion error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/ingest/wifi', methods=['POST'])
def ingest_wifi_observation():
    """
    Ingest a WiFi observation for device identity clustering.

    Expected JSON payload:
    {
        "timestamp": "2024-01-01T12:00:00",
        "src_mac": "AA:BB:CC:DD:EE:FF",       // Client MAC (may be randomized)
        "dst_mac": "11:22:33:44:55:66",       // Destination MAC
        "bssid": "11:22:33:44:55:66",         // AP BSSID
        "ssid": "NetworkName",                 // SSID if available
        "frame_type": "probe_request",        // Frame type
        "rssi": -70,                          // dBm
        "channel": 6,                         // WiFi channel
        "ht_capable": true,                   // 802.11n capable
        "vht_capable": true,                  // 802.11ac capable
        "he_capable": false,                  // 802.11ax capable
        "supported_rates": [1, 2, 5.5, 11],  // Supported rates
        "vendor_ies": [["001122", 10]],      // [(OUI, length), ...]
        "probed_ssids": ["ssid1", "ssid2"]   // For probe requests
    }
    """
    try:
        from utils.tscm.device_identity import ingest_wifi_dict

        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        session = ingest_wifi_dict(data)

        return jsonify({
            'status': 'success',
            'session_id': session.session_id,
            'observation_count': len(session.observations),
        })

    except Exception as e:
        logger.error(f"WiFi ingestion error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/ingest/batch', methods=['POST'])
def ingest_batch_observations():
    """
    Ingest multiple observations in a single request.

    Expected JSON payload:
    {
        "ble": [<ble_observation>, ...],
        "wifi": [<wifi_observation>, ...]
    }
    """
    try:
        from utils.tscm.device_identity import ingest_ble_dict, ingest_wifi_dict

        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        ble_count = 0
        wifi_count = 0

        for ble_obs in data.get('ble', []):
            ingest_ble_dict(ble_obs)
            ble_count += 1

        for wifi_obs in data.get('wifi', []):
            ingest_wifi_dict(wifi_obs)
            wifi_count += 1

        return jsonify({
            'status': 'success',
            'ble_ingested': ble_count,
            'wifi_ingested': wifi_count,
        })

    except Exception as e:
        logger.error(f"Batch ingestion error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/clusters')
def get_device_clusters():
    """
    Get all device clusters (probable physical device identities).

    Query parameters:
    - min_confidence: Minimum cluster confidence (0-1, default 0)
    - protocol: Filter by protocol ('ble' or 'wifi')
    - risk_level: Filter by risk level ('high', 'medium', 'low', 'informational')
    """
    try:
        from utils.tscm.device_identity import get_identity_engine

        engine = get_identity_engine()
        min_conf = request.args.get('min_confidence', 0, type=float)
        protocol = request.args.get('protocol')
        risk_filter = request.args.get('risk_level')

        clusters = engine.get_clusters(min_confidence=min_conf)

        if protocol:
            clusters = [c for c in clusters if c.protocol == protocol]

        if risk_filter:
            clusters = [c for c in clusters if c.risk_level.value == risk_filter]

        return jsonify({
            'status': 'success',
            'count': len(clusters),
            'clusters': [c.to_dict() for c in clusters],
            'disclaimer': (
                "Clusters represent PROBABLE device identities based on passive "
                "fingerprinting. Results are statistical correlations, not "
                "confirmed matches. False positives/negatives are expected."
            )
        })

    except Exception as e:
        logger.error(f"Get clusters error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/clusters/high-risk')
def get_high_risk_clusters():
    """Get device clusters with HIGH risk level."""
    try:
        from utils.tscm.device_identity import get_identity_engine

        engine = get_identity_engine()
        clusters = engine.get_high_risk_clusters()

        return jsonify({
            'status': 'success',
            'count': len(clusters),
            'clusters': [c.to_dict() for c in clusters],
            'disclaimer': (
                "High-risk classification indicates multiple behavioral indicators "
                "consistent with potential surveillance devices. This does NOT "
                "confirm surveillance activity. Professional verification required."
            )
        })

    except Exception as e:
        logger.error(f"Get high-risk clusters error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/summary')
def get_identity_summary():
    """
    Get summary of device identity analysis.

    Returns statistics, cluster counts by risk level, and monitoring period.
    """
    try:
        from utils.tscm.device_identity import get_identity_engine

        engine = get_identity_engine()
        summary = engine.get_summary()

        return jsonify({
            'status': 'success',
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Get identity summary error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/finalize', methods=['POST'])
def finalize_identity_sessions():
    """
    Finalize all active sessions and complete clustering.

    Call this at the end of a monitoring period to ensure all observations
    are properly clustered and assessed.
    """
    try:
        from utils.tscm.device_identity import get_identity_engine

        engine = get_identity_engine()
        engine.finalize_all_sessions()
        summary = engine.get_summary()

        return jsonify({
            'status': 'success',
            'message': 'All sessions finalized',
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Finalize sessions error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/reset', methods=['POST'])
def reset_identity_engine():
    """
    Reset the device identity engine.

    Clears all sessions, clusters, and monitoring state.
    """
    try:
        from utils.tscm.device_identity import reset_identity_engine as reset_engine

        reset_engine()

        return jsonify({
            'status': 'success',
            'message': 'Device identity engine reset'
        })

    except Exception as e:
        logger.error(f"Reset identity engine error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/identity/cluster/<cluster_id>')
def get_cluster_detail(cluster_id: str):
    """Get detailed information for a specific cluster."""
    try:
        from utils.tscm.device_identity import get_identity_engine

        engine = get_identity_engine()

        if cluster_id not in engine.clusters:
            return jsonify({
                'status': 'error',
                'message': 'Cluster not found'
            }), 404

        cluster = engine.clusters[cluster_id]

        return jsonify({
            'status': 'success',
            'cluster': cluster.to_dict()
        })

    except Exception as e:
        logger.error(f"Get cluster detail error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Capabilities & Coverage Endpoints
# =============================================================================

@tscm_bp.route('/capabilities')
def get_capabilities():
    """
    Get current system capabilities for TSCM sweeping.

    Returns what the system CAN and CANNOT detect based on OS,
    privileges, adapters, and SDR hardware.
    """
    try:
        from utils.tscm.advanced import detect_sweep_capabilities

        wifi_interface = request.args.get('wifi_interface', '')
        bt_adapter = request.args.get('bt_adapter', '')

        caps = detect_sweep_capabilities(
            wifi_interface=wifi_interface,
            bt_adapter=bt_adapter
        )

        return jsonify({
            'status': 'success',
            'capabilities': caps.to_dict()
        })

    except Exception as e:
        logger.error(f"Get capabilities error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/sweep/<int:sweep_id>/capabilities')
def get_sweep_stored_capabilities(sweep_id: int):
    """Get stored capabilities for a specific sweep."""
    from utils.database import get_sweep_capabilities

    caps = get_sweep_capabilities(sweep_id)
    if not caps:
        return jsonify({'status': 'error', 'message': 'No capabilities stored for this sweep'}), 404

    return jsonify({
        'status': 'success',
        'capabilities': caps
    })


# =============================================================================
# Baseline Diff & Health Endpoints
# =============================================================================

@tscm_bp.route('/baseline/diff/<int:baseline_id>/<int:sweep_id>')
def get_baseline_diff(baseline_id: int, sweep_id: int):
    """
    Get comprehensive diff between a baseline and a sweep.

    Shows new devices, missing devices, changed characteristics,
    and baseline health assessment.
    """
    try:
        from utils.tscm.advanced import calculate_baseline_diff

        baseline = get_tscm_baseline(baseline_id)
        if not baseline:
            return jsonify({'status': 'error', 'message': 'Baseline not found'}), 404

        sweep = get_tscm_sweep(sweep_id)
        if not sweep:
            return jsonify({'status': 'error', 'message': 'Sweep not found'}), 404

        # Get current devices from sweep results
        results = sweep.get('results', {})
        if isinstance(results, str):
            import json
            results = json.loads(results)

        current_wifi = results.get('wifi_devices', [])
        current_wifi_clients = results.get('wifi_clients', [])
        current_bt = results.get('bt_devices', [])
        current_rf = results.get('rf_signals', [])

        diff = calculate_baseline_diff(
            baseline=baseline,
            current_wifi=current_wifi,
            current_wifi_clients=current_wifi_clients,
            current_bt=current_bt,
            current_rf=current_rf,
            sweep_id=sweep_id
        )

        return jsonify({
            'status': 'success',
            'diff': diff.to_dict()
        })

    except Exception as e:
        logger.error(f"Get baseline diff error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/baseline/<int:baseline_id>/health')
def get_baseline_health(baseline_id: int):
    """Get health assessment for a baseline."""
    try:
        from utils.tscm.advanced import BaselineHealth
        from datetime import datetime

        baseline = get_tscm_baseline(baseline_id)
        if not baseline:
            return jsonify({'status': 'error', 'message': 'Baseline not found'}), 404

        # Calculate age
        created_at = baseline.get('created_at')
        age_hours = 0
        if created_at:
            if isinstance(created_at, str):
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                age_hours = (datetime.now() - created.replace(tzinfo=None)).total_seconds() / 3600
            elif isinstance(created_at, datetime):
                age_hours = (datetime.now() - created_at).total_seconds() / 3600

        # Count devices
        total_devices = (
            len(baseline.get('wifi_networks', [])) +
            len(baseline.get('bt_devices', [])) +
            len(baseline.get('rf_frequencies', []))
        )

        # Determine health
        health = 'healthy'
        score = 1.0
        reasons = []

        if age_hours > 168:
            health = 'stale'
            score = 0.3
            reasons.append(f'Baseline is {age_hours:.0f} hours old (over 1 week)')
        elif age_hours > 72:
            health = 'noisy'
            score = 0.6
            reasons.append(f'Baseline is {age_hours:.0f} hours old (over 3 days)')

        if total_devices < 3:
            score -= 0.2
            reasons.append(f'Baseline has few devices ({total_devices})')
            if health == 'healthy':
                health = 'noisy'

        return jsonify({
            'status': 'success',
            'health': {
                'status': health,
                'score': round(max(0, score), 2),
                'age_hours': round(age_hours, 1),
                'total_devices': total_devices,
                'reasons': reasons,
            }
        })

    except Exception as e:
        logger.error(f"Get baseline health error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Device Timeline Endpoints
# =============================================================================

@tscm_bp.route('/device/<identifier>/timeline')
def get_device_timeline_endpoint(identifier: str):
    """
    Get timeline of observations for a device.

    Shows behavior over time including RSSI stability, presence,
    and meeting window correlation.
    """
    try:
        from utils.tscm.advanced import get_timeline_manager
        from utils.database import get_device_timeline

        protocol = request.args.get('protocol', 'bluetooth')
        since_hours = request.args.get('since_hours', 24, type=int)

        # Try in-memory timeline first
        manager = get_timeline_manager()
        timeline = manager.get_timeline(identifier, protocol)

        # Also get stored timeline from database
        stored = get_device_timeline(identifier, since_hours=since_hours)

        result = {
            'identifier': identifier,
            'protocol': protocol,
            'observations': stored,
        }

        if timeline:
            result['metrics'] = {
                'first_seen': timeline.first_seen.isoformat() if timeline.first_seen else None,
                'last_seen': timeline.last_seen.isoformat() if timeline.last_seen else None,
                'total_observations': timeline.total_observations,
                'presence_ratio': round(timeline.presence_ratio, 2),
            }
            result['signal'] = {
                'rssi_min': timeline.rssi_min,
                'rssi_max': timeline.rssi_max,
                'rssi_mean': round(timeline.rssi_mean, 1) if timeline.rssi_mean else None,
                'stability': round(timeline.rssi_stability, 2),
            }
            result['movement'] = {
                'appears_stationary': timeline.appears_stationary,
                'pattern': timeline.movement_pattern,
            }
            result['meeting_correlation'] = {
                'correlated': timeline.meeting_correlated,
                'observations_during_meeting': timeline.meeting_observations,
            }

        return jsonify({
            'status': 'success',
            'timeline': result
        })

    except Exception as e:
        logger.error(f"Get device timeline error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/timelines')
def get_all_device_timelines():
    """Get all device timelines."""
    try:
        from utils.tscm.advanced import get_timeline_manager

        manager = get_timeline_manager()
        timelines = manager.get_all_timelines()

        return jsonify({
            'status': 'success',
            'count': len(timelines),
            'timelines': [t.to_dict() for t in timelines]
        })

    except Exception as e:
        logger.error(f"Get all timelines error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Known-Good Registry (Whitelist) Endpoints
# =============================================================================

@tscm_bp.route('/known-devices', methods=['GET'])
def list_known_devices():
    """List all known-good devices."""
    from utils.database import get_all_known_devices

    location = request.args.get('location')
    scope = request.args.get('scope')

    devices = get_all_known_devices(location=location, scope=scope)

    return jsonify({
        'status': 'success',
        'count': len(devices),
        'devices': devices
    })


@tscm_bp.route('/known-devices', methods=['POST'])
def add_known_device_endpoint():
    """
    Add a device to the known-good registry.

    Known devices remain visible but receive reduced risk scores.
    They are NOT suppressed from reports (preserves audit trail).
    """
    from utils.database import add_known_device

    data = request.get_json() or {}

    identifier = data.get('identifier')
    protocol = data.get('protocol')

    if not identifier or not protocol:
        return jsonify({
            'status': 'error',
            'message': 'identifier and protocol are required'
        }), 400

    device_id = add_known_device(
        identifier=identifier,
        protocol=protocol,
        name=data.get('name'),
        description=data.get('description'),
        location=data.get('location'),
        scope=data.get('scope', 'global'),
        added_by=data.get('added_by'),
        score_modifier=data.get('score_modifier', -2),
        metadata=data.get('metadata')
    )

    return jsonify({
        'status': 'success',
        'message': 'Device added to known-good registry',
        'device_id': device_id
    })


@tscm_bp.route('/known-devices/<identifier>', methods=['GET'])
def get_known_device_endpoint(identifier: str):
    """Get a known device by identifier."""
    from utils.database import get_known_device

    device = get_known_device(identifier)
    if not device:
        return jsonify({'status': 'error', 'message': 'Device not found'}), 404

    return jsonify({
        'status': 'success',
        'device': device
    })


@tscm_bp.route('/known-devices/<identifier>', methods=['DELETE'])
def delete_known_device_endpoint(identifier: str):
    """Remove a device from the known-good registry."""
    from utils.database import delete_known_device

    success = delete_known_device(identifier)
    if not success:
        return jsonify({'status': 'error', 'message': 'Device not found'}), 404

    return jsonify({
        'status': 'success',
        'message': 'Device removed from known-good registry'
    })


@tscm_bp.route('/known-devices/check/<identifier>')
def check_known_device(identifier: str):
    """Check if a device is in the known-good registry."""
    from utils.database import is_known_good_device

    location = request.args.get('location')
    result = is_known_good_device(identifier, location=location)

    return jsonify({
        'status': 'success',
        'is_known': result is not None,
        'details': result
    })


# =============================================================================
# Case Management Endpoints
# =============================================================================

@tscm_bp.route('/cases', methods=['GET'])
def list_cases():
    """List all TSCM cases."""
    from utils.database import get_all_tscm_cases

    status = request.args.get('status')
    limit = request.args.get('limit', 50, type=int)

    cases = get_all_tscm_cases(status=status, limit=limit)

    return jsonify({
        'status': 'success',
        'count': len(cases),
        'cases': cases
    })


@tscm_bp.route('/cases', methods=['POST'])
def create_case():
    """Create a new TSCM case."""
    from utils.database import create_tscm_case

    data = request.get_json() or {}

    name = data.get('name')
    if not name:
        return jsonify({'status': 'error', 'message': 'name is required'}), 400

    case_id = create_tscm_case(
        name=name,
        description=data.get('description'),
        location=data.get('location'),
        priority=data.get('priority', 'normal'),
        created_by=data.get('created_by'),
        metadata=data.get('metadata')
    )

    return jsonify({
        'status': 'success',
        'message': 'Case created',
        'case_id': case_id
    })


@tscm_bp.route('/cases/<int:case_id>', methods=['GET'])
def get_case(case_id: int):
    """Get a TSCM case with all linked sweeps, threats, and notes."""
    from utils.database import get_tscm_case

    case = get_tscm_case(case_id)
    if not case:
        return jsonify({'status': 'error', 'message': 'Case not found'}), 404

    return jsonify({
        'status': 'success',
        'case': case
    })


@tscm_bp.route('/cases/<int:case_id>', methods=['PUT'])
def update_case(case_id: int):
    """Update a TSCM case."""
    from utils.database import update_tscm_case

    data = request.get_json() or {}

    success = update_tscm_case(
        case_id=case_id,
        status=data.get('status'),
        priority=data.get('priority'),
        assigned_to=data.get('assigned_to'),
        notes=data.get('notes')
    )

    if not success:
        return jsonify({'status': 'error', 'message': 'Case not found'}), 404

    return jsonify({
        'status': 'success',
        'message': 'Case updated'
    })


@tscm_bp.route('/cases/<int:case_id>/sweeps/<int:sweep_id>', methods=['POST'])
def link_sweep_to_case(case_id: int, sweep_id: int):
    """Link a sweep to a case."""
    from utils.database import add_sweep_to_case

    success = add_sweep_to_case(case_id, sweep_id)

    return jsonify({
        'status': 'success' if success else 'error',
        'message': 'Sweep linked to case' if success else 'Already linked or not found'
    })


@tscm_bp.route('/cases/<int:case_id>/threats/<int:threat_id>', methods=['POST'])
def link_threat_to_case(case_id: int, threat_id: int):
    """Link a threat to a case."""
    from utils.database import add_threat_to_case

    success = add_threat_to_case(case_id, threat_id)

    return jsonify({
        'status': 'success' if success else 'error',
        'message': 'Threat linked to case' if success else 'Already linked or not found'
    })


@tscm_bp.route('/cases/<int:case_id>/notes', methods=['POST'])
def add_note_to_case(case_id: int):
    """Add a note to a case."""
    from utils.database import add_case_note

    data = request.get_json() or {}

    content = data.get('content')
    if not content:
        return jsonify({'status': 'error', 'message': 'content is required'}), 400

    note_id = add_case_note(
        case_id=case_id,
        content=content,
        note_type=data.get('note_type', 'general'),
        created_by=data.get('created_by')
    )

    return jsonify({
        'status': 'success',
        'message': 'Note added',
        'note_id': note_id
    })


# =============================================================================
# Meeting Window Enhanced Endpoints
# =============================================================================

@tscm_bp.route('/meeting/start-tracked', methods=['POST'])
def start_tracked_meeting():
    """
    Start a tracked meeting window with database persistence.

    Tracks devices first seen during meeting and behavior changes.
    """
    from utils.database import start_meeting_window
    from utils.tscm.advanced import get_timeline_manager

    data = request.get_json() or {}

    meeting_id = start_meeting_window(
        sweep_id=_current_sweep_id,
        name=data.get('name'),
        location=data.get('location'),
        notes=data.get('notes')
    )

    # Start meeting in correlation engine
    correlation = get_correlation_engine()
    correlation.start_meeting_window()

    # Start in timeline manager
    manager = get_timeline_manager()
    manager.start_meeting_window()

    _emit_event('meeting_started', {
        'meeting_id': meeting_id,
        'timestamp': datetime.now().isoformat(),
        'name': data.get('name'),
    })

    return jsonify({
        'status': 'success',
        'message': 'Tracked meeting window started',
        'meeting_id': meeting_id
    })


@tscm_bp.route('/meeting/<int:meeting_id>/end', methods=['POST'])
def end_tracked_meeting(meeting_id: int):
    """End a tracked meeting window."""
    from utils.database import end_meeting_window
    from utils.tscm.advanced import get_timeline_manager

    success = end_meeting_window(meeting_id)
    if not success:
        return jsonify({'status': 'error', 'message': 'Meeting not found or already ended'}), 404

    # End in correlation engine
    correlation = get_correlation_engine()
    correlation.end_meeting_window()

    # End in timeline manager
    manager = get_timeline_manager()
    manager.end_meeting_window()

    _emit_event('meeting_ended', {
        'meeting_id': meeting_id,
        'timestamp': datetime.now().isoformat()
    })

    return jsonify({
        'status': 'success',
        'message': 'Meeting window ended'
    })


@tscm_bp.route('/meeting/<int:meeting_id>/summary')
def get_meeting_summary_endpoint(meeting_id: int):
    """Get detailed summary of device activity during a meeting."""
    try:
        from utils.database import get_meeting_windows
        from utils.tscm.advanced import generate_meeting_summary, get_timeline_manager

        # Get meeting window
        windows = get_meeting_windows(_current_sweep_id or 0)
        meeting = None
        for w in windows:
            if w.get('id') == meeting_id:
                meeting = w
                break

        if not meeting:
            return jsonify({'status': 'error', 'message': 'Meeting not found'}), 404

        # Get timelines and profiles
        manager = get_timeline_manager()
        timelines = manager.get_all_timelines()

        correlation = get_correlation_engine()
        profiles = [p.to_dict() for p in correlation.device_profiles.values()]

        summary = generate_meeting_summary(meeting, timelines, profiles)

        return jsonify({
            'status': 'success',
            'summary': summary.to_dict()
        })

    except Exception as e:
        logger.error(f"Get meeting summary error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/meeting/active')
def get_active_meeting():
    """Get currently active meeting window."""
    from utils.database import get_active_meeting_window

    meeting = get_active_meeting_window(_current_sweep_id)

    return jsonify({
        'status': 'success',
        'meeting': meeting,
        'is_active': meeting is not None
    })


# =============================================================================
# PDF Report & Technical Annex Endpoints
# =============================================================================

@tscm_bp.route('/report/pdf')
def get_pdf_report():
    """
    Generate client-safe PDF report.

    Contains executive summary, findings by risk tier, meeting window
    summary, and mandatory disclaimers.
    """
    try:
        from utils.tscm.reports import generate_report, get_pdf_report
        from utils.tscm.advanced import detect_sweep_capabilities, get_timeline_manager

        sweep_id = request.args.get('sweep_id', _current_sweep_id, type=int)
        if not sweep_id:
            return jsonify({'status': 'error', 'message': 'No sweep specified'}), 400

        sweep = get_tscm_sweep(sweep_id)
        if not sweep:
            return jsonify({'status': 'error', 'message': 'Sweep not found'}), 404

        # Get data for report
        correlation = get_correlation_engine()
        profiles = [p.to_dict() for p in correlation.device_profiles.values()]
        caps = detect_sweep_capabilities().to_dict()

        manager = get_timeline_manager()
        timelines = [t.to_dict() for t in manager.get_all_timelines()]

        # Generate report
        report = generate_report(
            sweep_id=sweep_id,
            sweep_data=sweep,
            device_profiles=profiles,
            capabilities=caps,
            timelines=timelines
        )

        pdf_content = get_pdf_report(report)

        return Response(
            pdf_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=tscm_report_{sweep_id}.txt'
            }
        )

    except Exception as e:
        logger.error(f"Generate PDF report error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/report/annex')
def get_technical_annex():
    """
    Generate technical annex (JSON + CSV).

    Contains device timelines, all indicators, and detailed data
    for audit purposes. No packet data included.
    """
    try:
        from utils.tscm.reports import generate_report, get_json_annex, get_csv_annex
        from utils.tscm.advanced import detect_sweep_capabilities, get_timeline_manager

        sweep_id = request.args.get('sweep_id', _current_sweep_id, type=int)
        format_type = request.args.get('format', 'json')

        if not sweep_id:
            return jsonify({'status': 'error', 'message': 'No sweep specified'}), 400

        sweep = get_tscm_sweep(sweep_id)
        if not sweep:
            return jsonify({'status': 'error', 'message': 'Sweep not found'}), 404

        # Get data for report
        correlation = get_correlation_engine()
        profiles = [p.to_dict() for p in correlation.device_profiles.values()]
        caps = detect_sweep_capabilities().to_dict()

        manager = get_timeline_manager()
        timelines = [t.to_dict() for t in manager.get_all_timelines()]

        # Generate report
        report = generate_report(
            sweep_id=sweep_id,
            sweep_data=sweep,
            device_profiles=profiles,
            capabilities=caps,
            timelines=timelines
        )

        if format_type == 'csv':
            csv_content = get_csv_annex(report)
            return Response(
                csv_content,
                mimetype='text/csv',
                headers={
                    'Content-Disposition': f'attachment; filename=tscm_annex_{sweep_id}.csv'
                }
            )
        else:
            annex = get_json_annex(report)
            return jsonify({
                'status': 'success',
                'annex': annex
            })

    except Exception as e:
        logger.error(f"Generate technical annex error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# WiFi Advanced Indicators Endpoints
# =============================================================================

@tscm_bp.route('/wifi/advanced-indicators')
def get_wifi_advanced_indicators():
    """
    Get advanced WiFi indicators (Evil Twin, Probes, Deauth).

    These indicators require analysis of WiFi patterns.
    Some features require monitor mode.
    """
    try:
        from utils.tscm.advanced import get_wifi_detector

        detector = get_wifi_detector()

        return jsonify({
            'status': 'success',
            'indicators': detector.get_all_indicators(),
            'unavailable_features': detector.get_unavailable_features(),
            'disclaimer': (
                "All indicators represent pattern detections, NOT confirmed attacks. "
                "Further investigation is required."
            )
        })

    except Exception as e:
        logger.error(f"Get WiFi indicators error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/wifi/analyze-network', methods=['POST'])
def analyze_wifi_network():
    """
    Analyze a WiFi network for evil twin patterns.

    Compares against known networks to detect SSID spoofing.
    """
    try:
        from utils.tscm.advanced import get_wifi_detector

        data = request.get_json() or {}
        detector = get_wifi_detector()

        # Set known networks from baseline if available
        baseline = get_active_tscm_baseline()
        if baseline:
            detector.set_known_networks(baseline.get('wifi_networks', []))

        indicators = detector.analyze_network(data)

        return jsonify({
            'status': 'success',
            'indicators': [i.to_dict() for i in indicators]
        })

    except Exception as e:
        logger.error(f"Analyze WiFi network error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Bluetooth Risk Explainability Endpoints
# =============================================================================

@tscm_bp.route('/bluetooth/<identifier>/explain')
def explain_bluetooth_risk(identifier: str):
    """
    Get human-readable risk explanation for a BLE device.

    Includes proximity estimate, tracker explanation, and
    recommended actions.
    """
    try:
        from utils.tscm.advanced import generate_ble_risk_explanation

        # Get device from correlation engine
        correlation = get_correlation_engine()
        profile = None
        key = f"bluetooth:{identifier.upper()}"
        if key in correlation.device_profiles:
            profile = correlation.device_profiles[key].to_dict()

        # Try to find device info
        device = {'mac': identifier}
        if profile:
            device['name'] = profile.get('name')
            device['rssi'] = profile.get('rssi_samples', [None])[-1] if profile.get('rssi_samples') else None

        # Check meeting status
        is_meeting = correlation.is_during_meeting()

        explanation = generate_ble_risk_explanation(device, profile, is_meeting)

        return jsonify({
            'status': 'success',
            'explanation': explanation.to_dict()
        })

    except Exception as e:
        logger.error(f"Explain BLE risk error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/bluetooth/<identifier>/proximity')
def get_bluetooth_proximity(identifier: str):
    """Get proximity estimate for a BLE device."""
    try:
        from utils.tscm.advanced import estimate_ble_proximity

        rssi = request.args.get('rssi', type=int)
        if rssi is None:
            # Try to get from correlation engine
            correlation = get_correlation_engine()
            key = f"bluetooth:{identifier.upper()}"
            if key in correlation.device_profiles:
                profile = correlation.device_profiles[key]
                if profile.rssi_samples:
                    rssi = profile.rssi_samples[-1]

        if rssi is None:
            return jsonify({
                'status': 'error',
                'message': 'RSSI value required'
            }), 400

        proximity, explanation, distance = estimate_ble_proximity(rssi)

        return jsonify({
            'status': 'success',
            'proximity': {
                'estimate': proximity.value,
                'explanation': explanation,
                'estimated_distance': distance,
                'rssi_used': rssi,
            },
            'disclaimer': (
                "Proximity estimates are approximate and affected by "
                "environment, obstacles, and device characteristics."
            )
        })

    except Exception as e:
        logger.error(f"Get BLE proximity error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Operator Playbook Endpoints
# =============================================================================

@tscm_bp.route('/playbooks')
def list_playbooks():
    """List all available operator playbooks."""
    try:
        from utils.tscm.advanced import PLAYBOOKS

        # Return as array with id field for JavaScript compatibility
        playbooks_list = []
        for pid, pb in PLAYBOOKS.items():
            pb_dict = pb.to_dict()
            pb_dict['id'] = pid
            pb_dict['name'] = pb_dict.get('title', pid)
            pb_dict['category'] = pb_dict.get('risk_level', 'general')
            playbooks_list.append(pb_dict)

        return jsonify({
            'status': 'success',
            'playbooks': playbooks_list
        })

    except Exception as e:
        logger.error(f"List playbooks error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/playbooks/<playbook_id>')
def get_playbook(playbook_id: str):
    """Get a specific playbook."""
    try:
        from utils.tscm.advanced import PLAYBOOKS

        if playbook_id not in PLAYBOOKS:
            return jsonify({'status': 'error', 'message': 'Playbook not found'}), 404

        return jsonify({
            'status': 'success',
            'playbook': PLAYBOOKS[playbook_id].to_dict()
        })

    except Exception as e:
        logger.error(f"Get playbook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tscm_bp.route('/findings/<identifier>/playbook')
def get_finding_playbook(identifier: str):
    """Get recommended playbook for a specific finding."""
    try:
        from utils.tscm.advanced import get_playbook_for_finding

        # Get profile
        correlation = get_correlation_engine()
        profile = None

        for protocol in ['bluetooth', 'wifi', 'rf']:
            key = f"{protocol}:{identifier.upper()}"
            if key in correlation.device_profiles:
                profile = correlation.device_profiles[key].to_dict()
                break

        if not profile:
            return jsonify({'status': 'error', 'message': 'Finding not found'}), 404

        playbook = get_playbook_for_finding(
            risk_level=profile.get('risk_level', 'informational'),
            indicators=profile.get('indicators', [])
        )

        return jsonify({
            'status': 'success',
            'playbook': playbook.to_dict(),
            'suggested_next_steps': [
                f"Step {s.step_number}: {s.action}"
                for s in playbook.steps[:3]
            ]
        })

    except Exception as e:
        logger.error(f"Get finding playbook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
