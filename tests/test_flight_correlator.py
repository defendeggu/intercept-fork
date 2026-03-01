"""Tests for FlightCorrelator: ACARS/VDL2 message matching."""

import pytest

from utils.flight_correlator import FlightCorrelator


class TestFlightCorrelator:
    """Test ACARS/VDL2 message matching by callsign."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.correlator = FlightCorrelator(max_messages=100)

    def test_add_acars_message(self):
        self.correlator.add_acars_message({
            'flight': 'BAW123', 'tail': 'G-ABCD', 'text': 'Hello',
        })
        assert self.correlator.acars_count == 1

    def test_add_vdl2_message(self):
        self.correlator.add_vdl2_message({
            'flight': 'DLH456', 'text': 'World',
        })
        assert self.correlator.vdl2_count == 1

    def test_match_by_callsign(self):
        self.correlator.add_acars_message({
            'flight': 'BAW123', 'text': 'msg1',
        })
        self.correlator.add_acars_message({
            'flight': 'DLH456', 'text': 'msg2',
        })

        result = self.correlator.get_messages_for_aircraft(callsign='BAW123')
        assert len(result['acars']) == 1
        assert result['acars'][0]['text'] == 'msg1'

    def test_match_by_icao(self):
        self.correlator.add_vdl2_message({
            'icao': 'ABC123', 'text': 'vdl2 msg',
        })

        result = self.correlator.get_messages_for_aircraft(icao='ABC123')
        assert len(result['vdl2']) == 1
        assert result['vdl2'][0]['text'] == 'vdl2 msg'

    def test_no_match_returns_empty(self):
        self.correlator.add_acars_message({'flight': 'BAW123', 'text': 'msg'})

        result = self.correlator.get_messages_for_aircraft(callsign='NOMATCH')
        assert result['acars'] == []
        assert result['vdl2'] == []

    def test_empty_search_returns_empty(self):
        result = self.correlator.get_messages_for_aircraft()
        assert result == {'acars': [], 'vdl2': []}

    def test_ring_buffer_limit(self):
        correlator = FlightCorrelator(max_messages=5)
        for i in range(10):
            correlator.add_acars_message({'flight': f'FL{i}', 'text': f'msg{i}'})

        assert correlator.acars_count == 5
        # First 5 messages should have been evicted
        result = correlator.get_messages_for_aircraft(callsign='FL0')
        assert len(result['acars']) == 0
        # Last message should still be there
        result = correlator.get_messages_for_aircraft(callsign='FL9')
        assert len(result['acars']) == 1

    def test_case_insensitive_matching(self):
        self.correlator.add_acars_message({'flight': 'baw123', 'text': 'lowercase'})

        result = self.correlator.get_messages_for_aircraft(callsign='BAW123')
        assert len(result['acars']) == 1

    def test_match_by_tail_field(self):
        self.correlator.add_acars_message({
            'tail': 'G-ABCD', 'text': 'tail match',
        })

        result = self.correlator.get_messages_for_aircraft(callsign='G-ABCD')
        assert len(result['acars']) == 1

    def test_internal_fields_not_returned(self):
        self.correlator.add_acars_message({'flight': 'TEST', 'text': 'msg'})

        result = self.correlator.get_messages_for_aircraft(callsign='TEST')
        msg = result['acars'][0]
        assert '_corr_time' not in msg

    def test_both_acars_and_vdl2_returned(self):
        self.correlator.add_acars_message({'flight': 'UAL789', 'text': 'acars'})
        self.correlator.add_vdl2_message({'flight': 'UAL789', 'text': 'vdl2'})

        result = self.correlator.get_messages_for_aircraft(callsign='UAL789')
        assert len(result['acars']) == 1
        assert len(result['vdl2']) == 1
