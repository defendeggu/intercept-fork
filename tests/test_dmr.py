"""Tests for the DMR / Digital Voice decoding module."""

from unittest.mock import patch, MagicMock
import pytest
from routes.dmr import parse_dsd_output, _DSD_PROTOCOL_FLAGS, _DSD_FME_PROTOCOL_FLAGS, _DSD_FME_MODULATION


# ============================================
# parse_dsd_output() tests
# ============================================

def test_parse_sync_dmr():
    """Should parse DMR sync line."""
    result = parse_dsd_output('Sync: +DMR (data)')
    assert result is not None
    assert result['type'] == 'sync'
    assert 'DMR' in result['protocol']


def test_parse_sync_p25():
    """Should parse P25 sync line."""
    result = parse_dsd_output('Sync: +P25 Phase 1')
    assert result is not None
    assert result['type'] == 'sync'
    assert 'P25' in result['protocol']


def test_parse_talkgroup_and_source():
    """Should parse talkgroup and source ID."""
    result = parse_dsd_output('TG: 12345  Src: 67890')
    assert result is not None
    assert result['type'] == 'call'
    assert result['talkgroup'] == 12345
    assert result['source_id'] == 67890


def test_parse_slot():
    """Should parse slot info."""
    result = parse_dsd_output('Slot 1')
    assert result is not None
    assert result['type'] == 'slot'
    assert result['slot'] == 1


def test_parse_voice():
    """Should parse voice frame info."""
    result = parse_dsd_output('Voice Frame 1')
    assert result is not None
    assert result['type'] == 'voice'


def test_parse_nac():
    """Should parse P25 NAC."""
    result = parse_dsd_output('NAC: 293')
    assert result is not None
    assert result['type'] == 'nac'
    assert result['nac'] == '293'


def test_parse_talkgroup_dsd_fme_format():
    """Should parse dsd-fme comma-separated TG/Src format."""
    result = parse_dsd_output('TG: 12345, Src: 67890')
    assert result is not None
    assert result['type'] == 'call'
    assert result['talkgroup'] == 12345
    assert result['source_id'] == 67890


def test_parse_talkgroup_dsd_fme_tgt_src_format():
    """Should parse dsd-fme TGT/SRC pipe-delimited format."""
    result = parse_dsd_output('Slot 1 | TGT: 12345 | SRC: 67890')
    assert result is not None
    assert result['type'] == 'call'
    assert result['talkgroup'] == 12345
    assert result['source_id'] == 67890
    assert result['slot'] == 1


def test_parse_talkgroup_with_slot():
    """TG line with slot info should capture both."""
    result = parse_dsd_output('Slot 1 Voice LC, TG: 100, Src: 200')
    assert result is not None
    assert result['type'] == 'call'
    assert result['talkgroup'] == 100
    assert result['source_id'] == 200
    assert result['slot'] == 1


def test_parse_voice_with_slot():
    """Voice frame with slot info should be voice, not slot."""
    result = parse_dsd_output('Slot 2 Voice Frame')
    assert result is not None
    assert result['type'] == 'voice'
    assert result['slot'] == 2


def test_parse_empty_line():
    """Empty lines should return None."""
    assert parse_dsd_output('') is None
    assert parse_dsd_output('   ') is None


def test_parse_unrecognized():
    """Unrecognized lines should return raw event for diagnostics."""
    result = parse_dsd_output('some random text')
    assert result is not None
    assert result['type'] == 'raw'
    assert result['text'] == 'some random text'


def test_parse_banner_filtered():
    """Pure box-drawing lines (banners) should be filtered."""
    assert parse_dsd_output('╔══════════════╗') is None
    assert parse_dsd_output('║              ║') is None
    assert parse_dsd_output('╚══════════════╝') is None
    assert parse_dsd_output('───────────────') is None


def test_parse_box_drawing_with_data_not_filtered():
    """Lines with box-drawing separators AND data should NOT be filtered."""
    result = parse_dsd_output('DMR BS │ Slot 1 │ TG: 12345 │ SRC: 67890')
    assert result is not None
    assert result['type'] == 'call'
    assert result['talkgroup'] == 12345
    assert result['source_id'] == 67890


def test_dsd_fme_flags_differ_from_classic():
    """dsd-fme remapped several flags; tables must NOT be identical."""
    assert _DSD_FME_PROTOCOL_FLAGS != _DSD_PROTOCOL_FLAGS


def test_dsd_fme_protocol_flags_known_values():
    """dsd-fme flags use its own flag names (NOT classic DSD mappings)."""
    assert _DSD_FME_PROTOCOL_FLAGS['auto'] == ['-ft']       # XDMA
    assert _DSD_FME_PROTOCOL_FLAGS['dmr'] == ['-fs']        # Simplex (-fd is D-STAR!)
    assert _DSD_FME_PROTOCOL_FLAGS['p25'] == ['-f1']        # NOT -fp (ProVoice in fme)
    assert _DSD_FME_PROTOCOL_FLAGS['nxdn'] == ['-fn']
    assert _DSD_FME_PROTOCOL_FLAGS['dstar'] == ['-fd']      # -fd is D-STAR in dsd-fme
    assert _DSD_FME_PROTOCOL_FLAGS['provoice'] == ['-fp']   # NOT -fv


def test_dsd_protocol_flags_known_values():
    """Classic DSD protocol flags should map to the correct -f flags."""
    assert _DSD_PROTOCOL_FLAGS['dmr'] == ['-fd']
    assert _DSD_PROTOCOL_FLAGS['p25'] == ['-fp']
    assert _DSD_PROTOCOL_FLAGS['nxdn'] == ['-fn']
    assert _DSD_PROTOCOL_FLAGS['dstar'] == ['-fi']
    assert _DSD_PROTOCOL_FLAGS['provoice'] == ['-fv']
    assert _DSD_PROTOCOL_FLAGS['auto'] == []


def test_dsd_fme_modulation_hints():
    """C4FM modulation hints should be set for C4FM protocols."""
    assert _DSD_FME_MODULATION['dmr'] == ['-mc']
    assert _DSD_FME_MODULATION['p25'] == ['-mc']
    assert _DSD_FME_MODULATION['nxdn'] == ['-mc']
    # D-Star and ProVoice should not have forced modulation
    assert 'dstar' not in _DSD_FME_MODULATION
    assert 'provoice' not in _DSD_FME_MODULATION


# ============================================
# Endpoint tests
# ============================================

@pytest.fixture
def auth_client(client):
    """Client with logged-in session."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    return client


def test_dmr_tools(auth_client):
    """Tools endpoint should return availability info."""
    resp = auth_client.get('/dmr/tools')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'dsd' in data
    assert 'rtl_fm' in data
    assert 'protocols' in data


def test_dmr_status(auth_client):
    """Status endpoint should work."""
    resp = auth_client.get('/dmr/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'running' in data


def test_dmr_start_no_dsd(auth_client):
    """Start should fail gracefully when dsd is not installed."""
    with patch('routes.dmr.find_dsd', return_value=(None, False)):
        resp = auth_client.post('/dmr/start', json={
            'frequency': 462.5625,
            'protocol': 'auto',
        })
        assert resp.status_code == 503
        data = resp.get_json()
        assert 'dsd' in data['message']


def test_dmr_start_no_rtl_fm(auth_client):
    """Start should fail when rtl_fm is missing."""
    with patch('routes.dmr.find_dsd', return_value=('/usr/bin/dsd', False)), \
         patch('routes.dmr.find_rtl_fm', return_value=None):
        resp = auth_client.post('/dmr/start', json={
            'frequency': 462.5625,
        })
        assert resp.status_code == 503


def test_dmr_start_invalid_protocol(auth_client):
    """Start should reject invalid protocol."""
    with patch('routes.dmr.find_dsd', return_value=('/usr/bin/dsd', False)), \
         patch('routes.dmr.find_rtl_fm', return_value='/usr/bin/rtl_fm'):
        resp = auth_client.post('/dmr/start', json={
            'frequency': 462.5625,
            'protocol': 'invalid',
        })
        assert resp.status_code == 400


def test_dmr_stop(auth_client):
    """Stop should succeed."""
    resp = auth_client.post('/dmr/stop')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'stopped'


def test_dmr_stream_mimetype(auth_client):
    """Stream should return event-stream content type."""
    resp = auth_client.get('/dmr/stream')
    assert resp.content_type.startswith('text/event-stream')
