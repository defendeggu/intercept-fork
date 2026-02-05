"""
Unit tests for deauthentication attack detector.
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.wifi.deauth_detector import (
    DeauthDetector,
    DeauthPacketInfo,
    DeauthTracker,
    DeauthAlert,
    DEAUTH_REASON_CODES,
)
from utils.constants import (
    DEAUTH_DETECTION_WINDOW,
    DEAUTH_ALERT_THRESHOLD,
    DEAUTH_CRITICAL_THRESHOLD,
)


class TestDeauthPacketInfo:
    """Tests for DeauthPacketInfo dataclass."""

    def test_creation(self):
        """Test basic creation of packet info."""
        pkt = DeauthPacketInfo(
            timestamp=1234567890.0,
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='AA:BB:CC:DD:EE:FF',
            reason_code=7,
            signal_dbm=-45,
        )

        assert pkt.frame_type == 'deauth'
        assert pkt.src_mac == 'AA:BB:CC:DD:EE:FF'
        assert pkt.reason_code == 7
        assert pkt.signal_dbm == -45


class TestDeauthTracker:
    """Tests for DeauthTracker."""

    def test_add_packet(self):
        """Test adding packets to tracker."""
        tracker = DeauthTracker()

        pkt1 = DeauthPacketInfo(
            timestamp=100.0,
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='AA:BB:CC:DD:EE:FF',
            reason_code=7,
        )
        tracker.add_packet(pkt1)

        assert len(tracker.packets) == 1
        assert tracker.first_seen == 100.0
        assert tracker.last_seen == 100.0

    def test_multiple_packets(self):
        """Test adding multiple packets."""
        tracker = DeauthTracker()

        for i in range(5):
            pkt = DeauthPacketInfo(
                timestamp=100.0 + i,
                frame_type='deauth',
                src_mac='AA:BB:CC:DD:EE:FF',
                dst_mac='11:22:33:44:55:66',
                bssid='AA:BB:CC:DD:EE:FF',
                reason_code=7,
            )
            tracker.add_packet(pkt)

        assert len(tracker.packets) == 5
        assert tracker.first_seen == 100.0
        assert tracker.last_seen == 104.0

    def test_get_packets_in_window(self):
        """Test filtering packets by time window."""
        tracker = DeauthTracker()
        now = time.time()

        # Add old packet
        tracker.add_packet(DeauthPacketInfo(
            timestamp=now - 10,
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='AA:BB:CC:DD:EE:FF',
            reason_code=7,
        ))

        # Add recent packets
        for i in range(3):
            tracker.add_packet(DeauthPacketInfo(
                timestamp=now - i,
                frame_type='deauth',
                src_mac='AA:BB:CC:DD:EE:FF',
                dst_mac='11:22:33:44:55:66',
                bssid='AA:BB:CC:DD:EE:FF',
                reason_code=7,
            ))

        # 5-second window should only include the 3 recent packets
        in_window = tracker.get_packets_in_window(5.0)
        assert len(in_window) == 3

    def test_cleanup_old_packets(self):
        """Test removing old packets."""
        tracker = DeauthTracker()
        now = time.time()

        # Add old packet
        tracker.add_packet(DeauthPacketInfo(
            timestamp=now - 20,
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='AA:BB:CC:DD:EE:FF',
            reason_code=7,
        ))

        # Add recent packet
        tracker.add_packet(DeauthPacketInfo(
            timestamp=now,
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='AA:BB:CC:DD:EE:FF',
            reason_code=7,
        ))

        tracker.alert_sent = True

        # Cleanup with 10-second window
        tracker.cleanup_old_packets(10.0)

        assert len(tracker.packets) == 1
        assert tracker.packets[0].timestamp == now

    def test_cleanup_resets_alert_sent(self):
        """Test that cleanup resets alert_sent when all packets removed."""
        tracker = DeauthTracker()
        now = time.time()

        tracker.add_packet(DeauthPacketInfo(
            timestamp=now - 100,  # Very old
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='AA:BB:CC:DD:EE:FF',
            reason_code=7,
        ))

        tracker.alert_sent = True

        # Cleanup should remove all packets
        tracker.cleanup_old_packets(10.0)

        assert len(tracker.packets) == 0
        assert tracker.alert_sent is False


class TestDeauthAlert:
    """Tests for DeauthAlert."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        alert = DeauthAlert(
            id='deauth-123-1',
            timestamp=1234567890.0,
            severity='high',
            attacker_mac='AA:BB:CC:DD:EE:FF',
            attacker_vendor='Unknown',
            attacker_signal_dbm=-45,
            is_spoofed_ap=True,
            target_mac='11:22:33:44:55:66',
            target_vendor='Apple',
            target_type='client',
            target_known_from_scan=True,
            ap_bssid='AA:BB:CC:DD:EE:FF',
            ap_essid='TestNetwork',
            ap_channel=6,
            frame_type='deauth',
            reason_code=7,
            reason_text='Class 3 frame received from nonassociated STA',
            packet_count=50,
            window_seconds=5.0,
            packets_per_second=10.0,
            attack_type='targeted',
            description='Targeted deauth flood against known client',
        )

        d = alert.to_dict()

        assert d['id'] == 'deauth-123-1'
        assert d['type'] == 'deauth_alert'
        assert d['severity'] == 'high'
        assert d['attacker']['mac'] == 'AA:BB:CC:DD:EE:FF'
        assert d['attacker']['is_spoofed_ap'] is True
        assert d['target']['type'] == 'client'
        assert d['access_point']['essid'] == 'TestNetwork'
        assert d['attack_info']['packet_count'] == 50
        assert d['analysis']['attack_type'] == 'targeted'


class TestDeauthDetector:
    """Tests for DeauthDetector."""

    def test_init(self):
        """Test detector initialization."""
        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        assert detector.interface == 'wlan0mon'
        assert detector.event_callback == callback
        assert not detector.is_running

    def test_stats(self):
        """Test stats property."""
        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        stats = detector.stats
        assert stats['is_running'] is False
        assert stats['interface'] == 'wlan0mon'
        assert stats['packets_captured'] == 0
        assert stats['alerts_generated'] == 0

    def test_get_alerts_empty(self):
        """Test getting alerts when none exist."""
        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        alerts = detector.get_alerts()
        assert alerts == []

    def test_clear_alerts(self):
        """Test clearing alerts."""
        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        # Add a mock alert
        detector._alerts.append(MagicMock())
        detector._trackers[('A', 'B', 'C')] = DeauthTracker()
        detector._alert_counter = 5

        detector.clear_alerts()

        assert len(detector._alerts) == 0
        assert len(detector._trackers) == 0
        assert detector._alert_counter == 0

    @patch('utils.wifi.deauth_detector.time.time')
    def test_generate_alert_severity_low(self, mock_time):
        """Test alert generation with low severity."""
        mock_time.return_value = 1000.0

        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        # Create packets just at threshold
        packets = []
        for i in range(DEAUTH_ALERT_THRESHOLD):
            packets.append(DeauthPacketInfo(
                timestamp=1000.0 - (DEAUTH_ALERT_THRESHOLD - 1 - i) * 0.1,
                frame_type='deauth',
                src_mac='AA:BB:CC:DD:EE:FF',
                dst_mac='11:22:33:44:55:66',
                bssid='99:88:77:66:55:44',
                reason_code=7,
                signal_dbm=-50,
            ))

        alert = detector._generate_alert(
            tracker_key=('AA:BB:CC:DD:EE:FF', '11:22:33:44:55:66', '99:88:77:66:55:44'),
            packets=packets,
            packet_count=DEAUTH_ALERT_THRESHOLD,
        )

        assert alert.severity == 'low'
        assert alert.packet_count == DEAUTH_ALERT_THRESHOLD

    @patch('utils.wifi.deauth_detector.time.time')
    def test_generate_alert_severity_high(self, mock_time):
        """Test alert generation with high severity."""
        mock_time.return_value = 1000.0

        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        # Create packets above critical threshold
        packets = []
        for i in range(DEAUTH_CRITICAL_THRESHOLD):
            packets.append(DeauthPacketInfo(
                timestamp=1000.0 - (DEAUTH_CRITICAL_THRESHOLD - 1 - i) * 0.1,
                frame_type='deauth',
                src_mac='AA:BB:CC:DD:EE:FF',
                dst_mac='11:22:33:44:55:66',
                bssid='99:88:77:66:55:44',
                reason_code=7,
            ))

        alert = detector._generate_alert(
            tracker_key=('AA:BB:CC:DD:EE:FF', '11:22:33:44:55:66', '99:88:77:66:55:44'),
            packets=packets,
            packet_count=DEAUTH_CRITICAL_THRESHOLD,
        )

        assert alert.severity == 'high'

    @patch('utils.wifi.deauth_detector.time.time')
    def test_generate_alert_broadcast_attack(self, mock_time):
        """Test alert classification for broadcast attack."""
        mock_time.return_value = 1000.0

        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        packets = [DeauthPacketInfo(
            timestamp=999.9,
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='FF:FF:FF:FF:FF:FF',  # Broadcast
            bssid='99:88:77:66:55:44',
            reason_code=7,
        )]

        alert = detector._generate_alert(
            tracker_key=('AA:BB:CC:DD:EE:FF', 'FF:FF:FF:FF:FF:FF', '99:88:77:66:55:44'),
            packets=packets,
            packet_count=10,
        )

        assert alert.attack_type == 'broadcast'
        assert alert.target_type == 'broadcast'
        assert 'all clients' in alert.description.lower()

    def test_lookup_ap_no_callback(self):
        """Test AP lookup when no callback is provided."""
        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
            get_networks=None,
        )

        result = detector._lookup_ap('AA:BB:CC:DD:EE:FF')

        assert result['bssid'] == 'AA:BB:CC:DD:EE:FF'
        assert result['essid'] is None
        assert result['channel'] is None

    def test_lookup_ap_with_callback(self):
        """Test AP lookup with callback."""
        callback = MagicMock()
        get_networks = MagicMock(return_value={
            'AA:BB:CC:DD:EE:FF': {'essid': 'TestNet', 'channel': 6}
        })

        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
            get_networks=get_networks,
        )

        result = detector._lookup_ap('AA:BB:CC:DD:EE:FF')

        assert result['bssid'] == 'AA:BB:CC:DD:EE:FF'
        assert result['essid'] == 'TestNet'
        assert result['channel'] == 6

    def test_check_spoofed_source(self):
        """Test detection of spoofed AP source."""
        callback = MagicMock()
        get_networks = MagicMock(return_value={
            'AA:BB:CC:DD:EE:FF': {'essid': 'TestNet'}
        })

        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
            get_networks=get_networks,
        )

        # Source matches known AP - spoofed
        assert detector._check_spoofed_source('AA:BB:CC:DD:EE:FF') is True

        # Source does not match any AP - not spoofed
        assert detector._check_spoofed_source('11:22:33:44:55:66') is False

    def test_cleanup_old_trackers(self):
        """Test cleanup of old trackers."""
        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        now = time.time()

        # Add an old tracker
        old_tracker = DeauthTracker()
        old_tracker.add_packet(DeauthPacketInfo(
            timestamp=now - 100,  # Very old
            frame_type='deauth',
            src_mac='AA:BB:CC:DD:EE:FF',
            dst_mac='11:22:33:44:55:66',
            bssid='99:88:77:66:55:44',
            reason_code=7,
        ))
        detector._trackers[('AA:BB:CC:DD:EE:FF', '11:22:33:44:55:66', '99:88:77:66:55:44')] = old_tracker

        # Add a recent tracker
        recent_tracker = DeauthTracker()
        recent_tracker.add_packet(DeauthPacketInfo(
            timestamp=now,
            frame_type='deauth',
            src_mac='BB:CC:DD:EE:FF:AA',
            dst_mac='22:33:44:55:66:77',
            bssid='88:77:66:55:44:33',
            reason_code=7,
        ))
        detector._trackers[('BB:CC:DD:EE:FF:AA', '22:33:44:55:66:77', '88:77:66:55:44:33')] = recent_tracker

        detector._cleanup_old_trackers()

        # Old tracker should be removed
        assert ('AA:BB:CC:DD:EE:FF', '11:22:33:44:55:66', '99:88:77:66:55:44') not in detector._trackers
        # Recent tracker should remain
        assert ('BB:CC:DD:EE:FF:AA', '22:33:44:55:66:77', '88:77:66:55:44:33') in detector._trackers


class TestReasonCodes:
    """Tests for reason code dictionary."""

    def test_common_reason_codes(self):
        """Test that common reason codes are defined."""
        assert 1 in DEAUTH_REASON_CODES  # Unspecified
        assert 7 in DEAUTH_REASON_CODES  # Class 3 frame
        assert 14 in DEAUTH_REASON_CODES  # MIC failure

    def test_reason_code_descriptions(self):
        """Test reason code descriptions are strings."""
        for code, desc in DEAUTH_REASON_CODES.items():
            assert isinstance(code, int)
            assert isinstance(desc, str)
            assert len(desc) > 0


class TestDeauthDetectorIntegration:
    """Integration tests for DeauthDetector with mocked scapy."""

    @patch('utils.wifi.deauth_detector.time.time')
    def test_process_deauth_packet_generates_alert(self, mock_time):
        """Test that processing packets generates alert when threshold exceeded."""
        mock_time.return_value = 1000.0

        callback = MagicMock()
        detector = DeauthDetector(
            interface='wlan0mon',
            event_callback=callback,
        )

        # Create a mock scapy packet
        mock_pkt = MagicMock()

        # Mock Dot11Deauth layer
        mock_deauth = MagicMock()
        mock_deauth.reason = 7

        # Mock Dot11 layer
        mock_dot11 = MagicMock()
        mock_dot11.addr1 = '11:22:33:44:55:66'  # dst
        mock_dot11.addr2 = 'AA:BB:CC:DD:EE:FF'  # src
        mock_dot11.addr3 = '99:88:77:66:55:44'  # bssid

        # Mock RadioTap layer
        mock_radiotap = MagicMock()
        mock_radiotap.dBm_AntSignal = -50

        # Set up haslayer behavior
        def haslayer_side_effect(layer):
            if 'Dot11Deauth' in str(layer):
                return True
            if 'Dot11Disas' in str(layer):
                return False
            if 'RadioTap' in str(layer):
                return True
            return False

        mock_pkt.haslayer = haslayer_side_effect

        # Set up __getitem__ behavior
        def getitem_side_effect(layer):
            if 'Dot11Deauth' in str(layer):
                return mock_deauth
            if 'Dot11' in str(layer) and 'Deauth' not in str(layer):
                return mock_dot11
            if 'RadioTap' in str(layer):
                return mock_radiotap
            return MagicMock()

        mock_pkt.__getitem__ = getitem_side_effect

        # Patch the scapy imports inside _process_deauth_packet
        with patch('utils.wifi.deauth_detector.DeauthDetector._process_deauth_packet.__globals__', {
            'Dot11': MagicMock,
            'Dot11Deauth': MagicMock,
            'Dot11Disas': MagicMock,
            'RadioTap': MagicMock,
        }):
            # Process enough packets to trigger alert
            for i in range(DEAUTH_ALERT_THRESHOLD + 5):
                mock_time.return_value = 1000.0 + i * 0.1

                # Manually simulate what _process_deauth_packet does
                pkt_info = DeauthPacketInfo(
                    timestamp=mock_time.return_value,
                    frame_type='deauth',
                    src_mac='AA:BB:CC:DD:EE:FF',
                    dst_mac='11:22:33:44:55:66',
                    bssid='99:88:77:66:55:44',
                    reason_code=7,
                    signal_dbm=-50,
                )

                detector._packets_captured += 1

                tracker_key = ('AA:BB:CC:DD:EE:FF', '11:22:33:44:55:66', '99:88:77:66:55:44')
                tracker = detector._trackers[tracker_key]
                tracker.add_packet(pkt_info)

                packets_in_window = tracker.get_packets_in_window(DEAUTH_DETECTION_WINDOW)
                packet_count = len(packets_in_window)

                if packet_count >= DEAUTH_ALERT_THRESHOLD and not tracker.alert_sent:
                    alert = detector._generate_alert(
                        tracker_key=tracker_key,
                        packets=packets_in_window,
                        packet_count=packet_count,
                    )
                    detector._alerts.append(alert)
                    detector._alerts_generated += 1
                    tracker.alert_sent = True
                    detector.event_callback(alert.to_dict())

        # Verify alert was generated
        assert detector._alerts_generated == 1
        assert len(detector._alerts) == 1
        assert callback.called

        # Verify callback was called with alert data
        call_args = callback.call_args[0][0]
        assert call_args['type'] == 'deauth_alert'
        assert call_args['attacker']['mac'] == 'AA:BB:CC:DD:EE:FF'
        assert call_args['target']['mac'] == '11:22:33:44:55:66'
