"""
Hidden SSID correlation engine.

Correlates probe requests from clients with hidden access points to reveal
the actual SSID of hidden networks.

Strategy:
1. Track probe requests with source MACs and probed SSIDs
2. Track hidden networks (empty ESSID) with their BSSIDs
3. When a client probes for an SSID and then associates with a hidden AP
   within a time window, correlate the SSID to the hidden AP
4. Also correlate when the same client is seen both probing for an SSID
   and sending data to a hidden AP
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from .constants import (
    HIDDEN_CORRELATION_WINDOW_SECONDS,
    HIDDEN_MIN_CORRELATION_CONFIDENCE,
)

logger = logging.getLogger(__name__)

# Global correlator instance
_correlator_instance: Optional['HiddenSSIDCorrelator'] = None
_correlator_lock = threading.Lock()


@dataclass
class ProbeRecord:
    """Record of a probe request."""
    timestamp: datetime
    client_mac: str
    probed_ssid: str


@dataclass
class AssociationRecord:
    """Record of a client association."""
    timestamp: datetime
    client_mac: str
    bssid: str


@dataclass
class CorrelationResult:
    """Result of an SSID correlation."""
    bssid: str
    revealed_ssid: str
    client_mac: str
    confidence: float
    correlation_time: datetime
    method: str  # 'probe_association', 'data_correlation'


class HiddenSSIDCorrelator:
    """
    Correlates probe requests with hidden APs to reveal their SSIDs.

    Uses time-based correlation: when a client probes for an SSID and
    then is seen communicating with a hidden AP, the SSID is likely
    that of the hidden network.
    """

    def __init__(
        self,
        correlation_window: float = HIDDEN_CORRELATION_WINDOW_SECONDS,
        min_confidence: float = HIDDEN_MIN_CORRELATION_CONFIDENCE,
    ):
        """
        Initialize the correlator.

        Args:
            correlation_window: Time window for correlation (seconds).
            min_confidence: Minimum confidence to report a correlation.
        """
        self.correlation_window = correlation_window
        self.min_confidence = min_confidence
        self._lock = threading.Lock()

        # Storage
        self._probe_records: list[ProbeRecord] = []
        self._association_records: list[AssociationRecord] = []
        self._hidden_aps: dict[str, datetime] = {}  # BSSID -> last_seen
        self._revealed: dict[str, CorrelationResult] = {}  # BSSID -> result

        # Callbacks
        self._on_ssid_revealed: Optional[Callable[[CorrelationResult], None]] = None

    def record_probe(self, client_mac: str, probed_ssid: str, timestamp: Optional[datetime] = None):
        """
        Record a probe request.

        Args:
            client_mac: MAC address of the probing client.
            probed_ssid: SSID being probed for.
            timestamp: Time of the probe (defaults to now).
        """
        if not client_mac or not probed_ssid:
            return

        timestamp = timestamp or datetime.now()
        client_mac = client_mac.upper()

        with self._lock:
            self._probe_records.append(ProbeRecord(
                timestamp=timestamp,
                client_mac=client_mac,
                probed_ssid=probed_ssid,
            ))

            # Prune old records
            self._prune_records()

            # Check for correlations with known hidden APs
            self._check_correlations()

    def record_association(self, client_mac: str, bssid: str, timestamp: Optional[datetime] = None):
        """
        Record a client association with an AP.

        Args:
            client_mac: MAC address of the client.
            bssid: BSSID of the AP.
            timestamp: Time of the association (defaults to now).
        """
        if not client_mac or not bssid:
            return

        timestamp = timestamp or datetime.now()
        client_mac = client_mac.upper()
        bssid = bssid.upper()

        with self._lock:
            self._association_records.append(AssociationRecord(
                timestamp=timestamp,
                client_mac=client_mac,
                bssid=bssid,
            ))

            # Prune old records
            self._prune_records()

            # Check for correlations
            self._check_correlations()

    def record_hidden_ap(self, bssid: str, timestamp: Optional[datetime] = None):
        """
        Record a hidden access point (empty SSID).

        Args:
            bssid: BSSID of the hidden AP.
            timestamp: Time when seen (defaults to now).
        """
        if not bssid:
            return

        timestamp = timestamp or datetime.now()
        bssid = bssid.upper()

        with self._lock:
            self._hidden_aps[bssid] = timestamp

            # Check for correlations
            self._check_correlations()

    def get_revealed_ssid(self, bssid: str) -> Optional[str]:
        """
        Get the revealed SSID for a hidden AP, if known.

        Args:
            bssid: BSSID to look up.

        Returns:
            Revealed SSID or None.
        """
        with self._lock:
            result = self._revealed.get(bssid.upper())
            return result.revealed_ssid if result else None

    def get_correlation(self, bssid: str) -> Optional[CorrelationResult]:
        """
        Get the full correlation result for a hidden AP.

        Args:
            bssid: BSSID to look up.

        Returns:
            CorrelationResult or None.
        """
        with self._lock:
            return self._revealed.get(bssid.upper())

    def get_all_revealed(self) -> dict[str, str]:
        """
        Get all revealed SSID mappings.

        Returns:
            Dict of BSSID -> revealed SSID.
        """
        with self._lock:
            return {
                bssid: result.revealed_ssid
                for bssid, result in self._revealed.items()
            }

    def set_callback(self, callback: Callable[[CorrelationResult], None]):
        """Set callback for when an SSID is revealed."""
        self._on_ssid_revealed = callback

    def _prune_records(self):
        """Remove records older than the correlation window."""
        cutoff = datetime.now() - timedelta(seconds=self.correlation_window * 2)

        self._probe_records = [
            r for r in self._probe_records
            if r.timestamp > cutoff
        ]

        self._association_records = [
            r for r in self._association_records
            if r.timestamp > cutoff
        ]

    def _check_correlations(self):
        """Check for new SSID correlations."""
        now = datetime.now()
        window = timedelta(seconds=self.correlation_window)

        for bssid in list(self._hidden_aps.keys()):
            # Skip if already revealed
            if bssid in self._revealed:
                continue

            # Find associations with this hidden AP
            relevant_associations = [
                a for a in self._association_records
                if a.bssid == bssid and (now - a.timestamp) <= window
            ]

            if not relevant_associations:
                continue

            # For each associated client, look for recent probes
            for assoc in relevant_associations:
                client_probes = [
                    p for p in self._probe_records
                    if p.client_mac == assoc.client_mac
                    and abs((p.timestamp - assoc.timestamp).total_seconds()) <= self.correlation_window
                ]

                if not client_probes:
                    continue

                # Use the most recent probe from this client
                latest_probe = max(client_probes, key=lambda p: p.timestamp)

                # Calculate confidence based on timing
                time_diff = abs((latest_probe.timestamp - assoc.timestamp).total_seconds())
                confidence = 1.0 - (time_diff / self.correlation_window)
                confidence = max(0.0, min(1.0, confidence))

                if confidence >= self.min_confidence:
                    result = CorrelationResult(
                        bssid=bssid,
                        revealed_ssid=latest_probe.probed_ssid,
                        client_mac=assoc.client_mac,
                        confidence=confidence,
                        correlation_time=now,
                        method='probe_association',
                    )

                    self._revealed[bssid] = result

                    logger.info(
                        f"Hidden SSID revealed: {bssid} -> '{latest_probe.probed_ssid}' "
                        f"(confidence: {confidence:.2f})"
                    )

                    # Callback
                    if self._on_ssid_revealed:
                        try:
                            self._on_ssid_revealed(result)
                        except Exception as e:
                            logger.debug(f"SSID reveal callback error: {e}")

                    break  # Found correlation, move to next AP

    def clear(self):
        """Clear all stored data."""
        with self._lock:
            self._probe_records.clear()
            self._association_records.clear()
            self._hidden_aps.clear()
            self._revealed.clear()


def get_hidden_correlator(
    correlation_window: float = HIDDEN_CORRELATION_WINDOW_SECONDS,
    min_confidence: float = HIDDEN_MIN_CORRELATION_CONFIDENCE,
) -> HiddenSSIDCorrelator:
    """
    Get or create the global hidden SSID correlator instance.

    Args:
        correlation_window: Time window for correlation.
        min_confidence: Minimum confidence threshold.

    Returns:
        HiddenSSIDCorrelator instance.
    """
    global _correlator_instance

    with _correlator_lock:
        if _correlator_instance is None:
            _correlator_instance = HiddenSSIDCorrelator(
                correlation_window=correlation_window,
                min_confidence=min_confidence,
            )
        return _correlator_instance
