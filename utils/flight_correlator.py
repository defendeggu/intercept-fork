"""Match ACARS/VDL2 messages to ADS-B aircraft by callsign."""

from __future__ import annotations

import time
from collections import deque

from utils.airline_codes import expand_search_terms, translate_flight


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
        self,
        icao: str | None = None,
        callsign: str | None = None,
        registration: str | None = None,
    ) -> dict[str, list[dict]]:
        """Match ACARS/VDL2 messages by callsign, flight, or registration fields."""
        if not icao and not callsign:
            return {'acars': [], 'vdl2': []}

        search_terms: set[str] = set()
        if callsign:
            search_terms.add(callsign.strip().upper())
        if icao:
            search_terms.add(icao.strip().upper())
        if registration:
            search_terms.add(registration.strip().upper())

        # Expand with IATA↔ICAO airline code translations
        search_terms = expand_search_terms(search_terms)

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
            if not val:
                continue
            upper_val = str(val).strip().upper()
            if upper_val in terms:
                return True
            # Also try translating the message field value
            for translated in translate_flight(upper_val):
                if translated in terms:
                    return True
        return False

    @staticmethod
    def _clean_msg(msg: dict) -> dict:
        """Return message without internal correlation fields."""
        return {k: v for k, v in msg.items() if not k.startswith('_corr_')}

    def get_recent_messages(self, msg_type: str = 'acars', limit: int = 50) -> list[dict]:
        """Return the most recent messages (newest first)."""
        source = self._acars_messages if msg_type == 'acars' else self._vdl2_messages
        msgs = [self._clean_msg(m) for m in source]
        msgs.reverse()
        return msgs[:limit]

    def clear_acars(self) -> None:
        """Clear all stored ACARS messages."""
        self._acars_messages.clear()

    def clear_vdl2(self) -> None:
        """Clear all stored VDL2 messages."""
        self._vdl2_messages.clear()

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
