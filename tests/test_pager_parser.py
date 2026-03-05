"""Tests for pager multimon-ng output parser."""

from __future__ import annotations

from routes.pager import parse_multimon_output


class TestPocsagAlphaNumeric:
    """Standard POCSAG messages with Alpha or Numeric content."""

    def test_alpha_message(self):
        line = "POCSAG1200: Address:    1337  Function: 3  Alpha:   Hello World"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["protocol"] == "POCSAG1200"
        assert result["address"] == "1337"
        assert result["function"] == "3"
        assert result["msg_type"] == "Alpha"
        assert result["message"] == "Hello World"

    def test_numeric_message(self):
        line = "POCSAG1200: Address:     500  Function: 2  Numeric: 55512345"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Numeric"
        assert result["message"] == "55512345"

    def test_alpha_empty_content(self):
        line = "POCSAG1200: Address:     200  Function: 3  Alpha:   "
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Alpha"
        assert result["message"] == "[No Message]"

    def test_pocsag512_baud(self):
        line = "POCSAG512: Address: 12345 Function: 0 Alpha: test"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["protocol"] == "POCSAG512"
        assert result["message"] == "test"

    def test_pocsag2400_baud(self):
        line = "POCSAG2400: Address: 9999 Function: 1 Numeric: 0"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["protocol"] == "POCSAG2400"

    def test_alpha_with_special_characters(self):
        """Base64, colons, equals signs, and other punctuation should parse."""
        line = "POCSAG1200: Address:    1337  Function: 3  Alpha:   0:U0tZLQ=="
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Alpha"
        assert result["message"] == "0:U0tZLQ=="


class TestPocsagCatchAll:
    """Catch-all pattern for non-standard content type labels."""

    def test_unknown_content_label(self):
        """Future multimon-ng versions might emit new type labels."""
        line = "POCSAG1200: Address: 1337 Function: 3 Skyper: some data"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Skyper"
        assert result["message"] == "some data"

    def test_char_content_label(self):
        line = "POCSAG1200: Address: 1337 Function: 2 Char: ABCDEF"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Char"
        assert result["message"] == "ABCDEF"

    def test_catchall_empty_content(self):
        line = "POCSAG1200: Address: 1337 Function: 2 Raw:  "
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Raw"
        assert result["message"] == "[No Message]"

    def test_alpha_still_matches_first(self):
        """Alpha/Numeric pattern should take priority over catch-all."""
        line = "POCSAG1200: Address: 100 Function: 3 Alpha: priority"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Alpha"
        assert result["message"] == "priority"


class TestPocsagToneOnly:
    """Address-only lines with no message content."""

    def test_tone_only(self):
        line = "POCSAG1200: Address: 1977540 Function: 2"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Tone"
        assert result["message"] == "[Tone Only]"
        assert result["address"] == "1977540"

    def test_tone_only_with_trailing_spaces(self):
        line = "POCSAG1200: Address: 1337 Function: 1   "
        result = parse_multimon_output(line)
        assert result is not None
        assert result["msg_type"] == "Tone"


class TestFlexParsing:
    """FLEX protocol output parsing."""

    def test_simple_flex(self):
        line = "FLEX: Some flex message here"
        result = parse_multimon_output(line)
        assert result is not None
        assert result["protocol"] == "FLEX"
        assert result["message"] == "Some flex message here"

    def test_no_match(self):
        """Unrecognized lines should return None."""
        assert parse_multimon_output("multimon-ng 1.2.0") is None
        assert parse_multimon_output("") is None
        assert parse_multimon_output("Enabled decoders: POCSAG512") is None
