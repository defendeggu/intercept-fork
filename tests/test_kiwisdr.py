"""Tests for the KiwiSDR WebSocket audio client."""

import struct
from unittest.mock import patch, MagicMock

import pytest

from utils.kiwisdr import (
    KiwiSDRClient,
    KIWI_SAMPLE_RATE,
    KIWI_SND_HEADER_SIZE,
    KIWI_DEFAULT_PORT,
    MODE_FILTERS,
    VALID_MODES,
    parse_host_port,
)


# ============================================
# parse_host_port tests
# ============================================

def test_parse_host_port_basic():
    """Should parse host:port from a simple URL."""
    assert parse_host_port('http://kiwi.example.com:8073') == ('kiwi.example.com', 8073)


def test_parse_host_port_no_port():
    """Should default to 8073 when port is missing."""
    assert parse_host_port('http://kiwi.example.com') == ('kiwi.example.com', KIWI_DEFAULT_PORT)


def test_parse_host_port_https():
    """Should strip https:// prefix."""
    assert parse_host_port('https://secure.kiwi.com:9090') == ('secure.kiwi.com', 9090)


def test_parse_host_port_ws():
    """Should strip ws:// prefix."""
    assert parse_host_port('ws://kiwi.local:8074') == ('kiwi.local', 8074)


def test_parse_host_port_with_path():
    """Should strip trailing path from URL."""
    assert parse_host_port('http://kiwi.com:8073/some/path') == ('kiwi.com', 8073)


def test_parse_host_port_bare_host():
    """Should handle bare hostname without protocol."""
    assert parse_host_port('kiwi.local') == ('kiwi.local', KIWI_DEFAULT_PORT)


def test_parse_host_port_bare_host_with_port():
    """Should handle bare hostname with port."""
    assert parse_host_port('kiwi.local:8074') == ('kiwi.local', 8074)


def test_parse_host_port_empty():
    """Should handle empty/None input."""
    assert parse_host_port('') == ('', KIWI_DEFAULT_PORT)


def test_parse_host_port_invalid_port():
    """Should default port for non-numeric port."""
    assert parse_host_port('http://kiwi.com:abc') == ('kiwi.com', KIWI_DEFAULT_PORT)


# ============================================
# SND frame parsing tests
# ============================================

def _make_snd_frame(smeter_raw: int, pcm_samples: list[int]) -> bytes:
    """Build a mock KiwiSDR SND binary frame."""
    header = b'SND'           # 3 bytes: magic
    header += b'\x00'         # 1 byte: flags
    header += struct.pack('>I', 42)   # 4 bytes: sequence number
    header += struct.pack('>h', smeter_raw)  # 2 bytes: S-meter
    # PCM data: 16-bit signed LE
    pcm = b''.join(struct.pack('<h', s) for s in pcm_samples)
    return header + pcm


def test_parse_snd_frame_smeter():
    """Should extract S-meter value from SND frame."""
    client = KiwiSDRClient(host='test', port=8073)
    audio_data = []

    def on_audio(pcm, smeter):
        audio_data.append((pcm, smeter))

    client._on_audio = on_audio
    frame = _make_snd_frame(-730, [100, -100, 200])  # -73.0 dBm = S9
    client._parse_snd_frame(frame)

    assert client.last_smeter == -730
    assert len(audio_data) == 1
    assert audio_data[0][1] == -730


def test_parse_snd_frame_pcm_data():
    """Should forward PCM data from SND frame."""
    client = KiwiSDRClient(host='test', port=8073)
    received_pcm = []

    def on_audio(pcm, smeter):
        received_pcm.append(pcm)

    client._on_audio = on_audio
    samples = [1000, -2000, 3000, -4000]
    frame = _make_snd_frame(0, samples)
    client._parse_snd_frame(frame)

    assert len(received_pcm) == 1
    # PCM data is 8 bytes (4 samples * 2 bytes each)
    assert len(received_pcm[0]) == len(samples) * 2


def test_parse_snd_frame_short():
    """Should ignore frames shorter than header size."""
    client = KiwiSDRClient(host='test', port=8073)
    client._on_audio = MagicMock()
    client._parse_snd_frame(b'SND\x00')  # Too short
    client._on_audio.assert_not_called()


def test_parse_snd_frame_wrong_magic():
    """Should ignore frames with wrong header magic."""
    client = KiwiSDRClient(host='test', port=8073)
    client._on_audio = MagicMock()
    frame = b'XXX' + b'\x00' * 7 + b'\x00' * 10  # Wrong magic
    client._parse_snd_frame(frame)
    client._on_audio.assert_not_called()


# ============================================
# Client state tests
# ============================================

def test_client_initial_state():
    """New client should start disconnected."""
    client = KiwiSDRClient(host='kiwi.local', port=8073)
    assert client.connected is False
    assert client.host == 'kiwi.local'
    assert client.port == 8073
    assert client.frequency_khz == 0
    assert client.mode == 'am'


def test_client_tune_when_disconnected():
    """Tune should fail when not connected."""
    client = KiwiSDRClient(host='test', port=8073)
    assert client.tune(7000, 'usb') is False


def test_client_disconnect_when_not_connected():
    """Disconnect should not raise when already disconnected."""
    client = KiwiSDRClient(host='test', port=8073)
    client.disconnect()  # Should not raise
    assert client.connected is False


@patch('utils.kiwisdr.WEBSOCKET_CLIENT_AVAILABLE', False)
def test_client_connect_no_websocket():
    """Connect should fail if websocket-client not available."""
    client = KiwiSDRClient(host='test', port=8073)
    assert client.connect(7000, 'am') is False


# ============================================
# Constants tests
# ============================================

def test_sample_rate():
    """Sample rate should be 12 kHz."""
    assert KIWI_SAMPLE_RATE == 12000


def test_snd_header_size():
    """SND header should be 10 bytes."""
    assert KIWI_SND_HEADER_SIZE == 10


def test_valid_modes():
    """All expected modes should be in VALID_MODES."""
    assert 'am' in VALID_MODES
    assert 'usb' in VALID_MODES
    assert 'lsb' in VALID_MODES
    assert 'cw' in VALID_MODES


def test_mode_filters_defined():
    """All valid modes should have filter definitions."""
    for mode in VALID_MODES:
        assert mode in MODE_FILTERS
        low, high = MODE_FILTERS[mode]
        assert low < high


def test_mode_filter_am_symmetric():
    """AM filter should be symmetric."""
    low, high = MODE_FILTERS['am']
    assert low == -high


def test_mode_filter_usb_positive():
    """USB filter should be in positive passband."""
    low, high = MODE_FILTERS['usb']
    assert low > 0
    assert high > low


def test_mode_filter_lsb_negative():
    """LSB filter should be in negative passband."""
    low, high = MODE_FILTERS['lsb']
    assert low < 0
    assert high < 0


# ============================================
# Connection tests with mocked WebSocket
# ============================================

@patch('utils.kiwisdr.WEBSOCKET_CLIENT_AVAILABLE', True)
@patch('utils.kiwisdr.websocket')
def test_client_connect_success(mock_ws_module):
    """Connect should establish a WebSocket connection."""
    mock_ws = MagicMock()
    mock_ws_module.WebSocket.return_value = mock_ws

    client = KiwiSDRClient(host='kiwi.local', port=8073)
    result = client.connect(7000, 'am')

    assert result is True
    assert client.connected is True
    assert client.frequency_khz == 7000
    assert client.mode == 'am'

    # Verify WebSocket was created and connected
    mock_ws_module.WebSocket.assert_called_once()
    mock_ws.connect.assert_called_once()

    # Verify protocol messages were sent
    calls = [str(c) for c in mock_ws.send.call_args_list]
    auth_sent = any('SET auth' in c for c in calls)
    compression_sent = any('SET compression=0' in c for c in calls)
    mod_sent = any('SET mod=am' in c and 'freq=7000' in c for c in calls)
    assert auth_sent, "Auth message not sent"
    assert compression_sent, "Compression message not sent"
    assert mod_sent, "Tune message not sent"

    # Cleanup
    client.disconnect()


@patch('utils.kiwisdr.WEBSOCKET_CLIENT_AVAILABLE', True)
@patch('utils.kiwisdr.websocket')
def test_client_connect_failure(mock_ws_module):
    """Connect should handle connection failures."""
    mock_ws = MagicMock()
    mock_ws.connect.side_effect = ConnectionRefusedError("Connection refused")
    mock_ws_module.WebSocket.return_value = mock_ws

    client = KiwiSDRClient(host='unreachable.local', port=8073)
    result = client.connect(7000, 'am')

    assert result is False
    assert client.connected is False


@patch('utils.kiwisdr.WEBSOCKET_CLIENT_AVAILABLE', True)
@patch('utils.kiwisdr.websocket')
def test_client_tune_success(mock_ws_module):
    """Tune should send the correct SET mod command."""
    mock_ws = MagicMock()
    mock_ws_module.WebSocket.return_value = mock_ws

    client = KiwiSDRClient(host='kiwi.local', port=8073)
    client.connect(7000, 'am')

    mock_ws.send.reset_mock()
    result = client.tune(14000, 'usb')

    assert result is True
    assert client.frequency_khz == 14000
    assert client.mode == 'usb'

    tune_calls = [str(c) for c in mock_ws.send.call_args_list]
    assert any('SET mod=usb' in c and 'freq=14000' in c for c in tune_calls)

    client.disconnect()


@patch('utils.kiwisdr.WEBSOCKET_CLIENT_AVAILABLE', True)
@patch('utils.kiwisdr.websocket')
def test_client_invalid_mode_fallback(mock_ws_module):
    """Connect with invalid mode should fall back to AM."""
    mock_ws = MagicMock()
    mock_ws_module.WebSocket.return_value = mock_ws

    client = KiwiSDRClient(host='kiwi.local', port=8073)
    client.connect(7000, 'invalid_mode')

    assert client.mode == 'am'
    client.disconnect()


@patch('utils.kiwisdr.WEBSOCKET_CLIENT_AVAILABLE', True)
@patch('utils.kiwisdr.websocket')
def test_client_ws_url_format(mock_ws_module):
    """WebSocket URL should follow KiwiSDR format."""
    mock_ws = MagicMock()
    mock_ws_module.WebSocket.return_value = mock_ws

    client = KiwiSDRClient(host='test.kiwi.com', port=8074)
    client.connect(7000, 'am')

    ws_url = mock_ws.connect.call_args[0][0]
    assert ws_url.startswith('ws://test.kiwi.com:8074/')
    assert ws_url.endswith('/SND')

    client.disconnect()
