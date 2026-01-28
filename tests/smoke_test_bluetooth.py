#!/usr/bin/env python3
"""
Smoke Test for Bluetooth API Backwards Compatibility

Run this script against a running INTERCEPT server to verify:
1. Existing v1/v2 endpoints still work
2. New tracker endpoints work
3. TSCM integration is not broken
4. JSON schemas are compatible

Usage:
    python tests/smoke_test_bluetooth.py [--host HOST] [--port PORT]

Requirements:
    - INTERCEPT server must be running
    - requests library: pip install requests
"""

import argparse
import json
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


# =============================================================================
# SCHEMA VALIDATORS
# =============================================================================

def validate_device_schema(device: dict, context: str = "") -> list[str]:
    """Validate that a device dict has expected fields (backwards compatible)."""
    errors = []
    required_fields = [
        'device_id', 'address', 'rssi_current', 'last_seen', 'seen_count'
    ]

    for field in required_fields:
        if field not in device:
            errors.append(f"{context}Missing required field: {field}")

    # New tracker fields should be present (v2) but are optional
    tracker_fields = ['is_tracker', 'tracker_type', 'tracker_confidence']
    for field in tracker_fields:
        if field in device:
            # Field exists, check type
            if field == 'is_tracker' and not isinstance(device[field], bool):
                errors.append(f"{context}is_tracker should be bool, got {type(device[field])}")

    return errors


def validate_tracker_schema(tracker: dict, context: str = "") -> list[str]:
    """Validate tracker endpoint response schema."""
    errors = []

    required_fields = [
        'device_id', 'address', 'tracker'
    ]
    for field in required_fields:
        if field not in tracker:
            errors.append(f"{context}Missing required field: {field}")

    # Tracker sub-object
    if 'tracker' in tracker:
        tracker_obj = tracker['tracker']
        tracker_required = ['type', 'confidence', 'evidence']
        for field in tracker_required:
            if field not in tracker_obj:
                errors.append(f"{context}tracker.{field} missing")

    return errors


def validate_diagnostics_schema(diagnostics: dict) -> list[str]:
    """Validate diagnostics endpoint response schema."""
    errors = []

    required_sections = ['system', 'bluez', 'adapters', 'permissions', 'backends']
    for section in required_sections:
        if section not in diagnostics:
            errors.append(f"Missing diagnostics section: {section}")

    if 'can_scan' not in diagnostics:
        errors.append("Missing can_scan field")

    return errors


# =============================================================================
# TEST CASES
# =============================================================================

class SmokeTests:
    """Smoke test runner."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.passed = 0
        self.failed = 0
        self.errors = []

    def _check(self, name: str, condition: bool, error_msg: str = ""):
        """Record a test result."""
        if condition:
            print(f"  [PASS] {name}")
            self.passed += 1
        else:
            print(f"  [FAIL] {name}: {error_msg}")
            self.failed += 1
            self.errors.append(f"{name}: {error_msg}")

    def test_capabilities_endpoint(self):
        """Test GET /api/bluetooth/capabilities"""
        print("\n=== Test: Capabilities Endpoint ===")
        try:
            resp = requests.get(f"{self.base_url}/api/bluetooth/capabilities", timeout=5)
            self._check("Status code 200", resp.status_code == 200, f"Got {resp.status_code}")

            data = resp.json()
            self._check("Has 'available' field", 'available' in data or 'can_scan' in data)
            self._check("Has 'adapters' field", 'adapters' in data)
            self._check("Has 'recommended_backend' field", 'recommended_backend' in data or 'preferred_backend' in data)

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_devices_endpoint(self):
        """Test GET /api/bluetooth/devices (backwards compatibility)"""
        print("\n=== Test: Devices Endpoint (v2) ===")
        try:
            resp = requests.get(f"{self.base_url}/api/bluetooth/devices", timeout=5)
            self._check("Status code 200", resp.status_code == 200, f"Got {resp.status_code}")

            data = resp.json()
            self._check("Has 'count' field", 'count' in data)
            self._check("Has 'devices' array", 'devices' in data and isinstance(data['devices'], list))

            # If devices exist, validate schema
            if data.get('devices'):
                device = data['devices'][0]
                errors = validate_device_schema(device, "First device: ")
                self._check("Device schema valid", len(errors) == 0, "; ".join(errors))

                # Check for new tracker fields (should exist even if empty)
                self._check("Has tracker fields", 'is_tracker' in device,
                           "New tracker field missing (backwards compat issue)")

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_trackers_endpoint(self):
        """Test GET /api/bluetooth/trackers (new v2 endpoint)"""
        print("\n=== Test: Trackers Endpoint (NEW) ===")
        try:
            resp = requests.get(f"{self.base_url}/api/bluetooth/trackers", timeout=5)
            self._check("Status code 200", resp.status_code == 200, f"Got {resp.status_code}")

            data = resp.json()
            self._check("Has 'count' field", 'count' in data)
            self._check("Has 'trackers' array", 'trackers' in data and isinstance(data['trackers'], list))
            self._check("Has 'summary' field", 'summary' in data)

            # If trackers exist, validate schema
            if data.get('trackers'):
                tracker = data['trackers'][0]
                errors = validate_tracker_schema(tracker, "First tracker: ")
                self._check("Tracker schema valid", len(errors) == 0, "; ".join(errors))

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_diagnostics_endpoint(self):
        """Test GET /api/bluetooth/diagnostics (new endpoint)"""
        print("\n=== Test: Diagnostics Endpoint (NEW) ===")
        try:
            resp = requests.get(f"{self.base_url}/api/bluetooth/diagnostics", timeout=5)
            self._check("Status code 200", resp.status_code == 200, f"Got {resp.status_code}")

            data = resp.json()
            errors = validate_diagnostics_schema(data)
            self._check("Diagnostics schema valid", len(errors) == 0, "; ".join(errors))

            self._check("Has recommendations", 'recommendations' in data)

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_scan_status_endpoint(self):
        """Test GET /api/bluetooth/scan/status"""
        print("\n=== Test: Scan Status Endpoint ===")
        try:
            resp = requests.get(f"{self.base_url}/api/bluetooth/scan/status", timeout=5)
            self._check("Status code 200", resp.status_code == 200, f"Got {resp.status_code}")

            data = resp.json()
            self._check("Has 'is_scanning' field", 'is_scanning' in data)

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_baseline_endpoints(self):
        """Test baseline management endpoints"""
        print("\n=== Test: Baseline Endpoints ===")
        try:
            # List baselines
            resp = requests.get(f"{self.base_url}/api/bluetooth/baseline/list", timeout=5)
            self._check("List baselines: Status 200", resp.status_code == 200, f"Got {resp.status_code}")

            data = resp.json()
            self._check("Has 'baselines' array", 'baselines' in data)

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_tscm_integration(self):
        """Test that TSCM still works with Bluetooth"""
        print("\n=== Test: TSCM Integration ===")
        try:
            # Get TSCM sweep presets
            resp = requests.get(f"{self.base_url}/tscm/devices", timeout=5)
            # This might 404 if no devices, which is ok
            self._check("TSCM devices endpoint accessible", resp.status_code in (200, 404))

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def test_export_endpoint(self):
        """Test GET /api/bluetooth/export"""
        print("\n=== Test: Export Endpoint ===")
        try:
            # JSON export
            resp = requests.get(f"{self.base_url}/api/bluetooth/export?format=json", timeout=5)
            self._check("JSON export: Status 200", resp.status_code == 200, f"Got {resp.status_code}")
            self._check("JSON export: Content-Type", 'application/json' in resp.headers.get('Content-Type', ''))

            # CSV export
            resp = requests.get(f"{self.base_url}/api/bluetooth/export?format=csv", timeout=5)
            self._check("CSV export: Status 200", resp.status_code == 200, f"Got {resp.status_code}")
            self._check("CSV export: Content-Type", 'text/csv' in resp.headers.get('Content-Type', ''))

        except requests.RequestException as e:
            self._check("Request succeeded", False, str(e))

    def run_all(self):
        """Run all smoke tests."""
        print(f"\n{'='*60}")
        print(f"BLUETOOTH API SMOKE TESTS")
        print(f"Target: {self.base_url}")
        print(f"{'='*60}")

        self.test_capabilities_endpoint()
        self.test_devices_endpoint()
        self.test_trackers_endpoint()
        self.test_diagnostics_endpoint()
        self.test_scan_status_endpoint()
        self.test_baseline_endpoints()
        self.test_export_endpoint()
        self.test_tscm_integration()

        print(f"\n{'='*60}")
        print(f"RESULTS: {self.passed} passed, {self.failed} failed")
        print(f"{'='*60}")

        if self.errors:
            print("\nFailed tests:")
            for error in self.errors:
                print(f"  - {error}")

        return self.failed == 0


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Bluetooth API smoke tests")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    # Check server is reachable
    print(f"Checking server at {base_url}...")
    try:
        resp = requests.get(f"{base_url}/api/bluetooth/capabilities", timeout=5)
        print(f"Server responded: {resp.status_code}")
    except requests.RequestException as e:
        print(f"ERROR: Cannot reach server at {base_url}")
        print(f"Details: {e}")
        print("\nMake sure INTERCEPT is running:")
        print("  cd /path/to/intercept && python app.py")
        sys.exit(1)

    # Run tests
    tests = SmokeTests(base_url)
    success = tests.run_all()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
