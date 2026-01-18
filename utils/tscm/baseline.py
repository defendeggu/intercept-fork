"""
TSCM Baseline Recording and Comparison

Records environment "fingerprints" and compares current scans
against baselines to detect new or anomalous devices.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from utils.database import (
    create_tscm_baseline,
    get_active_tscm_baseline,
    get_tscm_baseline,
    update_tscm_baseline,
)

logger = logging.getLogger('intercept.tscm.baseline')


class BaselineRecorder:
    """
    Records and manages TSCM environment baselines.
    """

    def __init__(self):
        self.recording = False
        self.current_baseline_id: int | None = None
        self.wifi_networks: dict[str, dict] = {}  # BSSID -> network info
        self.bt_devices: dict[str, dict] = {}  # MAC -> device info
        self.rf_frequencies: dict[float, dict] = {}  # Frequency -> signal info

    def start_recording(
        self,
        name: str,
        location: str | None = None,
        description: str | None = None
    ) -> int:
        """
        Start recording a new baseline.

        Args:
            name: Baseline name
            location: Optional location description
            description: Optional description

        Returns:
            Baseline ID
        """
        self.recording = True
        self.wifi_networks = {}
        self.bt_devices = {}
        self.rf_frequencies = {}

        # Create baseline in database
        self.current_baseline_id = create_tscm_baseline(
            name=name,
            location=location,
            description=description
        )

        logger.info(f"Started baseline recording: {name} (ID: {self.current_baseline_id})")
        return self.current_baseline_id

    def stop_recording(self) -> dict:
        """
        Stop recording and finalize baseline.

        Returns:
            Final baseline summary
        """
        if not self.recording or not self.current_baseline_id:
            return {'error': 'Not recording'}

        self.recording = False

        # Convert to lists for storage
        wifi_list = list(self.wifi_networks.values())
        bt_list = list(self.bt_devices.values())
        rf_list = list(self.rf_frequencies.values())

        # Update database
        update_tscm_baseline(
            self.current_baseline_id,
            wifi_networks=wifi_list,
            bt_devices=bt_list,
            rf_frequencies=rf_list
        )

        summary = {
            'baseline_id': self.current_baseline_id,
            'wifi_count': len(wifi_list),
            'bt_count': len(bt_list),
            'rf_count': len(rf_list),
        }

        logger.info(
            f"Baseline recording complete: {summary['wifi_count']} WiFi, "
            f"{summary['bt_count']} BT, {summary['rf_count']} RF"
        )

        baseline_id = self.current_baseline_id
        self.current_baseline_id = None

        return summary

    def add_wifi_device(self, device: dict) -> None:
        """Add a WiFi device to the current baseline."""
        if not self.recording:
            return

        mac = device.get('bssid', device.get('mac', '')).upper()
        if not mac:
            return

        # Update or add device
        if mac in self.wifi_networks:
            # Update with latest info
            self.wifi_networks[mac].update({
                'last_seen': datetime.now().isoformat(),
                'power': device.get('power', self.wifi_networks[mac].get('power')),
            })
        else:
            self.wifi_networks[mac] = {
                'bssid': mac,
                'essid': device.get('essid', device.get('ssid', '')),
                'channel': device.get('channel'),
                'power': device.get('power', device.get('signal')),
                'vendor': device.get('vendor', ''),
                'encryption': device.get('privacy', device.get('encryption', '')),
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
            }

    def add_bt_device(self, device: dict) -> None:
        """Add a Bluetooth device to the current baseline."""
        if not self.recording:
            return

        mac = device.get('mac', device.get('address', '')).upper()
        if not mac:
            return

        if mac in self.bt_devices:
            self.bt_devices[mac].update({
                'last_seen': datetime.now().isoformat(),
                'rssi': device.get('rssi', self.bt_devices[mac].get('rssi')),
            })
        else:
            self.bt_devices[mac] = {
                'mac': mac,
                'name': device.get('name', ''),
                'rssi': device.get('rssi', device.get('signal')),
                'manufacturer': device.get('manufacturer', ''),
                'type': device.get('type', ''),
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
            }

    def add_rf_signal(self, signal: dict) -> None:
        """Add an RF signal to the current baseline."""
        if not self.recording:
            return

        frequency = signal.get('frequency')
        if not frequency:
            return

        # Round to 0.1 MHz for grouping
        freq_key = round(frequency, 1)

        if freq_key in self.rf_frequencies:
            existing = self.rf_frequencies[freq_key]
            existing['last_seen'] = datetime.now().isoformat()
            existing['hit_count'] = existing.get('hit_count', 1) + 1
            # Update max signal level
            new_level = signal.get('level', signal.get('power', -100))
            if new_level > existing.get('max_level', -100):
                existing['max_level'] = new_level
        else:
            self.rf_frequencies[freq_key] = {
                'frequency': freq_key,
                'level': signal.get('level', signal.get('power')),
                'max_level': signal.get('level', signal.get('power', -100)),
                'modulation': signal.get('modulation', ''),
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'hit_count': 1,
            }

    def get_recording_status(self) -> dict:
        """Get current recording status and counts."""
        return {
            'recording': self.recording,
            'baseline_id': self.current_baseline_id,
            'wifi_count': len(self.wifi_networks),
            'bt_count': len(self.bt_devices),
            'rf_count': len(self.rf_frequencies),
        }


class BaselineComparator:
    """
    Compares current scan results against a baseline.
    """

    def __init__(self, baseline: dict):
        """
        Initialize comparator with a baseline.

        Args:
            baseline: Baseline dict from database
        """
        self.baseline = baseline
        self.baseline_wifi = {
            d.get('bssid', d.get('mac', '')).upper(): d
            for d in baseline.get('wifi_networks', [])
            if d.get('bssid') or d.get('mac')
        }
        self.baseline_bt = {
            d.get('mac', d.get('address', '')).upper(): d
            for d in baseline.get('bt_devices', [])
            if d.get('mac') or d.get('address')
        }
        self.baseline_rf = {
            round(d.get('frequency', 0), 1): d
            for d in baseline.get('rf_frequencies', [])
            if d.get('frequency')
        }

    def compare_wifi(self, current_devices: list[dict]) -> dict:
        """
        Compare current WiFi devices against baseline.

        Returns:
            Dict with new, missing, and matching devices
        """
        current_macs = {
            d.get('bssid', d.get('mac', '')).upper(): d
            for d in current_devices
            if d.get('bssid') or d.get('mac')
        }

        new_devices = []
        missing_devices = []
        matching_devices = []

        # Find new devices
        for mac, device in current_macs.items():
            if mac not in self.baseline_wifi:
                new_devices.append(device)
            else:
                matching_devices.append(device)

        # Find missing devices
        for mac, device in self.baseline_wifi.items():
            if mac not in current_macs:
                missing_devices.append(device)

        return {
            'new': new_devices,
            'missing': missing_devices,
            'matching': matching_devices,
            'new_count': len(new_devices),
            'missing_count': len(missing_devices),
            'matching_count': len(matching_devices),
        }

    def compare_bluetooth(self, current_devices: list[dict]) -> dict:
        """Compare current Bluetooth devices against baseline."""
        current_macs = {
            d.get('mac', d.get('address', '')).upper(): d
            for d in current_devices
            if d.get('mac') or d.get('address')
        }

        new_devices = []
        missing_devices = []
        matching_devices = []

        for mac, device in current_macs.items():
            if mac not in self.baseline_bt:
                new_devices.append(device)
            else:
                matching_devices.append(device)

        for mac, device in self.baseline_bt.items():
            if mac not in current_macs:
                missing_devices.append(device)

        return {
            'new': new_devices,
            'missing': missing_devices,
            'matching': matching_devices,
            'new_count': len(new_devices),
            'missing_count': len(missing_devices),
            'matching_count': len(matching_devices),
        }

    def compare_rf(self, current_signals: list[dict]) -> dict:
        """Compare current RF signals against baseline."""
        current_freqs = {
            round(s.get('frequency', 0), 1): s
            for s in current_signals
            if s.get('frequency')
        }

        new_signals = []
        missing_signals = []
        matching_signals = []

        for freq, signal in current_freqs.items():
            if freq not in self.baseline_rf:
                new_signals.append(signal)
            else:
                matching_signals.append(signal)

        for freq, signal in self.baseline_rf.items():
            if freq not in current_freqs:
                missing_signals.append(signal)

        return {
            'new': new_signals,
            'missing': missing_signals,
            'matching': matching_signals,
            'new_count': len(new_signals),
            'missing_count': len(missing_signals),
            'matching_count': len(matching_signals),
        }

    def compare_all(
        self,
        wifi_devices: list[dict] | None = None,
        bt_devices: list[dict] | None = None,
        rf_signals: list[dict] | None = None
    ) -> dict:
        """
        Compare all current data against baseline.

        Returns:
            Dict with comparison results for each category
        """
        results = {
            'wifi': None,
            'bluetooth': None,
            'rf': None,
            'total_new': 0,
            'total_missing': 0,
        }

        if wifi_devices is not None:
            results['wifi'] = self.compare_wifi(wifi_devices)
            results['total_new'] += results['wifi']['new_count']
            results['total_missing'] += results['wifi']['missing_count']

        if bt_devices is not None:
            results['bluetooth'] = self.compare_bluetooth(bt_devices)
            results['total_new'] += results['bluetooth']['new_count']
            results['total_missing'] += results['bluetooth']['missing_count']

        if rf_signals is not None:
            results['rf'] = self.compare_rf(rf_signals)
            results['total_new'] += results['rf']['new_count']
            results['total_missing'] += results['rf']['missing_count']

        return results


def get_comparison_for_active_baseline(
    wifi_devices: list[dict] | None = None,
    bt_devices: list[dict] | None = None,
    rf_signals: list[dict] | None = None
) -> dict | None:
    """
    Convenience function to compare against the active baseline.

    Returns:
        Comparison results or None if no active baseline
    """
    baseline = get_active_tscm_baseline()
    if not baseline:
        return None

    comparator = BaselineComparator(baseline)
    return comparator.compare_all(wifi_devices, bt_devices, rf_signals)
