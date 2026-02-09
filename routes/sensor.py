"""RTL_433 sensor monitoring routes."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from datetime import datetime
from typing import Generator

from flask import Blueprint, jsonify, request, Response

import app as app_module
from utils.logging import sensor_logger as logger
from utils.validation import (
    validate_frequency, validate_device_index, validate_gain, validate_ppm,
    validate_rtl_tcp_host, validate_rtl_tcp_port
)
from utils.sse import format_sse
from utils.event_pipeline import process_event
from utils.process import safe_terminate, register_process, unregister_process
from utils.sdr import SDRFactory, SDRType
from utils.mqtt import mqtt_publish

sensor_bp = Blueprint('sensor', __name__)

# Track which device is being used
sensor_active_device: int | None = None


def stream_sensor_output(process: subprocess.Popen[bytes]) -> None:
    """Stream rtl_433 JSON output to queue."""
    try:
        app_module.sensor_queue.put({'type': 'status', 'text': 'started'})

        for line in iter(process.stdout.readline, b''):
            line = line.decode('utf-8', errors='replace').strip()
            if not line:
                continue

            try:
                # rtl_433 outputs JSON objects, one per line
                data = json.loads(line)
                data['type'] = 'sensor'
                app_module.sensor_queue.put(data)

                # Publish to MQTT
                mqtt_publish('sensor', data)

                # Push scope event when signal level data is present
                rssi = data.get('rssi')
                snr = data.get('snr')
                noise = data.get('noise')
                if rssi is not None or snr is not None:
                    try:
                        app_module.sensor_queue.put_nowait({
                            'type': 'scope',
                            'rssi': rssi if rssi is not None else 0,
                            'snr': snr if snr is not None else 0,
                            'noise': noise if noise is not None else 0,
                        })
                    except queue.Full:
                        pass

                # Log if enabled
                if app_module.logging_enabled:
                    try:
                        with open(app_module.log_file_path, 'a') as f:
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            f.write(f"{timestamp} | {data.get('model', 'Unknown')} | {json.dumps(data)}\n")
                    except Exception:
                        pass
            except json.JSONDecodeError:
                # Not JSON, send as raw
                app_module.sensor_queue.put({'type': 'raw', 'text': line})

    except Exception as e:
        app_module.sensor_queue.put({'type': 'error', 'text': str(e)})
    finally:
        global sensor_active_device
        # Ensure process is terminated
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        unregister_process(process)
        app_module.sensor_queue.put({'type': 'status', 'text': 'stopped'})
        with app_module.sensor_lock:
            app_module.sensor_process = None
        # Release SDR device
        if sensor_active_device is not None:
            app_module.release_sdr_device(sensor_active_device)
            sensor_active_device = None


@sensor_bp.route('/sensor/status')
def sensor_status() -> Response:
    """Check if sensor decoder is currently running."""
    with app_module.sensor_lock:
        running = app_module.sensor_process is not None and app_module.sensor_process.poll() is None
    return jsonify({'running': running})


@sensor_bp.route('/start_sensor', methods=['POST'])
def start_sensor() -> Response:
    global sensor_active_device

    with app_module.sensor_lock:
        if app_module.sensor_process:
            return jsonify({'status': 'error', 'message': 'Sensor already running'}), 409

        data = request.json or {}

        # Validate inputs
        try:
            freq = validate_frequency(data.get('frequency', '433.92'))
            gain = validate_gain(data.get('gain', '0'))
            ppm = validate_ppm(data.get('ppm', '0'))
            device = validate_device_index(data.get('device', '0'))
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

        # Check for rtl_tcp (remote SDR) connection
        rtl_tcp_host = data.get('rtl_tcp_host')
        rtl_tcp_port = data.get('rtl_tcp_port', 1234)

        # Claim local device if not using remote rtl_tcp
        if not rtl_tcp_host:
            device_int = int(device)
            error = app_module.claim_sdr_device(device_int, 'sensor')
            if error:
                return jsonify({
                    'status': 'error',
                    'error_type': 'DEVICE_BUSY',
                    'message': error
                }), 409
            sensor_active_device = device_int

        # Clear queue
        while not app_module.sensor_queue.empty():
            try:
                app_module.sensor_queue.get_nowait()
            except queue.Empty:
                break

        # Get SDR type and build command via abstraction layer
        sdr_type_str = data.get('sdr_type', 'rtlsdr')
        try:
            sdr_type = SDRType(sdr_type_str)
        except ValueError:
            sdr_type = SDRType.RTL_SDR

        if rtl_tcp_host:
            # Validate and create network device
            try:
                rtl_tcp_host = validate_rtl_tcp_host(rtl_tcp_host)
                rtl_tcp_port = validate_rtl_tcp_port(rtl_tcp_port)
            except ValueError as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400

            sdr_device = SDRFactory.create_network_device(rtl_tcp_host, rtl_tcp_port)
            logger.info(f"Using remote SDR: rtl_tcp://{rtl_tcp_host}:{rtl_tcp_port}")
        else:
            # Create local device object
            sdr_device = SDRFactory.create_default_device(sdr_type, index=device)

        builder = SDRFactory.get_builder(sdr_device.sdr_type)

        # Build ISM band decoder command
        bias_t = data.get('bias_t', False)
        cmd = builder.build_ism_command(
            device=sdr_device,
            frequency_mhz=freq,
            gain=float(gain) if gain and gain != 0 else None,
            ppm=int(ppm) if ppm and ppm != 0 else None,
            bias_t=bias_t
        )

        full_cmd = ' '.join(cmd)
        logger.info(f"Running: {full_cmd}")

        # Add signal level metadata so the frontend scope can display RSSI/SNR
        # Disable stats reporting to suppress "row count limit 50 reached" warnings
        cmd.extend(['-M', 'level', '-M', 'stats:0'])

        try:
            app_module.sensor_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            register_process(app_module.sensor_process)

            # Start output thread
            thread = threading.Thread(target=stream_sensor_output, args=(app_module.sensor_process,))
            thread.daemon = True
            thread.start()

            # Monitor stderr
            def monitor_stderr():
                for line in app_module.sensor_process.stderr:
                    err = line.decode('utf-8', errors='replace').strip()
                    if err:
                        logger.debug(f"[rtl_433] {err}")
                        app_module.sensor_queue.put({'type': 'info', 'text': f'[rtl_433] {err}'})

            stderr_thread = threading.Thread(target=monitor_stderr)
            stderr_thread.daemon = True
            stderr_thread.start()

            app_module.sensor_queue.put({'type': 'info', 'text': f'Command: {full_cmd}'})

            return jsonify({'status': 'started', 'command': full_cmd})

        except FileNotFoundError:
            # Release device on failure
            if sensor_active_device is not None:
                app_module.release_sdr_device(sensor_active_device)
                sensor_active_device = None
            return jsonify({'status': 'error', 'message': 'rtl_433 not found. Install with: brew install rtl_433'})
        except Exception as e:
            # Release device on failure
            if sensor_active_device is not None:
                app_module.release_sdr_device(sensor_active_device)
                sensor_active_device = None
            return jsonify({'status': 'error', 'message': str(e)})


@sensor_bp.route('/stop_sensor', methods=['POST'])
def stop_sensor() -> Response:
    global sensor_active_device

    with app_module.sensor_lock:
        if app_module.sensor_process:
            app_module.sensor_process.terminate()
            try:
                app_module.sensor_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                app_module.sensor_process.kill()
            app_module.sensor_process = None

            # Release device from registry
            if sensor_active_device is not None:
                app_module.release_sdr_device(sensor_active_device)
                sensor_active_device = None

            return jsonify({'status': 'stopped'})

        return jsonify({'status': 'not_running'})


@sensor_bp.route('/stream_sensor')
def stream_sensor() -> Response:
    def generate() -> Generator[str, None, None]:
        last_keepalive = time.time()
        keepalive_interval = 30.0

        while True:
            try:
                msg = app_module.sensor_queue.get(timeout=1)
                last_keepalive = time.time()
                try:
                    process_event('sensor', msg, msg.get('type'))
                except Exception:
                    pass
                yield format_sse(msg)
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
