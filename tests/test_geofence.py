"""Tests for geofence haversine, enter/exit detection, and persistence."""

from unittest.mock import MagicMock, patch

import pytest


class TestHaversineDistance:
    """Test haversine_distance accuracy."""

    def test_same_point_zero_distance(self):
        from utils.geofence import haversine_distance
        assert haversine_distance(51.5, -0.1, 51.5, -0.1) == 0.0

    def test_known_distance_london_paris(self):
        from utils.geofence import haversine_distance
        # London to Paris ~340km
        dist = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
        assert 340_000 < dist < 345_000

    def test_short_distance(self):
        from utils.geofence import haversine_distance
        # Two points ~111m apart (0.001 degrees latitude at equator)
        dist = haversine_distance(0.0, 0.0, 0.001, 0.0)
        assert 100 < dist < 120

    def test_antipodal_distance(self):
        from utils.geofence import haversine_distance
        # North pole to south pole ~20015km
        dist = haversine_distance(90.0, 0.0, -90.0, 0.0)
        assert 20_000_000 < dist < 20_050_000


class TestGeofenceManager:
    """Test enter/exit detection logic."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Provide a fresh GeofenceManager with mocked DB."""
        from utils.geofence import GeofenceManager

        with patch('utils.geofence._ensure_table'), patch('utils.geofence.get_db') as mock_db:
            # Mock the context manager
            mock_conn = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            self.manager = GeofenceManager()
            # Override list_zones to return test data
            self._zones = []
            self.manager.list_zones = lambda: self._zones

    def test_no_zones_returns_empty(self):
        events = self.manager.check_position('TEST1', 'aircraft', 51.5, -0.1)
        assert events == []

    def test_enter_event(self):
        self._zones = [{
            'id': 1, 'name': 'London', 'lat': 51.5074, 'lon': -0.1278,
            'radius_m': 10000, 'alert_on': 'enter_exit',
        }]
        # First position inside zone
        events = self.manager.check_position('AC1', 'aircraft', 51.5074, -0.1278)
        assert len(events) == 1
        assert events[0]['type'] == 'geofence_enter'
        assert events[0]['zone_name'] == 'London'

    def test_no_duplicate_enter(self):
        self._zones = [{
            'id': 1, 'name': 'London', 'lat': 51.5074, 'lon': -0.1278,
            'radius_m': 10000, 'alert_on': 'enter_exit',
        }]
        # First enter
        self.manager.check_position('AC1', 'aircraft', 51.5074, -0.1278)
        # Second check still inside - should not fire enter again
        events = self.manager.check_position('AC1', 'aircraft', 51.508, -0.128)
        assert len(events) == 0

    def test_exit_event(self):
        self._zones = [{
            'id': 1, 'name': 'London', 'lat': 51.5074, 'lon': -0.1278,
            'radius_m': 1000, 'alert_on': 'enter_exit',
        }]
        # Enter
        self.manager.check_position('AC1', 'aircraft', 51.5074, -0.1278)
        # Exit (far away)
        events = self.manager.check_position('AC1', 'aircraft', 52.0, 0.0)
        assert len(events) == 1
        assert events[0]['type'] == 'geofence_exit'

    def test_enter_only_mode(self):
        self._zones = [{
            'id': 1, 'name': 'London', 'lat': 51.5074, 'lon': -0.1278,
            'radius_m': 1000, 'alert_on': 'enter',
        }]
        # Enter
        events = self.manager.check_position('AC1', 'aircraft', 51.5074, -0.1278)
        assert len(events) == 1
        assert events[0]['type'] == 'geofence_enter'
        # Exit should not fire
        events = self.manager.check_position('AC1', 'aircraft', 52.0, 0.0)
        assert len(events) == 0

    def test_metadata_included_in_event(self):
        self._zones = [{
            'id': 1, 'name': 'Zone', 'lat': 0.0, 'lon': 0.0,
            'radius_m': 100000, 'alert_on': 'enter_exit',
        }]
        events = self.manager.check_position(
            'AC1', 'aircraft', 0.0, 0.0,
            metadata={'callsign': 'TEST01', 'altitude': 35000}
        )
        assert events[0]['callsign'] == 'TEST01'
        assert events[0]['altitude'] == 35000
