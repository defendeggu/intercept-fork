"""Tests for ADS-B history persistence utilities."""

import queue
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestAdsbHistoryWriterUnit:
    """Unit tests for AdsbHistoryWriter (no database)."""

    @pytest.fixture
    def mock_config(self):
        """Mock config with history disabled."""
        with patch.multiple(
            'utils.adsb_history',
            ADSB_HISTORY_ENABLED=False,
            ADSB_DB_HOST='localhost',
            ADSB_DB_PORT=5432,
            ADSB_DB_NAME='test_db',
            ADSB_DB_USER='test',
            ADSB_DB_PASSWORD='test',
            ADSB_HISTORY_BATCH_SIZE=100,
            ADSB_HISTORY_FLUSH_INTERVAL=1.0,
            ADSB_HISTORY_QUEUE_SIZE=1000,
        ):
            yield

    @pytest.fixture
    def mock_config_enabled(self):
        """Mock config with history enabled."""
        with patch.multiple(
            'utils.adsb_history',
            ADSB_HISTORY_ENABLED=True,
            ADSB_DB_HOST='localhost',
            ADSB_DB_PORT=5432,
            ADSB_DB_NAME='test_db',
            ADSB_DB_USER='test',
            ADSB_DB_PASSWORD='test',
            ADSB_HISTORY_BATCH_SIZE=100,
            ADSB_HISTORY_FLUSH_INTERVAL=1.0,
            ADSB_HISTORY_QUEUE_SIZE=1000,
        ):
            yield

    def test_writer_disabled_by_default(self, mock_config):
        """Test writer does nothing when disabled."""
        from utils.adsb_history import AdsbHistoryWriter

        writer = AdsbHistoryWriter()
        writer.enabled = False

        # Should not start thread
        writer.start()
        assert writer._thread is None

        # Should not queue records
        writer.enqueue({'icao': 'ABC123'})
        assert writer._queue.empty()

    def test_enqueue_adds_received_at(self, mock_config_enabled):
        """Test enqueue adds received_at timestamp if missing."""
        from utils.adsb_history import AdsbHistoryWriter

        writer = AdsbHistoryWriter()
        writer.enabled = True

        record = {'icao': 'ABC123'}
        writer.enqueue(record)

        # Record should have received_at added
        assert 'received_at' in record
        assert isinstance(record['received_at'], datetime)

    def test_enqueue_preserves_existing_received_at(self, mock_config_enabled):
        """Test enqueue preserves existing received_at."""
        from utils.adsb_history import AdsbHistoryWriter

        writer = AdsbHistoryWriter()
        writer.enabled = True

        original_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        record = {'icao': 'ABC123', 'received_at': original_time}
        writer.enqueue(record)

        assert record['received_at'] == original_time

    def test_enqueue_drops_when_queue_full(self, mock_config_enabled):
        """Test enqueue drops records when queue is full."""
        from utils.adsb_history import AdsbHistoryWriter

        writer = AdsbHistoryWriter()
        writer.enabled = True
        writer._queue = queue.Queue(maxsize=2)

        # Fill the queue
        writer.enqueue({'icao': 'A'})
        writer.enqueue({'icao': 'B'})

        # This should be dropped
        writer.enqueue({'icao': 'C'})

        assert writer._dropped == 1
        assert writer._queue.qsize() == 2


class TestAdsbSnapshotWriterUnit:
    """Unit tests for AdsbSnapshotWriter (no database)."""

    @pytest.fixture
    def mock_config_enabled(self):
        """Mock config with history enabled."""
        with patch.multiple(
            'utils.adsb_history',
            ADSB_HISTORY_ENABLED=True,
            ADSB_DB_HOST='localhost',
            ADSB_DB_PORT=5432,
            ADSB_DB_NAME='test_db',
            ADSB_DB_USER='test',
            ADSB_DB_PASSWORD='test',
            ADSB_HISTORY_BATCH_SIZE=100,
            ADSB_HISTORY_FLUSH_INTERVAL=1.0,
            ADSB_HISTORY_QUEUE_SIZE=1000,
        ):
            yield

    def test_snapshot_enqueue_adds_captured_at(self, mock_config_enabled):
        """Test enqueue adds captured_at timestamp if missing."""
        from utils.adsb_history import AdsbSnapshotWriter

        writer = AdsbSnapshotWriter()
        writer.enabled = True

        record = {'icao': 'ABC123'}
        writer.enqueue(record)

        assert 'captured_at' in record
        assert isinstance(record['captured_at'], datetime)


class TestMakeDsn:
    """Tests for DSN generation."""

    def test_make_dsn_format(self):
        """Test DSN string format."""
        with patch.multiple(
            'utils.adsb_history',
            ADSB_DB_HOST='testhost',
            ADSB_DB_PORT=5433,
            ADSB_DB_NAME='testdb',
            ADSB_DB_USER='testuser',
            ADSB_DB_PASSWORD='testpass',
        ):
            from utils.adsb_history import _make_dsn

            dsn = _make_dsn()

            assert 'host=testhost' in dsn
            assert 'port=5433' in dsn
            assert 'dbname=testdb' in dsn
            assert 'user=testuser' in dsn
            assert 'password=testpass' in dsn


class TestEnsureAdsbSchema:
    """Tests for schema creation."""

    def test_ensure_schema_creates_tables(self):
        """Test schema creation SQL is executed."""
        from utils.adsb_history import _ensure_adsb_schema

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        _ensure_adsb_schema(mock_conn)

        # Should execute CREATE TABLE statements
        assert mock_cursor.execute.call_count >= 3  # 3 tables + indexes

        # Should commit
        mock_conn.commit.assert_called_once()

    def test_ensure_schema_creates_indexes(self):
        """Test schema creates required indexes."""
        from utils.adsb_history import _ensure_adsb_schema

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        _ensure_adsb_schema(mock_conn)

        # Get all executed SQL
        executed_sql = [str(call) for call in mock_cursor.execute.call_args_list]
        sql_text = ' '.join(executed_sql)

        # Should create indexes
        assert 'CREATE INDEX' in sql_text or 'idx_adsb' in sql_text


class TestMessageFields:
    """Tests for message field constants."""

    def test_message_fields_exist(self):
        """Test required message fields are defined."""
        from utils.adsb_history import _MESSAGE_FIELDS

        required_fields = [
            'received_at', 'icao', 'callsign', 'altitude',
            'speed', 'heading', 'lat', 'lon', 'squawk'
        ]

        for field in required_fields:
            assert field in _MESSAGE_FIELDS

    def test_snapshot_fields_exist(self):
        """Test required snapshot fields are defined."""
        from utils.adsb_history import _SNAPSHOT_FIELDS

        required_fields = [
            'captured_at', 'icao', 'callsign', 'altitude',
            'lat', 'lon', 'snapshot'
        ]

        for field in required_fields:
            assert field in _SNAPSHOT_FIELDS


class TestWriterThreadSafety:
    """Tests for thread safety of writers."""

    def test_multiple_enqueue_thread_safe(self):
        """Test multiple threads can enqueue safely."""
        with patch.multiple(
            'utils.adsb_history',
            ADSB_HISTORY_ENABLED=True,
            ADSB_HISTORY_QUEUE_SIZE=10000,
            ADSB_HISTORY_BATCH_SIZE=100,
            ADSB_HISTORY_FLUSH_INTERVAL=1.0,
            ADSB_DB_HOST='localhost',
            ADSB_DB_PORT=5432,
            ADSB_DB_NAME='test',
            ADSB_DB_USER='test',
            ADSB_DB_PASSWORD='test',
        ):
            from utils.adsb_history import AdsbHistoryWriter

            writer = AdsbHistoryWriter()
            writer.enabled = True
            errors = []

            def enqueue_many(n):
                try:
                    for i in range(n):
                        writer.enqueue({'icao': f'TEST{i}', 'altitude': i * 100})
                except Exception as e:
                    errors.append(e)

            threads = [
                threading.Thread(target=enqueue_many, args=(100,))
                for _ in range(5)
            ]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            # Should have queued 500 records (5 threads * 100 each)
            assert writer._queue.qsize() == 500
