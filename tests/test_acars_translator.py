"""Tests for ACARS message translator."""

import pytest

from utils.acars_translator import (
    ACARS_LABELS,
    translate_label,
    classify_message_type,
    parse_position_report,
    parse_engine_data,
    parse_weather_data,
    parse_oooi,
    translate_message,
)


# --- translate_label ---

class TestTranslateLabel:
    def test_known_labels(self):
        assert translate_label('H1') == 'Position report (HF data link)'
        assert translate_label('DF') == 'Engine data / DFDR'
        assert translate_label('_d') == 'Demand mode (link test)'
        assert translate_label('5Z') == 'OOOI (gate times)'
        assert translate_label('B9') == 'ATC message'
        assert translate_label('SQ') == 'Squawk assignment'

    def test_unknown_label(self):
        assert translate_label('ZZ') == 'Label ZZ'

    def test_empty_label(self):
        assert translate_label('') == 'Unknown label'

    def test_none_label(self):
        assert translate_label(None) == 'Unknown label'

    def test_q_prefix_unknown(self):
        """Q-prefix labels not in table should get generic link management desc."""
        assert 'Link management' in translate_label('QZ')

    def test_whitespace_stripped(self):
        assert translate_label(' H1 ') == 'Position report (HF data link)'


# --- classify_message_type ---

class TestClassifyMessageType:
    def test_h1_is_position(self):
        assert classify_message_type('H1') == 'position'

    def test_df_is_engine_data(self):
        assert classify_message_type('DF') == 'engine_data'

    def test_h2_is_weather(self):
        assert classify_message_type('H2') == 'weather'

    def test_b9_is_ats(self):
        assert classify_message_type('B9') == 'ats'

    def test_5z_is_oooi(self):
        assert classify_message_type('5Z') == 'oooi'

    def test_sq_is_squawk(self):
        assert classify_message_type('SQ') == 'squawk'

    def test_underscore_d_is_handshake(self):
        assert classify_message_type('_d') == 'handshake'

    def test_q0_is_link_test(self):
        assert classify_message_type('Q0') == 'link_test'

    def test_aa_is_cpdlc(self):
        assert classify_message_type('AA') == 'cpdlc'

    def test_unknown_is_other(self):
        assert classify_message_type('ZZ') == 'other'

    def test_none_is_other(self):
        assert classify_message_type(None) == 'other'

    def test_text_with_bpos_override(self):
        """H1 with #M1BPOS text should be position."""
        assert classify_message_type('H1', '#M1BPOSN42411W086034') == 'position'


# --- parse_position_report ---

class TestParsePositionReport:
    def test_real_h1_bpos(self):
        text = '#M1BPOSN42411W086034,CSG,070852,340,N42441W087074,DTW,0757,224A8C'
        result = parse_position_report(text)
        assert result is not None
        assert result['lat'] > 42
        assert result['lon'] < -86
        assert result['waypoint'] == 'CSG'
        assert result['flight_level'] == 'FL340'
        assert result['destination'] == 'DTW'

    def test_none_text(self):
        assert parse_position_report(None) is None

    def test_empty_text(self):
        assert parse_position_report('') is None

    def test_no_bpos_data(self):
        assert parse_position_report('SOME RANDOM TEXT') is None

    def test_temperature_field(self):
        text = '#M1BPOSN42411W086034,CSG,070852,340,N42441W087074,DTW,0757/TSM045'
        result = parse_position_report(text)
        assert result is not None
        assert result.get('temperature') == '-045 C'

    def test_southern_hemisphere(self):
        text = '#M1BPOSS33500E018200,CPT,120000,350,S33500E018200,CPT,1230,ABC123'
        result = parse_position_report(text)
        assert result is not None
        assert result['lat'] < 0  # South


# --- parse_engine_data ---

class TestParseEngineData:
    def test_real_dfdr_message(self):
        text = '#DFB SM/0 AC0/85.2 AC1/84.9 FL/350 FU/12450 ES/15'
        result = parse_engine_data(text)
        assert result is not None
        assert 'AC0' in result
        assert result['AC0']['value'] == '85.2'
        assert 'FL' in result
        assert result['FL']['value'] == '350'

    def test_none_text(self):
        assert parse_engine_data(None) is None

    def test_empty_text(self):
        assert parse_engine_data('') is None

    def test_no_engine_keys(self):
        assert parse_engine_data('HELLO WORLD') is None

    def test_n1_n2_values(self):
        text = 'N1/92.3 N2/88.1 EGT/425'
        result = parse_engine_data(text)
        assert result is not None
        assert result['N1']['value'] == '92.3'
        assert result['N2']['value'] == '88.1'
        assert result['EGT']['value'] == '425'


# --- parse_weather_data ---

class TestParseWeatherData:
    def test_wind_data(self):
        text = 'WND270015 KJFK VIS10'
        result = parse_weather_data(text)
        assert result is not None
        assert result['wind_dir'] == '270 deg'
        assert result['wind_speed'] == '015 kts'

    def test_airports(self):
        text = '/WX KJFK KLAX TMP24'
        result = parse_weather_data(text)
        assert result is not None
        assert 'KJFK' in result['airports']
        assert 'KLAX' in result['airports']

    def test_none_text(self):
        assert parse_weather_data(None) is None

    def test_empty_text(self):
        assert parse_weather_data('') is None


# --- parse_oooi ---

class TestParseOooi:
    def test_full_oooi(self):
        text = 'KJFK KLAX 1423 1435 1812 1824'
        result = parse_oooi(text)
        assert result is not None
        assert result['origin'] == 'KJFK'
        assert result['destination'] == 'KLAX'
        assert result['out'] == '1423'
        assert result['off'] == '1435'
        assert result['on'] == '1812'
        assert result['in'] == '1824'

    def test_partial_oooi(self):
        text = 'KJFK KLAX 1423 1435'
        result = parse_oooi(text)
        assert result is not None
        assert result['origin'] == 'KJFK'
        assert result['destination'] == 'KLAX'

    def test_none_text(self):
        assert parse_oooi(None) is None

    def test_empty_text(self):
        assert parse_oooi('') is None


# --- translate_message (integration) ---

class TestTranslateMessage:
    def test_h1_position(self):
        msg = {
            'label': 'H1',
            'text': '#M1BPOSN42411W086034,CSG,070852,340,N42441W087074,DTW,0757,224A8C',
        }
        result = translate_message(msg)
        assert result['label_description'] == 'Position report (HF data link)'
        assert result['message_type'] == 'position'
        assert result['parsed'] is not None
        assert 'lat' in result['parsed']

    def test_df_engine(self):
        msg = {
            'label': 'DF',
            'text': '#DFB SM/0 AC0/85.2 AC1/84.9 FL/350',
        }
        result = translate_message(msg)
        assert result['message_type'] == 'engine_data'
        assert result['parsed'] is not None
        assert 'AC0' in result['parsed']

    def test_underscore_d_handshake(self):
        msg = {'label': '_d', 'text': ''}
        result = translate_message(msg)
        assert result['label_description'] == 'Demand mode (link test)'
        assert result['message_type'] == 'handshake'

    def test_unknown_label(self):
        msg = {'label': 'ZZ', 'text': 'SOME DATA'}
        result = translate_message(msg)
        assert result['label_description'] == 'Label ZZ'
        assert result['message_type'] == 'other'
        assert result['parsed'] is None

    def test_missing_fields(self):
        """Handles messages with no label or text gracefully."""
        result = translate_message({})
        assert result['label_description'] == 'Unknown label'
        assert result['message_type'] == 'other'
        assert result['parsed'] is None

    def test_msg_field_fallback(self):
        """Uses 'msg' field when 'text' is missing."""
        msg = {
            'label': 'DF',
            'msg': '#DFB N1/92.3 N2/88.1',
        }
        result = translate_message(msg)
        assert result['parsed'] is not None
        assert 'N1' in result['parsed']

    def test_5z_oooi(self):
        msg = {
            'label': '5Z',
            'text': 'KJFK KLAX 1423 1435 1812 1824',
        }
        result = translate_message(msg)
        assert result['message_type'] == 'oooi'
        assert result['parsed'] is not None
        assert result['parsed']['origin'] == 'KJFK'
