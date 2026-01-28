"""
TSCM Threat Detection Engine

Analyzes WiFi, Bluetooth, and RF data to identify potential surveillance devices
and classify threats based on known patterns and baseline comparison.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from data.tscm_frequencies import (
    BLE_TRACKER_SIGNATURES,
    THREAT_TYPES,
    WIFI_CAMERA_PATTERNS,
    get_frequency_risk,
    get_threat_severity,
    is_known_tracker,
    is_potential_camera,
)
from utils.tscm.signal_classification import (
    classify_signal_strength,
    get_signal_strength_info,
    SignalStrength,
)

logger = logging.getLogger('intercept.tscm.detector')

# Classification levels for TSCM devices
CLASSIFICATION_LEVELS = {
    'informational': {
        'color': '#00cc00',  # Green
        'label': 'Informational',
        'description': 'Known device, expected infrastructure, or background noise',
    },
    'review': {
        'color': '#ffcc00',  # Yellow
        'label': 'Needs Review',
        'description': 'Unknown device requiring investigation',
    },
    'high_interest': {
        'color': '#ff3333',  # Red
        'label': 'High Interest',
        'description': 'Suspicious device requiring immediate attention',
    },
}

# BLE device types that can transmit audio (potential bugs)
AUDIO_CAPABLE_BLE_NAMES = [
    'headphone', 'headset', 'earphone', 'earbud', 'speaker',
    'audio', 'mic', 'microphone', 'airpod', 'buds',
    'jabra', 'bose', 'sony wf', 'sony wh', 'beats',
    'jbl', 'soundcore', 'anker', 'skullcandy',
]

# Device history for tracking repeat detections across scans
_device_history: dict[str, list[datetime]] = {}
_history_window_hours = 24  # Consider detections within 24 hours


def _record_device_seen(identifier: str) -> int:
    """Record a device sighting and return count of times seen."""
    now = datetime.now()
    if identifier not in _device_history:
        _device_history[identifier] = []

    # Clean old entries
    cutoff = now.timestamp() - (_history_window_hours * 3600)
    _device_history[identifier] = [
        dt for dt in _device_history[identifier]
        if dt.timestamp() > cutoff
    ]

    _device_history[identifier].append(now)
    return len(_device_history[identifier])


def _is_audio_capable_ble(name: str | None, device_type: str | None = None) -> bool:
    """Check if a BLE device might be audio-capable."""
    if name:
        name_lower = name.lower()
        for pattern in AUDIO_CAPABLE_BLE_NAMES:
            if pattern in name_lower:
                return True
    if device_type:
        type_lower = device_type.lower()
        if any(t in type_lower for t in ['audio', 'headset', 'headphone', 'speaker']):
            return True
    return False


class ThreatDetector:
    """
    Analyzes scan results to detect potential surveillance threats.
    """

    def __init__(self, baseline: dict | None = None):
        """
        Initialize the threat detector.

        Args:
            baseline: Optional baseline dict containing expected devices
        """
        self.baseline = baseline
        self.baseline_wifi_macs = set()
        self.baseline_bt_macs = set()
        self.baseline_rf_freqs = set()

        if baseline:
            self._load_baseline(baseline)

    def _load_baseline(self, baseline: dict) -> None:
        """Load baseline device identifiers for comparison."""
        # WiFi networks and clients
        for network in baseline.get('wifi_networks', []):
            if 'bssid' in network:
                self.baseline_wifi_macs.add(network['bssid'].upper())
            if 'clients' in network:
                for client in network['clients']:
                    if 'mac' in client:
                        self.baseline_wifi_macs.add(client['mac'].upper())

        # Bluetooth devices
        for device in baseline.get('bt_devices', []):
            if 'mac' in device:
                self.baseline_bt_macs.add(device['mac'].upper())

        # RF frequencies (rounded to nearest 0.1 MHz)
        for freq in baseline.get('rf_frequencies', []):
            if isinstance(freq, dict):
                self.baseline_rf_freqs.add(round(freq.get('frequency', 0), 1))
            else:
                self.baseline_rf_freqs.add(round(freq, 1))

        logger.info(
            f"Loaded baseline: {len(self.baseline_wifi_macs)} WiFi, "
            f"{len(self.baseline_bt_macs)} BT, {len(self.baseline_rf_freqs)} RF"
        )

    def classify_wifi_device(self, device: dict) -> dict:
        """
        Classify a WiFi device into informational/review/high_interest.

        Returns:
            Dict with 'classification', 'reasons', and metadata
        """
        mac = device.get('bssid', device.get('mac', '')).upper()
        ssid = device.get('essid', device.get('ssid', ''))
        signal = device.get('power', device.get('signal', -100))

        reasons = []
        classification = 'informational'

        # Track repeat detections
        times_seen = _record_device_seen(f'wifi:{mac}') if mac else 1

        # Check if in baseline (known device)
        in_baseline = mac in self.baseline_wifi_macs if self.baseline else False

        if in_baseline:
            reasons.append('Known device in baseline')
            classification = 'informational'
        else:
            # New/unknown device
            reasons.append('New WiFi access point')
            classification = 'review'

            # Check for suspicious patterns -> high interest
            if is_potential_camera(ssid=ssid, mac=mac):
                reasons.append('Matches camera device patterns')
                classification = 'high_interest'

            try:
                signal_val = int(signal) if signal else -100
            except (ValueError, TypeError):
                signal_val = -100

            # Use standardized signal classification
            signal_info = get_signal_strength_info(signal_val)
            if not ssid and signal_info['strength'] in ('strong', 'very_strong'):
                reasons.append(f"Hidden SSID with {signal_info['label'].lower()} signal")
                classification = 'high_interest'

            # Repeat detections across scans
            if times_seen >= 3:
                reasons.append(f'Repeat detection ({times_seen} times)')
                if classification != 'high_interest':
                    classification = 'high_interest'

        # Include standardized signal classification
        signal_info = get_signal_strength_info(signal_val)

        return {
            'classification': classification,
            'reasons': reasons,
            'in_baseline': in_baseline,
            'times_seen': times_seen,
            'signal_strength': signal_info['strength'],
            'signal_label': signal_info['label'],
            'signal_confidence': signal_info['confidence'],
        }

    def classify_bt_device(self, device: dict) -> dict:
        """
        Classify a Bluetooth device into informational/review/high_interest.

        Now uses the v2 tracker detection data if available.

        Returns:
            Dict with 'classification', 'reasons', and metadata
        """
        mac = device.get('mac', device.get('address', '')).upper()
        name = device.get('name', '')
        rssi = device.get('rssi', device.get('signal', -100))
        device_type = device.get('type', '')
        manufacturer_data = device.get('manufacturer_data')

        reasons = []
        classification = 'informational'

        # Track repeat detections
        times_seen = _record_device_seen(f'bt:{mac}') if mac else 1

        # Check if in baseline (known device)
        in_baseline = mac in self.baseline_bt_macs if self.baseline else False

        # Use v2 tracker detection data if available (from get_tscm_bluetooth_snapshot)
        tracker_data = device.get('tracker', {})
        is_tracker_v2 = tracker_data.get('is_tracker', False)
        tracker_type_v2 = tracker_data.get('type')
        tracker_name_v2 = tracker_data.get('name')
        tracker_confidence_v2 = tracker_data.get('confidence')
        tracker_evidence_v2 = tracker_data.get('evidence', [])

        # Use v2 risk analysis if available
        risk_data = device.get('risk_analysis', {})
        risk_score = risk_data.get('risk_score', 0)
        risk_factors = risk_data.get('risk_factors', [])

        # Fall back to legacy detection if v2 not available
        tracker_info_legacy = None
        if not is_tracker_v2:
            tracker_info_legacy = is_known_tracker(name, manufacturer_data)

        is_tracker = is_tracker_v2 or (tracker_info_legacy is not None)

        if in_baseline:
            reasons.append('Known device in baseline')
            classification = 'informational'
        else:
            # New/unknown BLE device
            if not name or name == 'Unknown':
                reasons.append('Unknown BLE device')
                classification = 'review'
            else:
                reasons.append('New Bluetooth device')
                classification = 'review'

            # Check for trackers -> high interest
            if is_tracker_v2:
                tracker_label = tracker_name_v2 or tracker_type_v2 or 'Unknown tracker'
                conf_label = f' ({tracker_confidence_v2})' if tracker_confidence_v2 else ''
                reasons.append(f"Tracker detected: {tracker_label}{conf_label}")
                classification = 'high_interest'

                # Add evidence from v2 detection
                for evidence_item in tracker_evidence_v2[:2]:  # First 2 items
                    reasons.append(f"Evidence: {evidence_item}")

                # Add risk factors if significant
                if risk_score >= 0.3:
                    reasons.append(f"Risk score: {int(risk_score * 100)}%")
                    for factor in risk_factors[:2]:  # First 2 factors
                        reasons.append(f"Risk: {factor}")

            elif tracker_info_legacy:
                reasons.append(f"Known tracker: {tracker_info_legacy.get('name', 'Unknown')}")
                classification = 'high_interest'

            # Check for audio-capable devices -> high interest
            if _is_audio_capable_ble(name, device_type):
                reasons.append('Audio-capable BLE device')
                classification = 'high_interest'

            # Strong signal from unknown device - use standardized classification
            try:
                rssi_val = int(rssi) if rssi else -100
            except (ValueError, TypeError):
                rssi_val = -100

            signal_info = get_signal_strength_info(rssi_val)
            if signal_info['strength'] in ('strong', 'very_strong') and not name:
                reasons.append(f"{signal_info['label']} signal from unnamed device")
                classification = 'high_interest'

            # Repeat detections across scans
            if times_seen >= 3:
                reasons.append(f'Repeat detection ({times_seen} times)')
                if classification != 'high_interest':
                    classification = 'high_interest'

        # Include standardized signal classification
        try:
            rssi_val = int(rssi) if rssi else -100
        except (ValueError, TypeError):
            rssi_val = -100
        signal_info = get_signal_strength_info(rssi_val)

        return {
            'classification': classification,
            'reasons': reasons,
            'in_baseline': in_baseline,
            'times_seen': times_seen,
            'is_tracker': is_tracker,
            'tracker_type': tracker_type_v2,
            'tracker_name': tracker_name_v2,
            'tracker_confidence': tracker_confidence_v2,
            'risk_score': risk_score,
            'is_audio_capable': _is_audio_capable_ble(name, device_type),
            'signal_strength': signal_info['strength'],
            'signal_label': signal_info['label'],
            'signal_confidence': signal_info['confidence'],
        }

    def classify_rf_signal(self, signal: dict) -> dict:
        """
        Classify an RF signal into informational/review/high_interest.

        Returns:
            Dict with 'classification', 'reasons', and metadata
        """
        frequency = signal.get('frequency', 0)
        power = signal.get('power', signal.get('level', -100))
        band = signal.get('band', '')

        reasons = []
        classification = 'informational'
        freq_rounded = round(frequency, 1)

        # Track repeat detections
        times_seen = _record_device_seen(f'rf:{freq_rounded}')

        # Check if in baseline (known frequency)
        in_baseline = freq_rounded in self.baseline_rf_freqs if self.baseline else False

        # Get frequency risk info
        risk, band_name = get_frequency_risk(frequency)

        if in_baseline:
            reasons.append('Known frequency in baseline')
            classification = 'informational'
        else:
            # New/unidentified RF carrier
            reasons.append(f'Unidentified RF carrier in {band_name}')

            if risk == 'low':
                reasons.append('Background RF noise band')
                classification = 'review'
            elif risk == 'medium':
                reasons.append('ISM band signal')
                classification = 'review'
            elif risk in ['high', 'critical']:
                reasons.append(f'High-risk surveillance band: {band_name}')
                classification = 'high_interest'

            # Strong persistent signal - use standardized classification
            if power:
                power_info = get_signal_strength_info(float(power))
                if power_info['strength'] in ('strong', 'very_strong'):
                    reasons.append(f"{power_info['label']} persistent transmitter")
                    classification = 'high_interest'

            # Repeat detections (persistent transmitter)
            if times_seen >= 2:
                reasons.append(f'Persistent transmitter ({times_seen} detections)')
                classification = 'high_interest'

        # Include standardized signal classification
        try:
            power_val = float(power) if power else -100
        except (ValueError, TypeError):
            power_val = -100
        signal_info = get_signal_strength_info(power_val)

        return {
            'classification': classification,
            'reasons': reasons,
            'in_baseline': in_baseline,
            'times_seen': times_seen,
            'risk_level': risk,
            'band_name': band_name,
            'signal_strength': signal_info['strength'],
            'signal_label': signal_info['label'],
            'signal_confidence': signal_info['confidence'],
        }

    def analyze_wifi_device(self, device: dict) -> dict | None:
        """
        Analyze a WiFi device for threats.

        Args:
            device: WiFi device dict with bssid, essid, etc.

        Returns:
            Threat dict if threat detected, None otherwise
        """
        mac = device.get('bssid', device.get('mac', '')).upper()
        ssid = device.get('essid', device.get('ssid', ''))
        vendor = device.get('vendor', '')
        signal = device.get('power', device.get('signal', -100))

        threats = []

        # Check if new device (not in baseline)
        if self.baseline and mac and mac not in self.baseline_wifi_macs:
            threats.append({
                'type': 'new_device',
                'severity': get_threat_severity('new_device', {'signal_strength': signal}),
                'reason': 'Device not present in baseline',
            })

        # Check for hidden camera patterns
        if is_potential_camera(ssid=ssid, mac=mac, vendor=vendor):
            threats.append({
                'type': 'hidden_camera',
                'severity': get_threat_severity('hidden_camera', {'signal_strength': signal}),
                'reason': 'Device matches WiFi camera patterns',
            })

        # Check for hidden SSID with strong signal - use standardized classification
        try:
            signal_int = int(signal) if signal else -100
        except (ValueError, TypeError):
            signal_int = -100

        signal_info = get_signal_strength_info(signal_int)
        if not ssid and signal_info['strength'] in ('strong', 'very_strong'):
            threats.append({
                'type': 'anomaly',
                'severity': 'medium',
                'reason': f"Hidden SSID with {signal_info['label'].lower()} signal",
            })

        if not threats:
            return None

        # Return highest severity threat
        threats.sort(key=lambda t: ['low', 'medium', 'high', 'critical'].index(t['severity']), reverse=True)

        return {
            'threat_type': threats[0]['type'],
            'severity': threats[0]['severity'],
            'source': 'wifi',
            'identifier': mac,
            'name': ssid or 'Hidden Network',
            'signal_strength': signal,
            'details': {
                'all_threats': threats,
                'vendor': vendor,
                'ssid': ssid,
            }
        }

    def analyze_bt_device(self, device: dict) -> dict | None:
        """
        Analyze a Bluetooth device for threats.

        Args:
            device: BT device dict with mac, name, rssi, etc.

        Returns:
            Threat dict if threat detected, None otherwise
        """
        mac = device.get('mac', device.get('address', '')).upper()
        name = device.get('name', '')
        rssi = device.get('rssi', device.get('signal', -100))
        manufacturer = device.get('manufacturer', '')
        device_type = device.get('type', '')
        manufacturer_data = device.get('manufacturer_data')

        threats = []

        # Check if new device (not in baseline)
        if self.baseline and mac and mac not in self.baseline_bt_macs:
            threats.append({
                'type': 'new_device',
                'severity': get_threat_severity('new_device', {'signal_strength': rssi}),
                'reason': 'Device not present in baseline',
            })

        # Check for known trackers
        tracker_info = is_known_tracker(name, manufacturer_data)
        if tracker_info:
            threats.append({
                'type': 'tracker',
                'severity': tracker_info.get('risk', 'high'),
                'reason': f"Known tracker detected: {tracker_info.get('name', 'Unknown')}",
                'tracker_type': tracker_info.get('name'),
            })

        # Check for suspicious BLE beacons (unnamed, persistent) - use standardized classification
        try:
            rssi_int = int(rssi) if rssi else -100
        except (ValueError, TypeError):
            rssi_int = -100

        signal_info = get_signal_strength_info(rssi_int)
        if not name and signal_info['strength'] in ('moderate', 'strong', 'very_strong'):
            threats.append({
                'type': 'anomaly',
                'severity': 'medium',
                'reason': f"Unnamed BLE device with {signal_info['label'].lower()} signal",
            })

        if not threats:
            return None

        # Return highest severity threat
        threats.sort(key=lambda t: ['low', 'medium', 'high', 'critical'].index(t['severity']), reverse=True)

        return {
            'threat_type': threats[0]['type'],
            'severity': threats[0]['severity'],
            'source': 'bluetooth',
            'identifier': mac,
            'name': name or 'Unknown BLE Device',
            'signal_strength': rssi,
            'details': {
                'all_threats': threats,
                'manufacturer': manufacturer,
                'device_type': device_type,
            }
        }

    def analyze_rf_signal(self, signal: dict) -> dict | None:
        """
        Analyze an RF signal for threats.

        Args:
            signal: RF signal dict with frequency, level, etc.

        Returns:
            Threat dict if threat detected, None otherwise
        """
        frequency = signal.get('frequency', 0)
        level = signal.get('level', signal.get('power', -100))
        modulation = signal.get('modulation', '')

        if not frequency:
            return None

        threats = []
        freq_rounded = round(frequency, 1)

        # Check if new frequency (not in baseline)
        if self.baseline and freq_rounded not in self.baseline_rf_freqs:
            risk, band_name = get_frequency_risk(frequency)
            threats.append({
                'type': 'unknown_signal',
                'severity': risk,
                'reason': f'New signal in {band_name}',
            })

        # Check frequency risk even without baseline
        risk, band_name = get_frequency_risk(frequency)
        if risk in ['high', 'critical']:
            threats.append({
                'type': 'unknown_signal',
                'severity': risk,
                'reason': f'Signal in high-risk band: {band_name}',
            })

        if not threats:
            return None

        # Return highest severity threat
        threats.sort(key=lambda t: ['low', 'medium', 'high', 'critical'].index(t['severity']), reverse=True)

        return {
            'threat_type': threats[0]['type'],
            'severity': threats[0]['severity'],
            'source': 'rf',
            'identifier': f'{frequency:.3f} MHz',
            'name': f'RF Signal @ {frequency:.3f} MHz',
            'signal_strength': level,
            'frequency': frequency,
            'details': {
                'all_threats': threats,
                'modulation': modulation,
                'band_name': band_name,
            }
        }

    def analyze_all(
        self,
        wifi_devices: list[dict] | None = None,
        bt_devices: list[dict] | None = None,
        rf_signals: list[dict] | None = None
    ) -> list[dict]:
        """
        Analyze all provided devices and signals for threats.

        Returns:
            List of detected threats sorted by severity
        """
        threats = []

        if wifi_devices:
            for device in wifi_devices:
                threat = self.analyze_wifi_device(device)
                if threat:
                    threats.append(threat)

        if bt_devices:
            for device in bt_devices:
                threat = self.analyze_bt_device(device)
                if threat:
                    threats.append(threat)

        if rf_signals:
            for signal in rf_signals:
                threat = self.analyze_rf_signal(signal)
                if threat:
                    threats.append(threat)

        # Sort by severity (critical first)
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        threats.sort(key=lambda t: severity_order.get(t.get('severity', 'low'), 3))

        return threats


def classify_device_threat(
    source: str,
    device: dict,
    baseline: dict | None = None
) -> dict | None:
    """
    Convenience function to classify a single device.

    Args:
        source: Device source ('wifi', 'bluetooth', 'rf')
        device: Device data dict
        baseline: Optional baseline for comparison

    Returns:
        Threat dict if threat detected, None otherwise
    """
    detector = ThreatDetector(baseline)

    if source == 'wifi':
        return detector.analyze_wifi_device(device)
    elif source == 'bluetooth':
        return detector.analyze_bt_device(device)
    elif source == 'rf':
        return detector.analyze_rf_signal(device)

    return None
