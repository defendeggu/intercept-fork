#!/usr/bin/env python3
"""
Mock Intercept Agent for development and testing.

This provides a simulated agent that generates fake data for testing
the controller without needing actual SDR hardware.

Usage:
    python tests/mock_agent.py [--port 8021] [--name mock-agent-1]
"""

from __future__ import annotations

import argparse
import json
import random
import string
import threading
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request

app = Flask(__name__)

# State
running_modes: set[str] = set()
start_time = time.time()
agent_name = "mock-agent-1"

# Simulated data generators
def generate_aircraft() -> list[dict]:
    """Generate fake ADS-B aircraft data."""
    aircraft = []
    for _ in range(random.randint(3, 10)):
        icao = ''.join(random.choices(string.hexdigits.upper()[:6], k=6))
        callsign = random.choice(['UAL', 'DAL', 'AAL', 'SWA', 'JBU']) + str(random.randint(100, 9999))
        aircraft.append({
            'icao': icao,
            'callsign': callsign,
            'altitude': random.randint(5000, 45000),
            'speed': random.randint(200, 550),
            'heading': random.randint(0, 359),
            'lat': round(40.0 + random.uniform(-2, 2), 4),
            'lon': round(-74.0 + random.uniform(-2, 2), 4),
            'vertical_rate': random.randint(-2000, 2000),
            'squawk': str(random.randint(1000, 7777)),
            'last_seen': datetime.now(timezone.utc).isoformat()
        })
    return aircraft


def generate_sensors() -> list[dict]:
    """Generate fake 433MHz sensor data."""
    sensors = []
    models = ['Acurite-Tower', 'Oregon-THGR122N', 'LaCrosse-TX141W', 'Ambient-F007TH']
    for i in range(random.randint(2, 5)):
        sensors.append({
            'time': datetime.now(timezone.utc).isoformat(),
            'model': random.choice(models),
            'id': random.randint(1, 255),
            'channel': random.randint(1, 3),
            'temperature_C': round(random.uniform(-10, 35), 1),
            'humidity': random.randint(20, 95),
            'battery_ok': random.choice([0, 1])
        })
    return sensors


def generate_wifi_networks() -> list[dict]:
    """Generate fake WiFi network data."""
    networks = []
    ssids = ['HomeNetwork', 'Linksys', 'NETGEAR', 'xfinitywifi', 'ATT-WIFI', 'CoffeeShop-Guest']
    for ssid in random.sample(ssids, random.randint(3, 6)):
        bssid = ':'.join(['%02X' % random.randint(0, 255) for _ in range(6)])
        networks.append({
            'ssid': ssid,
            'bssid': bssid,
            'channel': random.choice([1, 6, 11, 36, 40, 44, 48]),
            'signal': random.randint(-80, -30),
            'encryption': random.choice(['WPA2', 'WPA3', 'WEP', 'Open']),
            'clients': random.randint(0, 10),
            'last_seen': datetime.now(timezone.utc).isoformat()
        })
    return networks


def generate_bluetooth_devices() -> list[dict]:
    """Generate fake Bluetooth device data."""
    devices = []
    names = ['iPhone', 'Galaxy S21', 'AirPods', 'Tile Tracker', 'Fitbit', 'Unknown']
    for _ in range(random.randint(2, 8)):
        mac = ':'.join(['%02X' % random.randint(0, 255) for _ in range(6)])
        devices.append({
            'address': mac,
            'name': random.choice(names),
            'rssi': random.randint(-90, -40),
            'type': random.choice(['LE', 'Classic', 'Dual']),
            'manufacturer': random.choice(['Apple', 'Samsung', 'Unknown']),
            'last_seen': datetime.now(timezone.utc).isoformat()
        })
    return devices


def generate_vessels() -> list[dict]:
    """Generate fake AIS vessel data."""
    vessels = []
    vessel_names = ['EVERGREEN', 'MAERSK WINNER', 'OOCL HONG KONG', 'MSC GULSUN', 'CMA CGM MARCO POLO']
    for name in random.sample(vessel_names, random.randint(2, 4)):
        mmsi = str(random.randint(200000000, 800000000))
        vessels.append({
            'mmsi': mmsi,
            'name': name,
            'callsign': ''.join(random.choices(string.ascii_uppercase, k=5)),
            'ship_type': random.choice(['Cargo', 'Tanker', 'Passenger', 'Fishing']),
            'lat': round(40.5 + random.uniform(-0.5, 0.5), 4),
            'lon': round(-73.9 + random.uniform(-0.5, 0.5), 4),
            'speed': round(random.uniform(0, 25), 1),
            'course': random.randint(0, 359),
            'destination': random.choice(['NEW YORK', 'NEWARK', 'BALTIMORE', 'BOSTON']),
            'last_seen': datetime.now(timezone.utc).isoformat()
        })
    return vessels


# Data snapshot storage
data_snapshots: dict[str, list] = {}


def update_data_snapshot(mode: str):
    """Update data snapshot for a mode."""
    if mode == 'adsb':
        data_snapshots[mode] = generate_aircraft()
    elif mode == 'sensor':
        data_snapshots[mode] = generate_sensors()
    elif mode == 'wifi':
        data_snapshots[mode] = generate_wifi_networks()
    elif mode == 'bluetooth':
        data_snapshots[mode] = generate_bluetooth_devices()
    elif mode == 'ais':
        data_snapshots[mode] = generate_vessels()
    else:
        data_snapshots[mode] = []


# Background data generation threads
data_threads: dict[str, threading.Event] = {}


def data_generator_loop(mode: str, stop_event: threading.Event):
    """Background loop to generate data periodically."""
    while not stop_event.is_set():
        update_data_snapshot(mode)
        stop_event.wait(random.uniform(2, 5))


# =============================================================================
# Routes
# =============================================================================

@app.route('/capabilities')
def capabilities():
    """Return mock capabilities."""
    return jsonify({
        'modes': {
            'pager': True,
            'sensor': True,
            'adsb': True,
            'ais': True,
            'acars': True,
            'aprs': True,
            'wifi': True,
            'bluetooth': True,
            'dsc': True,
            'rtlamr': True,
            'tscm': True,
            'satellite': True,
            'listening_post': True
        },
        'devices': [
            {'index': 0, 'name': 'Mock RTL-SDR', 'type': 'rtlsdr', 'serial': 'MOCK001'}
        ],
        'agent_version': '1.0.0-mock'
    })


@app.route('/status')
def status():
    """Return agent status."""
    return jsonify({
        'running_modes': list(running_modes),
        'uptime': time.time() - start_time,
        'push_enabled': False,
        'push_connected': False
    })


@app.route('/health')
def health():
    """Health check."""
    return jsonify({'status': 'healthy', 'version': '1.0.0-mock'})


@app.route('/config', methods=['GET', 'POST'])
def config():
    """Config endpoint."""
    if request.method == 'POST':
        return jsonify({'status': 'updated', 'config': {}})
    return jsonify({
        'name': agent_name,
        'port': request.environ.get('SERVER_PORT', 8021),
        'push_enabled': False,
        'modes_enabled': {m: True for m in [
            'pager', 'sensor', 'adsb', 'ais', 'wifi', 'bluetooth'
        ]}
    })


@app.route('/<mode>/start', methods=['POST'])
def start_mode(mode: str):
    """Start a mode."""
    if mode in running_modes:
        return jsonify({'status': 'error', 'message': f'{mode} already running'}), 409

    running_modes.add(mode)

    # Start data generation thread
    stop_event = threading.Event()
    data_threads[mode] = stop_event
    thread = threading.Thread(target=data_generator_loop, args=(mode, stop_event))
    thread.daemon = True
    thread.start()

    # Generate initial data
    update_data_snapshot(mode)

    return jsonify({'status': 'started', 'mode': mode})


@app.route('/<mode>/stop', methods=['POST'])
def stop_mode(mode: str):
    """Stop a mode."""
    if mode not in running_modes:
        return jsonify({'status': 'not_running'})

    running_modes.discard(mode)

    # Stop data generation thread
    if mode in data_threads:
        data_threads[mode].set()
        del data_threads[mode]

    # Clear data
    if mode in data_snapshots:
        del data_snapshots[mode]

    return jsonify({'status': 'stopped', 'mode': mode})


@app.route('/<mode>/status')
def mode_status(mode: str):
    """Get mode status."""
    return jsonify({
        'running': mode in running_modes,
        'data_count': len(data_snapshots.get(mode, []))
    })


@app.route('/<mode>/data')
def mode_data(mode: str):
    """Get current data snapshot."""
    # Generate fresh data if mode is running but no snapshot exists
    if mode in running_modes and mode not in data_snapshots:
        update_data_snapshot(mode)

    return jsonify({
        'mode': mode,
        'data': data_snapshots.get(mode, []),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'agent_name': agent_name
    })


# =============================================================================
# Main
# =============================================================================

def main():
    global agent_name, start_time

    parser = argparse.ArgumentParser(description='Mock Intercept Agent')
    parser.add_argument('--port', '-p', type=int, default=8021, help='Port (default: 8021)')
    parser.add_argument('--name', '-n', default='mock-agent-1', help='Agent name')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()
    agent_name = args.name
    start_time = time.time()

    print("=" * 60)
    print("  MOCK INTERCEPT AGENT")
    print("  For development and testing")
    print("=" * 60)
    print()
    print(f"  Agent Name:  {agent_name}")
    print(f"  Port:        {args.port}")
    print()
    print("  Available modes: all (simulated data)")
    print()
    print(f"  Listening on http://0.0.0.0:{args.port}")
    print()
    print("  Press Ctrl+C to stop")
    print()

    app.run(host='0.0.0.0', port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
