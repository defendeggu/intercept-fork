"""Tests for the SigID Wiki lookup API endpoint."""

from unittest.mock import patch

import pytest

import routes.signalid as signalid_module


@pytest.fixture
def auth_client(client):
    """Client with logged-in session."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    return client


def test_sigidwiki_lookup_missing_frequency(auth_client):
    """frequency_mhz is required."""
    resp = auth_client.post('/signalid/sigidwiki', json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['status'] == 'error'


def test_sigidwiki_lookup_invalid_frequency(auth_client):
    """frequency_mhz must be numeric and positive."""
    resp = auth_client.post('/signalid/sigidwiki', json={'frequency_mhz': 'abc'})
    assert resp.status_code == 400

    resp = auth_client.post('/signalid/sigidwiki', json={'frequency_mhz': -1})
    assert resp.status_code == 400


def test_sigidwiki_lookup_success(auth_client):
    """Endpoint returns normalized SigID lookup structure."""
    signalid_module._cache.clear()
    fake_lookup = {
        'matches': [
            {
                'title': 'POCSAG',
                'url': 'https://www.sigidwiki.com/wiki/POCSAG',
                'frequencies_mhz': [929.6625],
                'modes': ['NFM'],
                'modulations': ['FSK'],
                'distance_hz': 0,
                'source': 'SigID Wiki',
            }
        ],
        'search_used': False,
        'exact_queries': ['[[Category:Signal]][[Frequencies::929.6625 MHz]]|?Frequencies|?Mode|?Modulation|limit=10'],
    }

    with patch('routes.signalid._lookup_sigidwiki_matches', return_value=fake_lookup) as lookup_mock:
        resp = auth_client.post('/signalid/sigidwiki', json={
            'frequency_mhz': 929.6625,
            'modulation': 'fm',
            'limit': 5,
        })

    assert lookup_mock.call_count == 1
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'
    assert data['source'] == 'sigidwiki'
    assert data['cached'] is False
    assert data['match_count'] == 1
    assert data['matches'][0]['title'] == 'POCSAG'


def test_sigidwiki_lookup_cached_response(auth_client):
    """Second identical lookup should be served from cache."""
    signalid_module._cache.clear()
    fake_lookup = {
        'matches': [{'title': 'Test Signal', 'url': 'https://www.sigidwiki.com/wiki/Test_Signal'}],
        'search_used': True,
        'exact_queries': [],
    }

    payload = {'frequency_mhz': 433.92, 'modulation': 'nfm', 'limit': 5}
    with patch('routes.signalid._lookup_sigidwiki_matches', return_value=fake_lookup) as lookup_mock:
        first = auth_client.post('/signalid/sigidwiki', json=payload)
        second = auth_client.post('/signalid/sigidwiki', json=payload)

    assert lookup_mock.call_count == 1
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()['cached'] is False
    assert second.get_json()['cached'] is True


def test_sigidwiki_lookup_backend_failure(auth_client):
    """Unexpected lookup failures should return 502."""
    signalid_module._cache.clear()
    with patch('routes.signalid._lookup_sigidwiki_matches', side_effect=RuntimeError('boom')):
        resp = auth_client.post('/signalid/sigidwiki', json={'frequency_mhz': 433.92})
    assert resp.status_code == 502
    data = resp.get_json()
    assert data['status'] == 'error'
