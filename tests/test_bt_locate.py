"""Tests for BT Locate — Bluetooth SAR Device Location System."""

from unittest.mock import MagicMock, patch

import pytest

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from cryptography.hazmat.primitives.ciphers import modes as cipher_modes
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

from utils.bt_locate import (
    DistanceEstimator,
    Environment,
    LocateSession,
    LocateTarget,
    get_locate_session,
    resolve_rpa,
    start_locate_session,
    stop_locate_session,
)


class TestResolveRPA:
    """Test BLE Resolvable Private Address resolution."""

    @pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="cryptography not installed")
    def test_resolve_rpa_valid_match(self):
        """Test RPA resolution with known IRK/address pair.

        Uses test vector: IRK = all zeros, we generate matching address.
        """
        # The ah() function: encrypt(IRK, 0x00..00 || prand) then take last 3 bytes

        irk = b'\x00' * 16
        # Choose prand with upper 2 bits = 01 (resolvable)
        prand = bytes([0x40, 0x00, 0x01])
        plaintext = b'\x00' * 13 + prand
        c = Cipher(algorithms.AES(irk), cipher_modes.ECB())
        enc = c.encryptor()
        encrypted = enc.update(plaintext) + enc.finalize()
        hash_bytes = encrypted[13:16]

        # Build address: prand || hash
        addr_bytes = prand + hash_bytes
        address = ':'.join(f'{b:02X}' for b in addr_bytes)

        assert resolve_rpa(irk, address) is True

    def test_resolve_rpa_invalid_address(self):
        """Test RPA resolution with non-matching address."""
        irk = b'\x00' * 16
        # Non-resolvable address (upper 2 bits != 01)
        assert resolve_rpa(irk, 'FF:FF:FF:FF:FF:FF') is False

    @pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="cryptography not installed")
    def test_resolve_rpa_wrong_irk(self):
        """Test RPA resolution with wrong IRK."""
        irk = b'\x00' * 16
        prand = bytes([0x40, 0x00, 0x01])
        plaintext = b'\x00' * 13 + prand
        c = Cipher(algorithms.AES(irk), cipher_modes.ECB())
        enc = c.encryptor()
        encrypted = enc.update(plaintext) + enc.finalize()
        hash_bytes = encrypted[13:16]
        addr_bytes = prand + hash_bytes
        address = ':'.join(f'{b:02X}' for b in addr_bytes)

        # Different IRK should fail
        wrong_irk = b'\x01' * 16
        assert resolve_rpa(wrong_irk, address) is False

    def test_resolve_rpa_short_address(self):
        """Test with invalid short address."""
        irk = b'\x00' * 16
        assert resolve_rpa(irk, 'AA:BB') is False

    def test_resolve_rpa_empty(self):
        """Test with empty inputs."""
        assert resolve_rpa(b'\x00' * 16, '') is False


class TestDistanceEstimator:
    """Test RSSI-to-distance estimation."""

    def test_free_space_distance(self):
        estimator = DistanceEstimator(path_loss_exponent=2.0, rssi_at_1m=-59)
        # At 1m, RSSI should be -59, so distance should be ~1m
        d = estimator.estimate(-59)
        assert abs(d - 1.0) < 0.01

    def test_weaker_signal_farther(self):
        estimator = DistanceEstimator(path_loss_exponent=2.0)
        d1 = estimator.estimate(-50)
        d2 = estimator.estimate(-70)
        assert d2 > d1

    def test_indoor_closer_estimate(self):
        """Indoor (n=3) should estimate closer distance for same RSSI."""
        free_space = DistanceEstimator(path_loss_exponent=2.0)
        indoor = DistanceEstimator(path_loss_exponent=3.0)
        rssi = -75
        d_free = free_space.estimate(rssi)
        d_indoor = indoor.estimate(rssi)
        # With higher path loss exponent, same RSSI means closer distance
        assert d_indoor < d_free

    def test_proximity_band_immediate(self):
        assert DistanceEstimator.proximity_band(0.5) == 'IMMEDIATE'

    def test_proximity_band_near(self):
        assert DistanceEstimator.proximity_band(3.0) == 'NEAR'

    def test_proximity_band_far(self):
        assert DistanceEstimator.proximity_band(10.0) == 'FAR'


class TestLocateTarget:
    """Test target matching."""

    def test_match_by_mac(self):
        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        device = MagicMock()
        device.device_id = 'other'
        device.address = 'AA:BB:CC:DD:EE:FF'
        device.name = None
        assert target.matches(device) is True

    def test_match_by_mac_case_insensitive(self):
        target = LocateTarget(mac_address='aa:bb:cc:dd:ee:ff')
        device = MagicMock()
        device.device_id = 'other'
        device.address = 'AA:BB:CC:DD:EE:FF'
        device.name = None
        assert target.matches(device) is True

    def test_match_by_mac_without_separators(self):
        target = LocateTarget(mac_address='aabbccddeeff')
        device = MagicMock()
        device.device_id = 'other'
        device.address = 'AA:BB:CC:DD:EE:FF'
        device.name = None
        assert target.matches(device) is True

    def test_match_by_name_pattern(self):
        target = LocateTarget(name_pattern='iPhone')
        device = MagicMock()
        device.device_id = 'other'
        device.address = '00:00:00:00:00:00'
        device.name = "John's iPhone 15"
        assert target.matches(device) is True

    def test_no_match(self):
        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        device = MagicMock()
        device.device_id = 'other'
        device.address = '11:22:33:44:55:66'
        device.name = None
        assert target.matches(device) is False

    def test_match_by_device_id(self):
        target = LocateTarget(device_id='my-device-123')
        device = MagicMock()
        device.device_id = 'my-device-123'
        device.address = '00:00:00:00:00:00'
        device.name = None
        assert target.matches(device) is True

    def test_to_dict(self):
        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF', known_name='Test')
        d = target.to_dict()
        assert d['mac_address'] == 'AA:BB:CC:DD:EE:FF'
        assert d['known_name'] == 'Test'


class TestLocateSession:
    """Test locate session lifecycle."""

    @patch('utils.bt_locate.get_bluetooth_scanner')
    def test_start_stop(self, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_get_scanner.return_value = mock_scanner

        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        session = LocateSession(target, Environment.OUTDOOR)
        session.start()

        assert session.active is True
        mock_scanner.add_device_callback.assert_called_once()

        session.stop()
        assert session.active is False
        mock_scanner.remove_device_callback.assert_called_once()

    @patch('utils.bt_locate.get_bluetooth_scanner')
    @patch('utils.bt_locate.get_current_position')
    def test_detection_creates_trail_point(self, mock_gps, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_get_scanner.return_value = mock_scanner
        mock_gps.return_value = None  # No GPS

        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        session = LocateSession(target, Environment.OUTDOOR)
        session.start()

        # Simulate device callback
        device = MagicMock()
        device.device_id = 'test'
        device.address = 'AA:BB:CC:DD:EE:FF'
        device.name = 'Test Device'
        device.rssi_current = -65

        session._on_device(device)

        assert session.detection_count == 1
        assert len(session.trail) == 1
        assert session.trail[0].rssi == -65

    @patch('utils.bt_locate.get_bluetooth_scanner')
    def test_non_matching_device_ignored(self, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_get_scanner.return_value = mock_scanner

        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        session = LocateSession(target, Environment.OUTDOOR)
        session.start()

        device = MagicMock()
        device.device_id = 'other'
        device.address = '11:22:33:44:55:66'
        device.name = None
        device.rssi_current = -70

        session._on_device(device)
        assert session.detection_count == 0

    @patch('utils.bt_locate.get_bluetooth_scanner')
    def test_get_status(self, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_get_scanner.return_value = mock_scanner

        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        session = LocateSession(target, Environment.FREE_SPACE)
        session.start()

        status = session.get_status()
        assert status['active'] is True
        assert status['environment'] == 'FREE_SPACE'
        assert status['detection_count'] == 0


class TestModuleLevelSessionManagement:
    """Test module-level session functions."""

    @patch('utils.bt_locate.get_bluetooth_scanner')
    def test_start_and_get_session(self, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_get_scanner.return_value = mock_scanner

        target = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        session = start_locate_session(target)

        assert get_locate_session() is session
        assert session.active is True

        stop_locate_session()
        assert get_locate_session() is None

    @patch('utils.bt_locate.get_bluetooth_scanner')
    def test_start_replaces_existing_session(self, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_get_scanner.return_value = mock_scanner

        target1 = LocateTarget(mac_address='AA:BB:CC:DD:EE:FF')
        session1 = start_locate_session(target1)

        target2 = LocateTarget(mac_address='11:22:33:44:55:66')
        session2 = start_locate_session(target2)

        assert get_locate_session() is session2
        assert session1.active is False
        assert session2.active is True

        stop_locate_session()

    @patch('utils.bt_locate.get_bluetooth_scanner')
    def test_start_raises_when_scanner_cannot_start(self, mock_get_scanner):
        mock_scanner = MagicMock()
        mock_scanner.is_scanning = False
        mock_scanner.start_scan.return_value = False
        status = MagicMock()
        status.error = 'No adapter'
        mock_scanner.get_status.return_value = status
        mock_get_scanner.return_value = mock_scanner

        with pytest.raises(RuntimeError):
            start_locate_session(LocateTarget(mac_address='AA:BB:CC:DD:EE:FF'))
