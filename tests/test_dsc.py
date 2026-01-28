"""Tests for DSC (Digital Selective Calling) utilities."""

import json
import pytest
from datetime import datetime


class TestDSCParser:
    """Tests for DSC parser utilities."""

    def test_get_country_from_mmsi_ship_station(self):
        """Test country lookup for standard ship MMSI."""
        from utils.dsc.parser import get_country_from_mmsi

        # UK ships start with 232-235
        assert get_country_from_mmsi('232123456') == 'United Kingdom'
        assert get_country_from_mmsi('235987654') == 'United Kingdom'

        # US ships start with 303, 338, 366-369
        assert get_country_from_mmsi('366123456') == 'USA'
        assert get_country_from_mmsi('369000001') == 'USA'

        # Panama (common flag of convenience)
        assert get_country_from_mmsi('351234567') == 'Panama'
        assert get_country_from_mmsi('370000001') == 'Panama'

        # Norway
        assert get_country_from_mmsi('257123456') == 'Norway'

        # Germany
        assert get_country_from_mmsi('211000001') == 'Germany'

    def test_get_country_from_mmsi_coast_station(self):
        """Test country lookup for coast station MMSI (starts with 00)."""
        from utils.dsc.parser import get_country_from_mmsi

        # Coast stations: 00 + MID
        assert get_country_from_mmsi('002320001') == 'United Kingdom'
        assert get_country_from_mmsi('003660001') == 'USA'

    def test_get_country_from_mmsi_group_station(self):
        """Test country lookup for group station MMSI (starts with 0)."""
        from utils.dsc.parser import get_country_from_mmsi

        # Group call: 0 + MID
        assert get_country_from_mmsi('023200001') == 'United Kingdom'
        assert get_country_from_mmsi('036600001') == 'USA'

    def test_get_country_from_mmsi_unknown(self):
        """Test country lookup returns None for unknown MID."""
        from utils.dsc.parser import get_country_from_mmsi

        assert get_country_from_mmsi('999999999') is None
        assert get_country_from_mmsi('100000000') is None

    def test_get_country_from_mmsi_invalid(self):
        """Test country lookup handles invalid input."""
        from utils.dsc.parser import get_country_from_mmsi

        assert get_country_from_mmsi('') is None
        assert get_country_from_mmsi(None) is None
        assert get_country_from_mmsi('12') is None

    def test_get_distress_nature_text(self):
        """Test distress nature code to text conversion."""
        from utils.dsc.parser import get_distress_nature_text

        assert get_distress_nature_text(100) == 'UNDESIGNATED'
        assert get_distress_nature_text(101) == 'FIRE'
        assert get_distress_nature_text(102) == 'FLOODING'
        assert get_distress_nature_text(103) == 'COLLISION'
        assert get_distress_nature_text(106) == 'SINKING'
        assert get_distress_nature_text(109) == 'PIRACY'
        assert get_distress_nature_text(110) == 'MOB'  # Man overboard

    def test_get_distress_nature_text_unknown(self):
        """Test distress nature returns formatted unknown for invalid codes."""
        from utils.dsc.parser import get_distress_nature_text

        assert 'UNKNOWN' in get_distress_nature_text(999)
        assert '999' in get_distress_nature_text(999)

    def test_get_distress_nature_text_string_input(self):
        """Test distress nature accepts string input."""
        from utils.dsc.parser import get_distress_nature_text

        assert get_distress_nature_text('101') == 'FIRE'
        assert get_distress_nature_text('invalid') == 'invalid'

    def test_get_format_text(self):
        """Test format code to text conversion."""
        from utils.dsc.parser import get_format_text

        assert get_format_text(100) == 'DISTRESS'
        assert get_format_text(102) == 'ALL_SHIPS'
        assert get_format_text(106) == 'DISTRESS_ACK'
        assert get_format_text(108) == 'DISTRESS_RELAY'
        assert get_format_text(112) == 'INDIVIDUAL'
        assert get_format_text(116) == 'ROUTINE'
        assert get_format_text(118) == 'SAFETY'
        assert get_format_text(120) == 'URGENCY'

    def test_get_format_text_unknown(self):
        """Test format code returns unknown for invalid codes."""
        from utils.dsc.parser import get_format_text

        result = get_format_text(999)
        assert 'UNKNOWN' in result

    def test_get_telecommand_text(self):
        """Test telecommand code to text conversion."""
        from utils.dsc.parser import get_telecommand_text

        assert get_telecommand_text(100) == 'F3E_G3E_ALL'
        assert get_telecommand_text(105) == 'DATA'
        assert get_telecommand_text(107) == 'DISTRESS_ACK'
        assert get_telecommand_text(111) == 'TEST'

    def test_get_category_priority(self):
        """Test category priority values."""
        from utils.dsc.parser import get_category_priority

        # Distress has highest priority (0)
        assert get_category_priority('DISTRESS') == 0
        assert get_category_priority('distress') == 0

        # Urgency is lower
        assert get_category_priority('URGENCY') == 3

        # Safety is lower still
        assert get_category_priority('SAFETY') == 4

        # Routine is lowest
        assert get_category_priority('ROUTINE') == 5

        # Unknown gets default high number
        assert get_category_priority('UNKNOWN') == 10

    def test_validate_mmsi_valid(self):
        """Test MMSI validation with valid numbers."""
        from utils.dsc.parser import validate_mmsi

        assert validate_mmsi('232123456') is True
        assert validate_mmsi('366000001') is True
        assert validate_mmsi('002320001') is True  # Coast station
        assert validate_mmsi('023200001') is True  # Group station

    def test_validate_mmsi_invalid(self):
        """Test MMSI validation rejects invalid numbers."""
        from utils.dsc.parser import validate_mmsi

        assert validate_mmsi('') is False
        assert validate_mmsi(None) is False
        assert validate_mmsi('12345678') is False  # Too short
        assert validate_mmsi('1234567890') is False  # Too long
        assert validate_mmsi('abcdefghi') is False  # Not digits
        assert validate_mmsi('000000000') is False  # All zeros

    def test_classify_mmsi(self):
        """Test MMSI classification."""
        from utils.dsc.parser import classify_mmsi

        # Ship stations (start with 2-7)
        assert classify_mmsi('232123456') == 'ship'
        assert classify_mmsi('366000001') == 'ship'
        assert classify_mmsi('503000001') == 'ship'

        # Coast stations (start with 00)
        assert classify_mmsi('002320001') == 'coast'

        # Group stations (start with 0, not 00)
        assert classify_mmsi('023200001') == 'group'

        # SAR aircraft (start with 111)
        assert classify_mmsi('111232001') == 'sar'

        # Aids to Navigation (start with 99)
        assert classify_mmsi('992321001') == 'aton'

        # Unknown
        assert classify_mmsi('invalid') == 'unknown'
        assert classify_mmsi('812345678') == 'unknown'

    def test_parse_dsc_message_distress(self):
        """Test parsing a distress message."""
        from utils.dsc.parser import parse_dsc_message

        raw = json.dumps({
            'type': 'dsc',
            'format': 100,
            'source_mmsi': '232123456',
            'dest_mmsi': '000000000',
            'category': 'DISTRESS',
            'nature': 101,
            'position': {'lat': 51.5, 'lon': -0.1},
            'telecommand1': 100,
            'timestamp': '2025-01-15T12:00:00Z'
        })

        msg = parse_dsc_message(raw)

        assert msg is not None
        assert msg['type'] == 'dsc_message'
        assert msg['source_mmsi'] == '232123456'
        assert msg['category'] == 'DISTRESS'
        assert msg['source_country'] == 'United Kingdom'
        assert msg['nature_of_distress'] == 'FIRE'
        assert msg['latitude'] == 51.5
        assert msg['longitude'] == -0.1
        assert msg['is_critical'] is True
        assert msg['priority'] == 0

    def test_parse_dsc_message_routine(self):
        """Test parsing a routine message."""
        from utils.dsc.parser import parse_dsc_message

        raw = json.dumps({
            'type': 'dsc',
            'format': 116,
            'source_mmsi': '366000001',
            'category': 'ROUTINE',
            'timestamp': '2025-01-15T12:00:00Z'
        })

        msg = parse_dsc_message(raw)

        assert msg is not None
        assert msg['category'] == 'ROUTINE'
        assert msg['source_country'] == 'USA'
        assert msg['is_critical'] is False
        assert msg['priority'] == 5

    def test_parse_dsc_message_invalid_json(self):
        """Test parsing rejects invalid JSON."""
        from utils.dsc.parser import parse_dsc_message

        assert parse_dsc_message('not json') is None
        assert parse_dsc_message('{invalid}') is None

    def test_parse_dsc_message_missing_type(self):
        """Test parsing rejects messages without correct type."""
        from utils.dsc.parser import parse_dsc_message

        raw = json.dumps({'source_mmsi': '232123456'})
        assert parse_dsc_message(raw) is None

        raw = json.dumps({'type': 'other', 'source_mmsi': '232123456'})
        assert parse_dsc_message(raw) is None

    def test_parse_dsc_message_missing_mmsi(self):
        """Test parsing rejects messages without source MMSI."""
        from utils.dsc.parser import parse_dsc_message

        raw = json.dumps({'type': 'dsc'})
        assert parse_dsc_message(raw) is None

    def test_parse_dsc_message_empty(self):
        """Test parsing handles empty input."""
        from utils.dsc.parser import parse_dsc_message

        assert parse_dsc_message('') is None
        assert parse_dsc_message(None) is None
        assert parse_dsc_message('   ') is None

    def test_format_dsc_for_display(self):
        """Test message formatting for display."""
        from utils.dsc.parser import format_dsc_for_display

        msg = {
            'category': 'DISTRESS',
            'source_mmsi': '232123456',
            'source_country': 'United Kingdom',
            'dest_mmsi': '002320001',
            'nature_of_distress': 'FIRE',
            'latitude': 51.5074,
            'longitude': -0.1278,
            'telecommand1_text': 'F3E_G3E_ALL',
            'channel': 16,
            'timestamp': '2025-01-15T12:00:00Z'
        }

        output = format_dsc_for_display(msg)

        assert 'DISTRESS' in output
        assert '232123456' in output
        assert 'United Kingdom' in output
        assert 'FIRE' in output
        assert '51.5074' in output
        assert 'Channel: 16' in output


class TestDSCDecoder:
    """Tests for DSC decoder utilities."""

    @pytest.fixture
    def decoder(self):
        """Create a DSC decoder instance."""
        # Skip if scipy not available
        pytest.importorskip('scipy')
        pytest.importorskip('numpy')
        from utils.dsc.decoder import DSCDecoder
        return DSCDecoder()

    def test_decode_mmsi_valid(self, decoder):
        """Test MMSI decoding from symbols."""
        # Each symbol is 2 BCD digits
        # To encode MMSI 232123456, we need:
        # 02-32-12-34-56 -> symbols [2, 32, 12, 34, 56]
        symbols = [2, 32, 12, 34, 56]
        result = decoder._decode_mmsi(symbols)
        assert result == '232123456'

    def test_decode_mmsi_with_leading_zeros(self, decoder):
        """Test MMSI decoding handles leading zeros."""
        # Coast station: 002320001
        # 00-23-20-00-01 -> [0, 23, 20, 0, 1]
        symbols = [0, 23, 20, 0, 1]
        result = decoder._decode_mmsi(symbols)
        assert result == '002320001'

    def test_decode_mmsi_short_symbols(self, decoder):
        """Test MMSI decoding handles short symbol list."""
        result = decoder._decode_mmsi([1, 2, 3])
        assert result == '000000000'

    def test_decode_mmsi_invalid_symbols(self, decoder):
        """Test MMSI decoding handles invalid symbol values."""
        # Symbols > 99 should be treated as 0
        symbols = [100, 32, 12, 34, 56]
        result = decoder._decode_mmsi(symbols)
        # First symbol becomes 00
        assert result == '003212345'[-9:]

    def test_decode_position_northeast(self, decoder):
        """Test position decoding for NE quadrant."""
        # Quadrant 10 = NE (lat+, lon+)
        # Position: 51°30'N, 0°10'E
        symbols = [10, 51, 30, 0, 10, 0, 0, 0, 0, 0]
        result = decoder._decode_position(symbols)

        assert result is not None
        assert result['lat'] == pytest.approx(51.5, rel=0.01)
        assert result['lon'] == pytest.approx(0.1667, rel=0.01)

    def test_decode_position_northwest(self, decoder):
        """Test position decoding for NW quadrant."""
        # Quadrant 11 = NW (lat+, lon-)
        # Position: 40°42'N, 74°00'W (NYC area)
        symbols = [11, 40, 42, 0, 74, 0, 0, 0, 0, 0]
        result = decoder._decode_position(symbols)

        assert result is not None
        assert result['lat'] > 0  # North
        assert result['lon'] < 0  # West

    def test_decode_position_southeast(self, decoder):
        """Test position decoding for SE quadrant."""
        # Quadrant 0 = SE (lat-, lon+)
        symbols = [0, 33, 51, 1, 51, 12, 0, 0, 0, 0]
        result = decoder._decode_position(symbols)

        assert result is not None
        assert result['lat'] < 0  # South
        assert result['lon'] > 0  # East

    def test_decode_position_short_symbols(self, decoder):
        """Test position decoding handles short symbol list."""
        result = decoder._decode_position([10, 51, 30])
        assert result is None

    def test_decode_position_invalid_values(self, decoder):
        """Test position decoding handles invalid values gracefully."""
        # Latitude > 90 should be treated as 0
        symbols = [10, 95, 30, 0, 10, 0, 0, 0, 0, 0]
        result = decoder._decode_position(symbols)
        assert result is not None
        assert result['lat'] == pytest.approx(0.5, rel=0.01)  # 0 deg + 30 min

    def test_bits_to_symbol(self, decoder):
        """Test bit to symbol conversion."""
        # Symbol value is first 7 bits (LSB first)
        # Value 100 = 0b1100100 -> bits [0,0,1,0,0,1,1, x,x,x]
        bits = [0, 0, 1, 0, 0, 1, 1, 0, 0, 0]
        result = decoder._bits_to_symbol(bits)
        assert result == 100

    def test_bits_to_symbol_wrong_length(self, decoder):
        """Test bit to symbol returns -1 for wrong length."""
        result = decoder._bits_to_symbol([0, 1, 0, 1, 0])
        assert result == -1

    def test_detect_dot_pattern(self, decoder):
        """Test dot pattern detection."""
        # Dot pattern is alternating 1010101...
        decoder.bit_buffer = [1, 0] * 25  # 50 alternating bits
        assert decoder._detect_dot_pattern() is True

    def test_detect_dot_pattern_insufficient(self, decoder):
        """Test dot pattern not detected with insufficient alternations."""
        decoder.bit_buffer = [1, 0] * 5  # Only 10 bits
        assert decoder._detect_dot_pattern() is False

    def test_detect_dot_pattern_not_alternating(self, decoder):
        """Test dot pattern not detected without alternation."""
        decoder.bit_buffer = [1, 1, 1, 1, 0, 0, 0, 0] * 5
        assert decoder._detect_dot_pattern() is False


class TestDSCConstants:
    """Tests for DSC constants."""

    def test_format_codes_completeness(self):
        """Test that all standard format codes are defined."""
        from utils.dsc.constants import FORMAT_CODES

        # ITU-R M.493 format codes
        assert 100 in FORMAT_CODES  # DISTRESS
        assert 102 in FORMAT_CODES  # ALL_SHIPS
        assert 106 in FORMAT_CODES  # DISTRESS_ACK
        assert 112 in FORMAT_CODES  # INDIVIDUAL
        assert 116 in FORMAT_CODES  # ROUTINE
        assert 118 in FORMAT_CODES  # SAFETY
        assert 120 in FORMAT_CODES  # URGENCY

    def test_distress_nature_codes_completeness(self):
        """Test that all distress nature codes are defined."""
        from utils.dsc.constants import DISTRESS_NATURE_CODES

        # ITU-R M.493 distress nature codes
        assert 100 in DISTRESS_NATURE_CODES  # UNDESIGNATED
        assert 101 in DISTRESS_NATURE_CODES  # FIRE
        assert 102 in DISTRESS_NATURE_CODES  # FLOODING
        assert 103 in DISTRESS_NATURE_CODES  # COLLISION
        assert 106 in DISTRESS_NATURE_CODES  # SINKING
        assert 109 in DISTRESS_NATURE_CODES  # PIRACY
        assert 110 in DISTRESS_NATURE_CODES  # MOB

    def test_mid_country_map_completeness(self):
        """Test that common MID codes are defined."""
        from utils.dsc.constants import MID_COUNTRY_MAP

        # Verify some key maritime nations
        assert '232' in MID_COUNTRY_MAP  # UK
        assert '366' in MID_COUNTRY_MAP  # USA
        assert '351' in MID_COUNTRY_MAP  # Panama
        assert '257' in MID_COUNTRY_MAP  # Norway
        assert '211' in MID_COUNTRY_MAP  # Germany
        assert '503' in MID_COUNTRY_MAP  # Australia
        assert '431' in MID_COUNTRY_MAP  # Japan

    def test_vhf_channel_70_frequency(self):
        """Test DSC Channel 70 frequency constant."""
        from utils.dsc.constants import VHF_CHANNELS

        assert VHF_CHANNELS[70] == 156.525

    def test_dsc_modulation_parameters(self):
        """Test DSC modulation constants."""
        from utils.dsc.constants import (
            DSC_BAUD_RATE,
            DSC_MARK_FREQ,
            DSC_SPACE_FREQ,
        )

        assert DSC_BAUD_RATE == 100
        assert DSC_MARK_FREQ == 1800
        assert DSC_SPACE_FREQ == 1200
