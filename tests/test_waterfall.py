"""Tests for the Waterfall / Spectrogram endpoints."""

from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def auth_client(client):
    """Client with logged-in session."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    return client


def test_waterfall_start_no_rtl_power(auth_client):
    """Start should fail gracefully when rtl_power is not available."""
    with patch('routes.listening_post.find_rtl_power', return_value=None):
        resp = auth_client.post('/listening/waterfall/start', json={
            'start_freq': 88.0,
            'end_freq': 108.0,
        })
        assert resp.status_code == 503
        data = resp.get_json()
        assert 'rtl_power' in data['message']


def test_waterfall_start_invalid_range(auth_client):
    """Start should reject end <= start."""
    with patch('routes.listening_post.find_rtl_power', return_value='/usr/bin/rtl_power'):
        resp = auth_client.post('/listening/waterfall/start', json={
            'start_freq': 108.0,
            'end_freq': 88.0,
        })
        assert resp.status_code == 400


def test_waterfall_start_success(auth_client):
    """Start should succeed with mocked rtl_power and device."""
    with patch('routes.listening_post.find_rtl_power', return_value='/usr/bin/rtl_power'), \
         patch('routes.listening_post.app_module') as mock_app:
        mock_app.claim_sdr_device.return_value = None  # No error, claim succeeds
        resp = auth_client.post('/listening/waterfall/start', json={
            'start_freq': 88.0,
            'end_freq': 108.0,
            'gain': 40,
            'device': 0,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'started'

    # Clean up: stop waterfall
    import routes.listening_post as lp
    lp.waterfall_running = False


def test_waterfall_stop(auth_client):
    """Stop should succeed."""
    resp = auth_client.post('/listening/waterfall/stop')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'stopped'


def test_waterfall_stream_mimetype(auth_client):
    """Stream should return event-stream content type."""
    resp = auth_client.get('/listening/waterfall/stream')
    assert resp.content_type.startswith('text/event-stream')


def test_waterfall_start_device_busy(auth_client):
    """Start should fail when device is in use."""
    with patch('routes.listening_post.find_rtl_power', return_value='/usr/bin/rtl_power'), \
         patch('routes.listening_post.app_module') as mock_app:
        mock_app.claim_sdr_device.return_value = 'SDR device 0 is in use by scanner'
        resp = auth_client.post('/listening/waterfall/start', json={
            'start_freq': 88.0,
            'end_freq': 108.0,
        })
        assert resp.status_code == 409
