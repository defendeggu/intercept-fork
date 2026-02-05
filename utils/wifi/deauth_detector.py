"""
Deauthentication attack detector using scapy.

Monitors a WiFi interface in monitor mode for deauthentication and disassociation
frames, detecting potential deauth flood attacks.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Any

from utils.constants import (
    DEAUTH_DETECTION_WINDOW,
    DEAUTH_ALERT_THRESHOLD,
    DEAUTH_CRITICAL_THRESHOLD,
    DEAUTH_SNIFF_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Deauth reason code descriptions
DEAUTH_REASON_CODES = {
    0: "Reserved",
    1: "Unspecified reason",
    2: "Previous authentication no longer valid",
    3: "Station is leaving (or has left) IBSS or ESS",
    4: "Disassociated due to inactivity",
    5: "Disassociated because AP is unable to handle all currently associated STAs",
    6: "Class 2 frame received from nonauthenticated STA",
    7: "Class 3 frame received from nonassociated STA",
    8: "Disassociated because sending STA is leaving (or has left) BSS",
    9: "STA requesting (re)association is not authenticated with responding STA",
    10: "Disassociated because the information in the Power Capability element is unacceptable",
    11: "Disassociated because the information in the Supported Channels element is unacceptable",
    12: "Disassociated due to BSS Transition Management",
    13: "Invalid information element",
    14: "MIC failure",
    15: "4-Way Handshake timeout",
    16: "Group Key Handshake timeout",
    17: "Information element in 4-Way Handshake different from (Re)Association Request/Probe Response/Beacon frame",
    18: "Invalid group cipher",
    19: "Invalid pairwise cipher",
    20: "Invalid AKMP",
    21: "Unsupported RSNE version",
    22: "Invalid RSNE capabilities",
    23: "IEEE 802.1X authentication failed",
    24: "Cipher suite rejected because of security policy",
}


@dataclass
class DeauthPacketInfo:
    """Information about a captured deauth/disassoc packet."""
    timestamp: float
    frame_type: str  # 'deauth' or 'disassoc'
    src_mac: str
    dst_mac: str
    bssid: str
    reason_code: int
    signal_dbm: Optional[int] = None


@dataclass
class DeauthTracker:
    """Tracks deauth packets for a specific source/dest/bssid combination."""
    packets: list[DeauthPacketInfo] = field(default_factory=list)
    first_seen: float = 0.0
    last_seen: float = 0.0
    alert_sent: bool = False

    def add_packet(self, pkt: DeauthPacketInfo):
        self.packets.append(pkt)
        now = pkt.timestamp
        if self.first_seen == 0.0:
            self.first_seen = now
        self.last_seen = now

    def get_packets_in_window(self, window_seconds: float) -> list[DeauthPacketInfo]:
        """Get packets within the time window."""
        cutoff = time.time() - window_seconds
        return [p for p in self.packets if p.timestamp >= cutoff]

    def cleanup_old_packets(self, window_seconds: float):
        """Remove packets older than the window."""
        cutoff = time.time() - window_seconds
        self.packets = [p for p in self.packets if p.timestamp >= cutoff]
        if self.packets:
            self.first_seen = self.packets[0].timestamp
        else:
            self.first_seen = 0.0
            self.alert_sent = False


@dataclass
class DeauthAlert:
    """A deauthentication attack alert."""
    id: str
    timestamp: float
    severity: str  # 'low', 'medium', 'high'

    # Attacker info
    attacker_mac: str
    attacker_vendor: Optional[str]
    attacker_signal_dbm: Optional[int]
    is_spoofed_ap: bool

    # Target info
    target_mac: str
    target_vendor: Optional[str]
    target_type: str  # 'client', 'broadcast', 'ap'
    target_known_from_scan: bool

    # Access point info
    ap_bssid: str
    ap_essid: Optional[str]
    ap_channel: Optional[int]

    # Attack info
    frame_type: str
    reason_code: int
    reason_text: str
    packet_count: int
    window_seconds: float
    packets_per_second: float

    # Analysis
    attack_type: str  # 'targeted', 'broadcast', 'ap_flood'
    description: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'type': 'deauth_alert',
            'timestamp': self.timestamp,
            'severity': self.severity,
            'attacker': {
                'mac': self.attacker_mac,
                'vendor': self.attacker_vendor,
                'signal_dbm': self.attacker_signal_dbm,
                'is_spoofed_ap': self.is_spoofed_ap,
            },
            'target': {
                'mac': self.target_mac,
                'vendor': self.target_vendor,
                'type': self.target_type,
                'known_from_scan': self.target_known_from_scan,
            },
            'access_point': {
                'bssid': self.ap_bssid,
                'essid': self.ap_essid,
                'channel': self.ap_channel,
            },
            'attack_info': {
                'frame_type': self.frame_type,
                'reason_code': self.reason_code,
                'reason_text': self.reason_text,
                'packet_count': self.packet_count,
                'window_seconds': self.window_seconds,
                'packets_per_second': self.packets_per_second,
            },
            'analysis': {
                'attack_type': self.attack_type,
                'description': self.description,
            },
        }


class DeauthDetector:
    """
    Detects deauthentication attacks using scapy.

    Monitors a WiFi interface in monitor mode for deauth/disassoc frames
    and emits alerts when attack thresholds are exceeded.
    """

    def __init__(
        self,
        interface: str,
        event_callback: Callable[[dict], None],
        get_networks: Optional[Callable[[], dict[str, Any]]] = None,
        get_clients: Optional[Callable[[], dict[str, Any]]] = None,
    ):
        """
        Initialize the deauth detector.

        Args:
            interface: Monitor mode interface to sniff on
            event_callback: Callback function to receive alert events
            get_networks: Optional function to get current WiFi networks (bssid -> network_info)
            get_clients: Optional function to get current WiFi clients (mac -> client_info)
        """
        self.interface = interface
        self.event_callback = event_callback
        self.get_networks = get_networks
        self.get_clients = get_clients

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Track deauth packets by (src, dst, bssid) tuple
        self._trackers: dict[tuple[str, str, str], DeauthTracker] = defaultdict(DeauthTracker)

        # Alert history
        self._alerts: list[DeauthAlert] = []
        self._alert_counter = 0

        # Stats
        self._packets_captured = 0
        self._alerts_generated = 0
        self._started_at: Optional[float] = None

    @property
    def is_running(self) -> bool:
        """Check if detector is running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def stats(self) -> dict:
        """Get detector statistics."""
        return {
            'is_running': self.is_running,
            'interface': self.interface,
            'started_at': self._started_at,
            'packets_captured': self._packets_captured,
            'alerts_generated': self._alerts_generated,
            'active_trackers': len(self._trackers),
        }

    def start(self) -> bool:
        """
        Start detection in background thread.

        Returns:
            True if started successfully.
        """
        if self.is_running:
            logger.warning("Deauth detector already running")
            return True

        self._stop_event.clear()
        self._started_at = time.time()

        self._thread = threading.Thread(
            target=self._sniff_loop,
            name="DeauthDetector",
            daemon=True,
        )
        self._thread.start()

        logger.info(f"Deauth detector started on {self.interface}")
        return True

    def stop(self) -> bool:
        """
        Stop detection.

        Returns:
            True if stopped successfully.
        """
        if not self.is_running:
            return True

        logger.info("Stopping deauth detector...")
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("Deauth detector thread did not stop cleanly")
            self._thread = None

        self._started_at = None
        logger.info("Deauth detector stopped")
        return True

    def get_alerts(self, limit: int = 100) -> list[dict]:
        """Get recent alerts."""
        with self._lock:
            return [a.to_dict() for a in self._alerts[-limit:]]

    def clear_alerts(self):
        """Clear alert history."""
        with self._lock:
            self._alerts.clear()
            self._trackers.clear()
            self._alert_counter = 0

    def _sniff_loop(self):
        """Main sniffing loop using scapy."""
        try:
            from scapy.all import sniff, Dot11, Dot11Deauth, Dot11Disas
        except ImportError:
            logger.error("scapy not installed. Install with: pip install scapy")
            self.event_callback({
                'type': 'deauth_error',
                'error': 'scapy not installed',
            })
            return

        logger.info(f"Starting deauth sniff on {self.interface}")

        def packet_handler(pkt):
            """Handle each captured packet."""
            if self._stop_event.is_set():
                return

            # Check for deauth or disassoc frames
            if pkt.haslayer(Dot11Deauth) or pkt.haslayer(Dot11Disas):
                self._process_deauth_packet(pkt)

        try:
            # Use stop_filter to allow clean shutdown
            sniff(
                iface=self.interface,
                prn=packet_handler,
                store=False,
                stop_filter=lambda _: self._stop_event.is_set(),
                timeout=DEAUTH_SNIFF_TIMEOUT,
            )

            # Continue sniffing until stop is requested
            while not self._stop_event.is_set():
                sniff(
                    iface=self.interface,
                    prn=packet_handler,
                    store=False,
                    stop_filter=lambda _: self._stop_event.is_set(),
                    timeout=DEAUTH_SNIFF_TIMEOUT,
                )
                # Periodic cleanup
                self._cleanup_old_trackers()

        except OSError as e:
            if "No such device" in str(e):
                logger.error(f"Interface {self.interface} not found")
                self.event_callback({
                    'type': 'deauth_error',
                    'error': f'Interface {self.interface} not found',
                })
            else:
                logger.exception(f"Sniff error: {e}")
                self.event_callback({
                    'type': 'deauth_error',
                    'error': str(e),
                })
        except Exception as e:
            logger.exception(f"Sniff error: {e}")
            self.event_callback({
                'type': 'deauth_error',
                'error': str(e),
            })

    def _process_deauth_packet(self, pkt):
        """Process a deauth/disassoc packet and emit alert if threshold exceeded."""
        try:
            from scapy.all import Dot11, Dot11Deauth, Dot11Disas, RadioTap
        except ImportError:
            return

        # Determine frame type
        if pkt.haslayer(Dot11Deauth):
            frame_type = 'deauth'
            reason_code = pkt[Dot11Deauth].reason
        elif pkt.haslayer(Dot11Disas):
            frame_type = 'disassoc'
            reason_code = pkt[Dot11Disas].reason
        else:
            return

        # Extract addresses from Dot11 layer
        dot11 = pkt[Dot11]
        dst_mac = (dot11.addr1 or '').upper()
        src_mac = (dot11.addr2 or '').upper()
        bssid = (dot11.addr3 or '').upper()

        # Skip if addresses are missing
        if not src_mac or not dst_mac:
            return

        # Extract signal strength from RadioTap if available
        signal_dbm = None
        if pkt.haslayer(RadioTap):
            try:
                signal_dbm = pkt[RadioTap].dBm_AntSignal
            except AttributeError:
                pass

        # Create packet info
        pkt_info = DeauthPacketInfo(
            timestamp=time.time(),
            frame_type=frame_type,
            src_mac=src_mac,
            dst_mac=dst_mac,
            bssid=bssid,
            reason_code=reason_code,
            signal_dbm=signal_dbm,
        )

        self._packets_captured += 1

        # Track packet
        tracker_key = (src_mac, dst_mac, bssid)
        with self._lock:
            tracker = self._trackers[tracker_key]
            tracker.add_packet(pkt_info)

            # Check if threshold exceeded
            packets_in_window = tracker.get_packets_in_window(DEAUTH_DETECTION_WINDOW)
            packet_count = len(packets_in_window)

            if packet_count >= DEAUTH_ALERT_THRESHOLD and not tracker.alert_sent:
                # Generate alert
                alert = self._generate_alert(
                    tracker_key=tracker_key,
                    packets=packets_in_window,
                    packet_count=packet_count,
                )

                self._alerts.append(alert)
                self._alerts_generated += 1
                tracker.alert_sent = True

                # Emit event
                self.event_callback(alert.to_dict())

                logger.warning(
                    f"Deauth attack detected: {src_mac} -> {dst_mac} "
                    f"({packet_count} packets in {DEAUTH_DETECTION_WINDOW}s)"
                )

    def _generate_alert(
        self,
        tracker_key: tuple[str, str, str],
        packets: list[DeauthPacketInfo],
        packet_count: int,
    ) -> DeauthAlert:
        """Generate an alert from tracked packets."""
        src_mac, dst_mac, bssid = tracker_key

        # Get latest packet for details
        latest_pkt = packets[-1] if packets else None

        # Determine severity
        if packet_count >= DEAUTH_CRITICAL_THRESHOLD:
            severity = 'high'
        elif packet_count >= DEAUTH_ALERT_THRESHOLD * 2.5:
            severity = 'medium'
        else:
            severity = 'low'

        # Lookup AP info
        ap_info = self._lookup_ap(bssid)

        # Lookup target info
        target_info = self._lookup_device(dst_mac)

        # Determine target type
        if dst_mac == 'FF:FF:FF:FF:FF:FF':
            target_type = 'broadcast'
        elif dst_mac in self._get_known_aps():
            target_type = 'ap'
        else:
            target_type = 'client'

        # Check if source is spoofed (matches known AP)
        is_spoofed = self._check_spoofed_source(src_mac)

        # Get attacker vendor
        attacker_vendor = self._get_vendor(src_mac)

        # Calculate packets per second
        if packets:
            time_span = packets[-1].timestamp - packets[0].timestamp
            pps = packet_count / time_span if time_span > 0 else float(packet_count)
        else:
            pps = 0.0

        # Determine attack type and description
        if dst_mac == 'FF:FF:FF:FF:FF:FF':
            attack_type = 'broadcast'
            description = "Broadcast deauth flood targeting all clients on the network"
        elif target_type == 'ap':
            attack_type = 'ap_flood'
            description = "Deauth flood targeting access point"
        else:
            attack_type = 'targeted'
            description = f"Targeted deauth flood against {'known' if target_info.get('known_from_scan') else 'unknown'} client"

        # Get reason code info
        reason_code = latest_pkt.reason_code if latest_pkt else 0
        reason_text = DEAUTH_REASON_CODES.get(reason_code, f"Unknown ({reason_code})")

        # Get signal
        signal_dbm = None
        for pkt in reversed(packets):
            if pkt.signal_dbm is not None:
                signal_dbm = pkt.signal_dbm
                break

        # Generate unique ID
        self._alert_counter += 1
        alert_id = f"deauth-{int(time.time())}-{self._alert_counter}"

        return DeauthAlert(
            id=alert_id,
            timestamp=time.time(),
            severity=severity,
            attacker_mac=src_mac,
            attacker_vendor=attacker_vendor,
            attacker_signal_dbm=signal_dbm,
            is_spoofed_ap=is_spoofed,
            target_mac=dst_mac,
            target_vendor=target_info.get('vendor'),
            target_type=target_type,
            target_known_from_scan=target_info.get('known_from_scan', False),
            ap_bssid=bssid,
            ap_essid=ap_info.get('essid'),
            ap_channel=ap_info.get('channel'),
            frame_type=latest_pkt.frame_type if latest_pkt else 'deauth',
            reason_code=reason_code,
            reason_text=reason_text,
            packet_count=packet_count,
            window_seconds=DEAUTH_DETECTION_WINDOW,
            packets_per_second=round(pps, 1),
            attack_type=attack_type,
            description=description,
        )

    def _lookup_ap(self, bssid: str) -> dict:
        """Get AP info from current scan data."""
        if not self.get_networks:
            return {'bssid': bssid, 'essid': None, 'channel': None}

        try:
            networks = self.get_networks()
            ap = networks.get(bssid.upper())
            if ap:
                return {
                    'bssid': bssid,
                    'essid': ap.get('essid') or ap.get('ssid'),
                    'channel': ap.get('channel'),
                }
        except Exception as e:
            logger.debug(f"Error looking up AP {bssid}: {e}")

        return {'bssid': bssid, 'essid': None, 'channel': None}

    def _lookup_device(self, mac: str) -> dict:
        """Get device info and vendor from MAC."""
        vendor = self._get_vendor(mac)
        known_from_scan = False

        if self.get_clients:
            try:
                clients = self.get_clients()
                if mac.upper() in clients:
                    known_from_scan = True
            except Exception:
                pass

        return {
            'mac': mac,
            'vendor': vendor,
            'known_from_scan': known_from_scan,
        }

    def _get_known_aps(self) -> set[str]:
        """Get set of known AP BSSIDs."""
        if not self.get_networks:
            return set()

        try:
            networks = self.get_networks()
            return {bssid.upper() for bssid in networks.keys()}
        except Exception:
            return set()

    def _check_spoofed_source(self, src_mac: str) -> bool:
        """Check if source MAC matches a known AP (spoofing indicator)."""
        return src_mac.upper() in self._get_known_aps()

    def _get_vendor(self, mac: str) -> Optional[str]:
        """Get vendor from MAC OUI."""
        try:
            from data.oui import get_manufacturer
            vendor = get_manufacturer(mac)
            return vendor if vendor != 'Unknown' else None
        except Exception:
            pass

        # Fallback to wifi constants
        try:
            from utils.wifi.constants import get_vendor_from_mac
            return get_vendor_from_mac(mac)
        except Exception:
            return None

    def _cleanup_old_trackers(self):
        """Remove old packets and empty trackers."""
        with self._lock:
            keys_to_remove = []
            for key, tracker in self._trackers.items():
                tracker.cleanup_old_packets(DEAUTH_DETECTION_WINDOW * 2)
                if not tracker.packets:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._trackers[key]
