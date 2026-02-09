"""Pytest configuration and fixtures."""

import pytest
from app import app as flask_app
from routes import register_blueprints


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    flask_app.config['TESTING'] = True
    # Register blueprints only if not already registered
    if 'pager' not in flask_app.blueprints:
        register_blueprints(flask_app)
    return flask_app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()
