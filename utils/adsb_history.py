"""ADS-B history persistence to PostgreSQL."""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Iterable

# psycopg2 is optional - only needed for PostgreSQL history persistence
try:
    import psycopg2
    from psycopg2.extras import execute_values, Json
    PSYCOPG2_AVAILABLE = True
except ImportError:
    psycopg2 = None  # type: ignore
    execute_values = None  # type: ignore
    Json = None  # type: ignore
    PSYCOPG2_AVAILABLE = False

from config import (
    ADSB_DB_HOST,
    ADSB_DB_NAME,
    ADSB_DB_PASSWORD,
    ADSB_DB_PORT,
    ADSB_DB_USER,
    ADSB_HISTORY_BATCH_SIZE,
    ADSB_HISTORY_ENABLED,
    ADSB_HISTORY_FLUSH_INTERVAL,
    ADSB_HISTORY_QUEUE_SIZE,
)

logger = logging.getLogger('intercept.adsb_history')


_MESSAGE_FIELDS = (
    'received_at',
    'msg_time',
    'logged_time',
    'icao',
    'msg_type',
    'callsign',
    'altitude',
    'speed',
    'heading',
    'vertical_rate',
    'lat',
    'lon',
    'squawk',
    'session_id',
    'aircraft_id',
    'flight_id',
    'raw_line',
    'source_host',
)

_MESSAGE_INSERT_SQL = f"""
    INSERT INTO adsb_messages ({', '.join(_MESSAGE_FIELDS)})
    VALUES %s
"""

_SNAPSHOT_FIELDS = (
    'captured_at',
    'icao',
    'callsign',
    'registration',
    'type_code',
    'type_desc',
    'altitude',
    'speed',
    'heading',
    'vertical_rate',
    'lat',
    'lon',
    'squawk',
    'source_host',
    'snapshot',
)

_SNAPSHOT_INSERT_SQL = f"""
    INSERT INTO adsb_snapshots ({', '.join(_SNAPSHOT_FIELDS)})
    VALUES %s
"""

def _ensure_adsb_schema(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS adsb_messages (
                id BIGSERIAL PRIMARY KEY,
                received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                msg_time TIMESTAMPTZ,
                logged_time TIMESTAMPTZ,
                icao TEXT NOT NULL,
                msg_type SMALLINT,
                callsign TEXT,
                altitude INTEGER,
                speed INTEGER,
                heading INTEGER,
                vertical_rate INTEGER,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                squawk TEXT,
                session_id TEXT,
                aircraft_id TEXT,
                flight_id TEXT,
                raw_line TEXT,
                source_host TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_messages_icao_time
            ON adsb_messages (icao, received_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_messages_received_at
            ON adsb_messages (received_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_messages_msg_time
            ON adsb_messages (msg_time)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS adsb_snapshots (
                id BIGSERIAL PRIMARY KEY,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                icao TEXT NOT NULL,
                callsign TEXT,
                registration TEXT,
                type_code TEXT,
                type_desc TEXT,
                altitude INTEGER,
                speed INTEGER,
                heading INTEGER,
                vertical_rate INTEGER,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                squawk TEXT,
                source_host TEXT,
                snapshot JSONB
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_snapshots_icao_time
            ON adsb_snapshots (icao, captured_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_snapshots_captured_at
            ON adsb_snapshots (captured_at)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS adsb_sessions (
                id BIGSERIAL PRIMARY KEY,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ended_at TIMESTAMPTZ,
                device_index INTEGER,
                sdr_type TEXT,
                remote_host TEXT,
                remote_port INTEGER,
                start_source TEXT,
                stop_source TEXT,
                started_by TEXT,
                stopped_by TEXT,
                notes TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_sessions_started_at
            ON adsb_sessions (started_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_adsb_sessions_active
            ON adsb_sessions (ended_at)
            """
        )
    conn.commit()


def _make_dsn() -> str:
    return (
        f"host={ADSB_DB_HOST} port={ADSB_DB_PORT} dbname={ADSB_DB_NAME} "
        f"user={ADSB_DB_USER} password={ADSB_DB_PASSWORD}"
    )


class AdsbHistoryWriter:
    """Background writer for ADS-B history records."""

    def __init__(self) -> None:
        self.enabled = ADSB_HISTORY_ENABLED and PSYCOPG2_AVAILABLE
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=ADSB_HISTORY_QUEUE_SIZE)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._conn: psycopg2.extensions.connection | None = None
        self._dropped = 0

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name='adsb-history-writer', daemon=True)
        self._thread.start()
        logger.info("ADS-B history writer started")

    def stop(self) -> None:
        self._stop_event.set()

    def enqueue(self, record: dict) -> None:
        if not self.enabled:
            return
        if 'received_at' not in record or record['received_at'] is None:
            record['received_at'] = datetime.now(timezone.utc)
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._dropped += 1
            if self._dropped % 1000 == 0:
                logger.warning("ADS-B history queue full, dropped %d records", self._dropped)

    def _run(self) -> None:
        batch: list[dict] = []
        last_flush = time.time()

        while not self._stop_event.is_set():
            timeout = max(0.0, ADSB_HISTORY_FLUSH_INTERVAL - (time.time() - last_flush))
            try:
                item = self._queue.get(timeout=timeout)
                batch.append(item)
            except queue.Empty:
                pass

            now = time.time()
            if batch and (len(batch) >= ADSB_HISTORY_BATCH_SIZE or now - last_flush >= ADSB_HISTORY_FLUSH_INTERVAL):
                if self._flush(batch):
                    batch.clear()
                    last_flush = now

    def _ensure_connection(self) -> psycopg2.extensions.connection | None:
        if self._conn:
            return self._conn
        try:
            self._conn = psycopg2.connect(_make_dsn())
            self._conn.autocommit = False
            self._ensure_schema(self._conn)
            return self._conn
        except Exception as exc:
            logger.warning("ADS-B history DB connection failed: %s", exc)
            self._conn = None
            return None

    def _ensure_schema(self, conn: psycopg2.extensions.connection) -> None:
        _ensure_adsb_schema(conn)

    def _flush(self, batch: Iterable[dict]) -> bool:
        conn = self._ensure_connection()
        if not conn:
            time.sleep(2.0)
            return False

        values = []
        for record in batch:
            values.append(tuple(record.get(field) for field in _MESSAGE_FIELDS))

        try:
            with conn.cursor() as cur:
                execute_values(cur, _MESSAGE_INSERT_SQL, values)
            conn.commit()
            return True
        except Exception as exc:
            logger.warning("ADS-B history insert failed: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            self._conn = None
            time.sleep(2.0)
            return False


adsb_history_writer = AdsbHistoryWriter()


class AdsbSnapshotWriter:
    """Background writer for ADS-B snapshot records."""

    def __init__(self) -> None:
        self.enabled = ADSB_HISTORY_ENABLED and PSYCOPG2_AVAILABLE
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=ADSB_HISTORY_QUEUE_SIZE)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._conn: psycopg2.extensions.connection | None = None
        self._dropped = 0

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name='adsb-snapshot-writer', daemon=True)
        self._thread.start()
        logger.info("ADS-B snapshot writer started")

    def stop(self) -> None:
        self._stop_event.set()

    def enqueue(self, record: dict) -> None:
        if not self.enabled:
            return
        if 'captured_at' not in record or record['captured_at'] is None:
            record['captured_at'] = datetime.now(timezone.utc)
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._dropped += 1
            if self._dropped % 1000 == 0:
                logger.warning("ADS-B snapshot queue full, dropped %d records", self._dropped)

    def _run(self) -> None:
        batch: list[dict] = []
        last_flush = time.time()

        while not self._stop_event.is_set():
            timeout = max(0.0, ADSB_HISTORY_FLUSH_INTERVAL - (time.time() - last_flush))
            try:
                item = self._queue.get(timeout=timeout)
                batch.append(item)
            except queue.Empty:
                pass

            now = time.time()
            if batch and (len(batch) >= ADSB_HISTORY_BATCH_SIZE or now - last_flush >= ADSB_HISTORY_FLUSH_INTERVAL):
                if self._flush(batch):
                    batch.clear()
                    last_flush = now

    def _ensure_connection(self) -> psycopg2.extensions.connection | None:
        if self._conn:
            return self._conn
        try:
            self._conn = psycopg2.connect(_make_dsn())
            self._conn.autocommit = False
            self._ensure_schema(self._conn)
            return self._conn
        except Exception as exc:
            logger.warning("ADS-B snapshot DB connection failed: %s", exc)
            self._conn = None
            return None

    def _ensure_schema(self, conn: psycopg2.extensions.connection) -> None:
        _ensure_adsb_schema(conn)

    def _flush(self, batch: Iterable[dict]) -> bool:
        conn = self._ensure_connection()
        if not conn:
            time.sleep(2.0)
            return False

        values = []
        for record in batch:
            row = []
            for field in _SNAPSHOT_FIELDS:
                value = record.get(field)
                if field == 'snapshot' and value is not None:
                    value = Json(value)
                row.append(value)
            values.append(tuple(row))

        try:
            with conn.cursor() as cur:
                execute_values(cur, _SNAPSHOT_INSERT_SQL, values)
            conn.commit()
            return True
        except Exception as exc:
            logger.warning("ADS-B snapshot insert failed: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            self._conn = None
            time.sleep(2.0)
            return False


adsb_snapshot_writer = AdsbSnapshotWriter()
