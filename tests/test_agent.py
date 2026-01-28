"""
Tests for Intercept Agent components.

Tests cover:
- AgentConfig parsing
- AgentClient HTTP operations
- Database agent CRUD operations
- GPS integration
"""

import json
import os
import pytest
import tempfile
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.agent_client import (
    AgentClient, AgentHTTPError, AgentConnectionError, create_client_from_agent
)
from utils.database import (
    init_db, get_db_path, create_agent, get_agent, get_agent_by_name,
    list_agents, update_agent, delete_agent, store_push_payload,
    get_recent_payloads, cleanup_old_payloads
)


# =============================================================================
# AgentConfig Tests
# =============================================================================

class TestAgentConfig:
    """Tests for AgentConfig class."""

    def test_default_values(self):
        """AgentConfig should have sensible defaults."""
        from intercept_agent import AgentConfig
        config = AgentConfig()

        assert config.port == 8020
        assert config.allow_cors is False
        assert config.push_enabled is False
        assert config.push_interval == 5
        assert config.controller_url == ''
        assert 'adsb' in config.modes_enabled
        assert 'wifi' in config.modes_enabled
        assert config.modes_enabled['adsb'] is True

    def test_load_from_file_valid(self):
        """AgentConfig should load from valid INI file."""
        from intercept_agent import AgentConfig

        config_content = """
[agent]
name = test-sensor
port = 8025
allowed_ips = 192.168.1.0/24, 10.0.0.1
allow_cors = true

[controller]
url = http://192.168.1.100:5050
api_key = secret123
push_enabled = true
push_interval = 10

[modes]
pager = false
adsb = true
wifi = true
bluetooth = false
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cfg', delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            config = AgentConfig()
            result = config.load_from_file(config_path)

            assert result is True
            assert config.name == 'test-sensor'
            assert config.port == 8025
            assert '192.168.1.0/24' in config.allowed_ips
            assert config.allow_cors is True
            assert config.controller_url == 'http://192.168.1.100:5050'
            assert config.controller_api_key == 'secret123'
            assert config.push_enabled is True
            assert config.push_interval == 10
            assert config.modes_enabled['pager'] is False
            assert config.modes_enabled['adsb'] is True
            assert config.modes_enabled['bluetooth'] is False
        finally:
            os.unlink(config_path)

    def test_load_from_file_missing(self):
        """AgentConfig should handle missing file gracefully."""
        from intercept_agent import AgentConfig
        config = AgentConfig()
        result = config.load_from_file('/nonexistent/path.cfg')
        assert result is False

    def test_to_dict(self):
        """AgentConfig should convert to dictionary."""
        from intercept_agent import AgentConfig
        config = AgentConfig()
        config.name = 'test'
        config.port = 9000

        d = config.to_dict()

        assert d['name'] == 'test'
        assert d['port'] == 9000
        assert 'modes_enabled' in d
        assert isinstance(d['modes_enabled'], dict)


# =============================================================================
# AgentClient Tests
# =============================================================================

class TestAgentClient:
    """Tests for AgentClient HTTP operations."""

    def test_init(self):
        """AgentClient should initialize correctly."""
        client = AgentClient('http://192.168.1.50:8020', api_key='secret')
        assert client.base_url == 'http://192.168.1.50:8020'
        assert client.api_key == 'secret'
        assert client.timeout == 60.0

    def test_init_strips_trailing_slash(self):
        """AgentClient should strip trailing slash from URL."""
        client = AgentClient('http://192.168.1.50:8020/')
        assert client.base_url == 'http://192.168.1.50:8020'

    def test_headers_without_api_key(self):
        """Headers should not include API key if not provided."""
        client = AgentClient('http://localhost:8020')
        headers = client._headers()
        assert 'X-API-Key' not in headers
        assert 'Content-Type' in headers

    def test_headers_with_api_key(self):
        """Headers should include API key if provided."""
        client = AgentClient('http://localhost:8020', api_key='test-key')
        headers = client._headers()
        assert headers['X-API-Key'] == 'test-key'

    @patch('utils.agent_client.requests.get')
    def test_get_capabilities(self, mock_get):
        """get_capabilities should parse JSON response."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'modes': {'adsb': True, 'wifi': True},
            'devices': [{'name': 'RTL-SDR'}],
            'agent_version': '1.0.0'
        }
        mock_response.content = b'{}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = AgentClient('http://localhost:8020')
        caps = client.get_capabilities()

        assert caps['modes']['adsb'] is True
        assert len(caps['devices']) == 1
        mock_get.assert_called_once()

    @patch('utils.agent_client.requests.get')
    def test_get_status(self, mock_get):
        """get_status should return status dict."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'running_modes': ['adsb', 'sensor'],
            'uptime': 3600,
            'push_enabled': True
        }
        mock_response.content = b'{}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = AgentClient('http://localhost:8020')
        status = client.get_status()

        assert 'adsb' in status['running_modes']
        assert status['uptime'] == 3600

    @patch('utils.agent_client.requests.get')
    def test_health_check_healthy(self, mock_get):
        """health_check should return True for healthy agent."""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'healthy'}
        mock_response.content = b'{}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = AgentClient('http://localhost:8020')
        assert client.health_check() is True

    @patch('utils.agent_client.requests.get')
    def test_health_check_unhealthy(self, mock_get):
        """health_check should return False for connection error."""
        import requests
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        client = AgentClient('http://localhost:8020')
        assert client.health_check() is False

    @patch('utils.agent_client.requests.post')
    def test_start_mode(self, mock_post):
        """start_mode should POST to correct endpoint."""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'started', 'mode': 'adsb'}
        mock_response.content = b'{}'
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client = AgentClient('http://localhost:8020')
        result = client.start_mode('adsb', {'device_index': 0})

        assert result['status'] == 'started'
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert '/adsb/start' in call_url

    @patch('utils.agent_client.requests.post')
    def test_stop_mode(self, mock_post):
        """stop_mode should POST to stop endpoint."""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'stopped'}
        mock_response.content = b'{}'
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client = AgentClient('http://localhost:8020')
        result = client.stop_mode('wifi')

        assert result['status'] == 'stopped'

    @patch('utils.agent_client.requests.get')
    def test_get_mode_data(self, mock_get):
        """get_mode_data should return data snapshot."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'mode': 'adsb',
            'data': [
                {'icao': 'ABC123', 'altitude': 35000},
                {'icao': 'DEF456', 'altitude': 28000}
            ]
        }
        mock_response.content = b'{}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = AgentClient('http://localhost:8020')
        result = client.get_mode_data('adsb')

        assert len(result['data']) == 2
        assert result['data'][0]['icao'] == 'ABC123'

    @patch('utils.agent_client.requests.get')
    def test_connection_error_handling(self, mock_get):
        """Client should raise AgentConnectionError on connection failure."""
        import requests
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        client = AgentClient('http://localhost:8020')

        with pytest.raises(AgentConnectionError) as exc_info:
            client.get_capabilities()
        assert 'Cannot connect' in str(exc_info.value)

    @patch('utils.agent_client.requests.get')
    def test_timeout_error_handling(self, mock_get):
        """Client should raise AgentConnectionError on timeout."""
        import requests
        mock_get.side_effect = requests.Timeout("Request timed out")

        client = AgentClient('http://localhost:8020', timeout=5.0)

        with pytest.raises(AgentConnectionError) as exc_info:
            client.get_status()
        assert 'timed out' in str(exc_info.value)

    @patch('utils.agent_client.requests.get')
    def test_http_error_handling(self, mock_get):
        """Client should raise AgentHTTPError on HTTP errors."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        client = AgentClient('http://localhost:8020')

        with pytest.raises(AgentHTTPError) as exc_info:
            client.get_capabilities()
        assert exc_info.value.status_code == 500

    def test_create_client_from_agent(self):
        """create_client_from_agent should create configured client."""
        agent = {
            'id': 1,
            'name': 'test-agent',
            'base_url': 'http://192.168.1.50:8020',
            'api_key': 'secret123'
        }

        client = create_client_from_agent(agent)

        assert client.base_url == 'http://192.168.1.50:8020'
        assert client.api_key == 'secret123'


# =============================================================================
# Database Agent CRUD Tests
# =============================================================================

class TestDatabaseAgentCRUD:
    """Tests for database agent operations."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Set up a temporary database for each test."""
        import utils.database as db_module

        # Create temp database
        test_db_path = tmp_path / 'test.db'
        original_db_path = db_module.DB_PATH
        db_module.DB_PATH = test_db_path
        db_module.DB_DIR = tmp_path

        # Clear any existing connection
        if hasattr(db_module._local, 'connection') and db_module._local.connection:
            db_module._local.connection.close()
            db_module._local.connection = None

        # Initialize schema
        init_db()

        yield

        # Cleanup
        if hasattr(db_module._local, 'connection') and db_module._local.connection:
            db_module._local.connection.close()
            db_module._local.connection = None
        db_module.DB_PATH = original_db_path

    def test_create_agent(self):
        """create_agent should insert new agent."""
        agent_id = create_agent(
            name='sensor-1',
            base_url='http://192.168.1.50:8020',
            api_key='secret',
            description='Test sensor node'
        )

        assert agent_id is not None
        assert agent_id > 0

    def test_get_agent(self):
        """get_agent should retrieve agent by ID."""
        agent_id = create_agent(
            name='sensor-1',
            base_url='http://192.168.1.50:8020'
        )

        agent = get_agent(agent_id)

        assert agent is not None
        assert agent['name'] == 'sensor-1'
        assert agent['base_url'] == 'http://192.168.1.50:8020'
        assert agent['is_active'] is True

    def test_get_agent_not_found(self):
        """get_agent should return None for missing agent."""
        agent = get_agent(99999)
        assert agent is None

    def test_get_agent_by_name(self):
        """get_agent_by_name should find agent by name."""
        create_agent(name='unique-sensor', base_url='http://localhost:8020')

        agent = get_agent_by_name('unique-sensor')

        assert agent is not None
        assert agent['name'] == 'unique-sensor'

    def test_get_agent_by_name_not_found(self):
        """get_agent_by_name should return None for missing name."""
        agent = get_agent_by_name('nonexistent-sensor')
        assert agent is None

    def test_list_agents(self):
        """list_agents should return all active agents."""
        create_agent(name='sensor-1', base_url='http://192.168.1.51:8020')
        create_agent(name='sensor-2', base_url='http://192.168.1.52:8020')
        create_agent(name='sensor-3', base_url='http://192.168.1.53:8020')

        agents = list_agents()

        assert len(agents) >= 3
        names = [a['name'] for a in agents]
        assert 'sensor-1' in names
        assert 'sensor-2' in names

    def test_list_agents_active_only(self):
        """list_agents should filter inactive agents by default."""
        agent_id = create_agent(name='inactive-sensor', base_url='http://localhost:8020')
        update_agent(agent_id, is_active=False)

        agents = list_agents(active_only=True)

        names = [a['name'] for a in agents]
        assert 'inactive-sensor' not in names

    def test_update_agent(self):
        """update_agent should modify agent fields."""
        agent_id = create_agent(name='sensor-1', base_url='http://localhost:8020')

        result = update_agent(
            agent_id,
            base_url='http://192.168.1.100:8020',
            description='Updated description'
        )

        assert result is True

        agent = get_agent(agent_id)
        assert agent['base_url'] == 'http://192.168.1.100:8020'
        assert agent['description'] == 'Updated description'

    def test_update_agent_capabilities(self):
        """update_agent should update capabilities JSON."""
        agent_id = create_agent(name='sensor-1', base_url='http://localhost:8020')

        caps = {'adsb': True, 'wifi': True, 'bluetooth': False}
        update_agent(agent_id, capabilities=caps)

        agent = get_agent(agent_id)
        assert agent['capabilities']['adsb'] is True
        assert agent['capabilities']['bluetooth'] is False

    def test_update_agent_gps_coords(self):
        """update_agent should update GPS coordinates."""
        agent_id = create_agent(name='sensor-1', base_url='http://localhost:8020')

        gps = {'lat': 40.7128, 'lon': -74.0060, 'altitude': 10}
        update_agent(agent_id, gps_coords=gps)

        agent = get_agent(agent_id)
        assert agent['gps_coords']['lat'] == 40.7128
        assert agent['gps_coords']['lon'] == -74.0060

    def test_delete_agent(self):
        """delete_agent should remove agent and payloads."""
        agent_id = create_agent(name='to-delete', base_url='http://localhost:8020')

        # Add a payload
        store_push_payload(agent_id, 'adsb', {'aircraft': []})

        # Delete
        result = delete_agent(agent_id)

        assert result is True
        assert get_agent(agent_id) is None

    def test_delete_agent_not_found(self):
        """delete_agent should return False for missing agent."""
        result = delete_agent(99999)
        assert result is False


# =============================================================================
# Database Push Payload Tests
# =============================================================================

class TestDatabasePayloads:
    """Tests for push payload storage."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Set up a temporary database for each test."""
        import utils.database as db_module

        test_db_path = tmp_path / 'test.db'
        original_db_path = db_module.DB_PATH
        db_module.DB_PATH = test_db_path
        db_module.DB_DIR = tmp_path

        if hasattr(db_module._local, 'connection') and db_module._local.connection:
            db_module._local.connection.close()
            db_module._local.connection = None

        init_db()

        yield

        if hasattr(db_module._local, 'connection') and db_module._local.connection:
            db_module._local.connection.close()
            db_module._local.connection = None
        db_module.DB_PATH = original_db_path

    def test_store_push_payload(self):
        """store_push_payload should insert payload."""
        agent_id = create_agent(name='sensor-1', base_url='http://localhost:8020')

        payload = {'aircraft': [{'icao': 'ABC123', 'altitude': 35000}]}
        payload_id = store_push_payload(agent_id, 'adsb', payload, 'rtlsdr0')

        assert payload_id > 0

    def test_get_recent_payloads(self):
        """get_recent_payloads should return stored payloads."""
        agent_id = create_agent(name='sensor-1', base_url='http://localhost:8020')

        store_push_payload(agent_id, 'adsb', {'aircraft': [{'icao': 'A'}]})
        store_push_payload(agent_id, 'adsb', {'aircraft': [{'icao': 'B'}]})
        store_push_payload(agent_id, 'wifi', {'networks': []})

        # Get all
        payloads = get_recent_payloads(agent_id=agent_id)
        assert len(payloads) == 3

        # Filter by scan_type
        adsb_payloads = get_recent_payloads(agent_id=agent_id, scan_type='adsb')
        assert len(adsb_payloads) == 2

    def test_get_recent_payloads_includes_agent_name(self):
        """Payloads should include agent name."""
        agent_id = create_agent(name='my-sensor', base_url='http://localhost:8020')
        store_push_payload(agent_id, 'sensor', {'temperature': 22.5})

        payloads = get_recent_payloads(agent_id=agent_id)

        assert len(payloads) > 0
        assert payloads[0]['agent_name'] == 'my-sensor'

    def test_get_recent_payloads_limit(self):
        """get_recent_payloads should respect limit."""
        agent_id = create_agent(name='sensor-1', base_url='http://localhost:8020')

        for i in range(10):
            store_push_payload(agent_id, 'sensor', {'temp': i})

        payloads = get_recent_payloads(agent_id=agent_id, limit=5)
        assert len(payloads) == 5


# =============================================================================
# Integration Tests
# =============================================================================

class TestAgentClientIntegration:
    """Integration tests using mock agent server."""

    @pytest.fixture
    def mock_agent(self):
        """Start mock agent server for testing."""
        from tests.mock_agent import app as mock_app
        import threading

        # Run mock agent in background
        mock_app.config['TESTING'] = True
        # Using Flask's test client instead of actual server
        return mock_app.test_client()

    def test_mock_agent_capabilities(self, mock_agent):
        """Mock agent should return capabilities."""
        response = mock_agent.get('/capabilities')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'modes' in data
        assert data['modes']['adsb'] is True

    def test_mock_agent_start_stop_mode(self, mock_agent):
        """Mock agent should start/stop modes."""
        # Start
        response = mock_agent.post('/adsb/start', json={})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'started'

        # Check status
        response = mock_agent.get('/status')
        data = json.loads(response.data)
        assert 'adsb' in data['running_modes']

        # Stop
        response = mock_agent.post('/adsb/stop', json={})
        assert response.status_code == 200

    def test_mock_agent_data(self, mock_agent):
        """Mock agent should return data when mode is running."""
        # Start mode first
        mock_agent.post('/adsb/start', json={})

        response = mock_agent.get('/adsb/data')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'data' in data
        # Data should be a list of aircraft
        assert isinstance(data['data'], list)

        # Cleanup
        mock_agent.post('/adsb/stop', json={})


# =============================================================================
# GPS Manager Tests
# =============================================================================

class TestGPSManager:
    """Tests for GPS integration in agent."""

    def test_gps_manager_init(self):
        """GPSManager should initialize without error."""
        from intercept_agent import GPSManager
        gps = GPSManager()
        assert gps.position is None
        assert gps._running is False

    def test_gps_manager_position_format(self):
        """GPSManager position should have correct format when set."""
        from intercept_agent import GPSManager

        gps = GPSManager()

        # Simulate a position update
        class MockPosition:
            latitude = 40.7128
            longitude = -74.0060
            altitude = 10.5
            speed = 0.0
            heading = 180.0
            fix_quality = 2

        gps._position = MockPosition()
        pos = gps.position

        assert pos is not None
        assert pos['lat'] == 40.7128
        assert pos['lon'] == -74.0060
        assert pos['altitude'] == 10.5
