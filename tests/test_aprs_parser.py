"""APRS packet parser regression tests."""

from __future__ import annotations

import pytest

from routes.aprs import parse_aprs_packet


_BASE_PACKET = "N0CALL-9>APRS,TCPIP*:@092345z4903.50N/07201.75W_090/000g005t077"


@pytest.mark.parametrize(
    "line",
    [
        _BASE_PACKET,
        f"[0.4] {_BASE_PACKET}",
        f"[0L] {_BASE_PACKET}",
        f"AFSK1200: {_BASE_PACKET}",
        f"AFSK1200: [0L] {_BASE_PACKET}",
    ],
)
def test_parse_aprs_packet_accepts_decoder_prefix_variants(line: str) -> None:
    packet = parse_aprs_packet(line)
    assert packet is not None
    assert packet["callsign"] == "N0CALL-9"
    assert packet["type"] == "aprs"


def test_parse_aprs_packet_accepts_callsign_with_tactical_suffix() -> None:
    packet = parse_aprs_packet("CALL/1>APRS:!4903.50N/07201.75W-Test")
    assert packet is not None
    assert packet["callsign"] == "CALL/1"
    assert packet["lat"] == pytest.approx(49.058333, rel=0, abs=1e-6)
    assert packet["lon"] == pytest.approx(-72.029167, rel=0, abs=1e-6)


def test_parse_aprs_packet_handles_ambiguous_uncompressed_position() -> None:
    packet = parse_aprs_packet("KJ7ABC-7>APRS,WIDE1-1:!4903.  N/07201.  W-Test")
    assert packet is not None
    assert packet["packet_type"] == "position"
    assert packet["lat"] == pytest.approx(49.05, rel=0, abs=1e-6)
    assert packet["lon"] == pytest.approx(-72.016667, rel=0, abs=1e-6)


def test_parse_aprs_packet_handles_no_decimal_position_variant() -> None:
    packet = parse_aprs_packet("KJ7ABC-7>APRS,WIDE1-1:!4903N/07201W-Test")
    assert packet is not None
    assert packet["packet_type"] == "position"
    assert packet["lat"] == pytest.approx(49.05, rel=0, abs=1e-6)
    assert packet["lon"] == pytest.approx(-72.016667, rel=0, abs=1e-6)
