"""Match ACARS/VDL2 messages to ADS-B aircraft by callsign."""

from __future__ import annotations

import time
from collections import deque


class FlightCorrelator:
    """Correlate ACARS and VDL2 messages with ADS-B aircraft."""

    def __init__(self, max_messages: int = 1000):
        self._acars_messages: deque[dict] = deque(maxlen=max_messages)
        self._vdl2_messages: deque[dict] = deque(maxlen=max_messages)

    def add_acars_message(self, msg: dict) -> None:
        self._acars_messages.append({
            **msg,
            '_corr_time': time.time(),
        })

    def add_vdl2_message(self, msg: dict) -> None:
        self._vdl2_messages.append({
            **msg,
            '_corr_time': time.time(),
        })

    def get_messages_for_aircraft(
        self, icao: str | None = None, callsign: str | None = None
    ) -> dict[str, list[dict]]:
        """Match ACARS/VDL2 messages by callsign, flight, or registration fields."""
        if not icao and not callsign:
            return {'acars': [], 'vdl2': []}

        search_terms: set[str] = set()
        if callsign:
            search_terms.add(callsign.strip().upper())
        if icao:
            search_terms.add(icao.strip().upper())

        acars = []
        for msg in self._acars_messages:
            if self._msg_matches(msg, search_terms):
                acars.append(self._clean_msg(msg))

        vdl2 = []
        for msg in self._vdl2_messages:
            if self._msg_matches(msg, search_terms):
                vdl2.append(self._clean_msg(msg))

        return {'acars': acars, 'vdl2': vdl2}

    @staticmethod
    def _msg_matches(msg: dict, terms: set[str]) -> bool:
        """Check if any identifying field in msg matches the search terms."""
        for field in ('flight', 'tail', 'reg', 'callsign', 'icao', 'addr'):
            val = msg.get(field)
            if val and str(val).strip().upper() in terms:
                return True
        return False

    @staticmethod
    def _clean_msg(msg: dict) -> dict:
        """Return message without internal correlation fields."""
        return {k: v for k, v in msg.items() if not k.startswith('_corr_')}

    @property
    def acars_count(self) -> int:
        return len(self._acars_messages)

    @property
    def vdl2_count(self) -> int:
        return len(self._vdl2_messages)


# Singleton
_correlator: FlightCorrelator | None = None


def get_flight_correlator() -> FlightCorrelator:
    global _correlator
    if _correlator is None:
        _correlator = FlightCorrelator()
    return _correlator
