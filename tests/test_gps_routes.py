"""Tests for GPS route behavior and gps client callback management."""

from routes import gps as gps_routes
from utils.gps import GPSDClient


def test_gpsd_client_add_callback_deduplicates():
    """Adding the same position callback twice should only register once."""
    client = GPSDClient()

    def callback(_position):
        return None

    client.add_callback(callback)
    client.add_callback(callback)

    assert client._callbacks.count(callback) == 1


def test_gpsd_client_add_sky_callback_deduplicates():
    """Adding the same sky callback twice should only register once."""
    client = GPSDClient()

    def callback(_sky):
        return None

    client.add_sky_callback(callback)
    client.add_sky_callback(callback)

    assert client._sky_callbacks.count(callback) == 1


def test_auto_connect_attaches_callbacks_when_reader_already_running(client, monkeypatch):
    """Auto-connect should re-attach stream callbacks for an already-running reader."""

    class FakeReader:
        is_running = True
        position = None
        sky = None

        def __init__(self):
            self.position_callbacks = []
            self.sky_callbacks = []

        def add_callback(self, callback):
            self.position_callbacks.append(callback)

        def add_sky_callback(self, callback):
            self.sky_callbacks.append(callback)

    reader = FakeReader()
    monkeypatch.setattr(gps_routes, 'get_gps_reader', lambda: reader)

    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.post('/gps/auto-connect')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['status'] == 'connected'
    assert reader.position_callbacks == [gps_routes._position_callback]
    assert reader.sky_callbacks == [gps_routes._sky_callback]


def test_satellites_returns_waiting_when_reader_not_running(client, monkeypatch):
    """Satellite endpoint should return a non-error waiting state when reader is down."""
    monkeypatch.setattr(gps_routes, 'get_gps_reader', lambda: None)

    with client.session_transaction() as sess:
        sess['logged_in'] = True

    response = client.get('/gps/satellites')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['status'] == 'waiting'
    assert payload['running'] is False
