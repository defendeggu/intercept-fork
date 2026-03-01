"""Session recording utilities for SSE/event streams."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.database import get_db

logger = logging.getLogger('intercept.recording')

RECORDING_ROOT = Path(__file__).parent.parent / 'instance' / 'recordings'


@dataclass
class RecordingSession:
    id: str
    mode: str
    label: str | None
    file_path: Path
    started_at: datetime
    stopped_at: datetime | None = None
    event_count: int = 0
    size_bytes: int = 0
    metadata: dict | None = None

    _file_handle: Any | None = None
    _lock: threading.Lock = threading.Lock()

    def open(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_handle = self.file_path.open('a', encoding='utf-8')

    def close(self) -> None:
        if self._file_handle:
            self._file_handle.flush()
            self._file_handle.close()
            self._file_handle = None

    def write_event(self, record: dict) -> None:
        if not self._file_handle:
            self.open()
        line = json.dumps(record, ensure_ascii=True) + '\n'
        with self._lock:
            self._file_handle.write(line)
            self._file_handle.flush()
            self.event_count += 1
            self.size_bytes += len(line.encode('utf-8'))


class RecordingManager:
    def __init__(self) -> None:
        self._active_by_mode: dict[str, RecordingSession] = {}
        self._active_by_id: dict[str, RecordingSession] = {}
        self._lock = threading.Lock()

    def start_recording(self, mode: str, label: str | None = None, metadata: dict | None = None) -> RecordingSession:
        with self._lock:
            existing = self._active_by_mode.get(mode)
            if existing:
                return existing

            session_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc)
            filename = f"{mode}_{started_at.strftime('%Y%m%d_%H%M%S')}_{session_id}.jsonl"
            file_path = RECORDING_ROOT / mode / filename

            session = RecordingSession(
                id=session_id,
                mode=mode,
                label=label,
                file_path=file_path,
                started_at=started_at,
                metadata=metadata or {},
            )
            session.open()

            self._active_by_mode[mode] = session
            self._active_by_id[session_id] = session

            with get_db() as conn:
                conn.execute('''
                    INSERT INTO recording_sessions
                    (id, mode, label, started_at, file_path, event_count, size_bytes, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session.id,
                    session.mode,
                    session.label,
                    session.started_at.isoformat(),
                    str(session.file_path),
                    session.event_count,
                    session.size_bytes,
                    json.dumps(session.metadata or {}),
                ))

            return session

    def stop_recording(self, mode: str | None = None, session_id: str | None = None) -> RecordingSession | None:
        with self._lock:
            session = None
            if session_id:
                session = self._active_by_id.get(session_id)
            elif mode:
                session = self._active_by_mode.get(mode)

            if not session:
                return None

            session.stopped_at = datetime.now(timezone.utc)
            session.close()

            self._active_by_mode.pop(session.mode, None)
            self._active_by_id.pop(session.id, None)

            with get_db() as conn:
                conn.execute('''
                    UPDATE recording_sessions
                    SET stopped_at = ?, event_count = ?, size_bytes = ?
                    WHERE id = ?
                ''', (
                    session.stopped_at.isoformat(),
                    session.event_count,
                    session.size_bytes,
                    session.id,
                ))

            return session

    def record_event(self, mode: str, event: dict, event_type: str | None = None) -> None:
        if event_type in ('keepalive', 'ping'):
            return
        session = self._active_by_mode.get(mode)
        if not session:
            return
        record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'mode': mode,
            'event_type': event_type,
            'event': event,
        }
        try:
            session.write_event(record)
        except Exception as e:
            logger.debug(f"Recording write failed: {e}")

    def list_recordings(self, limit: int = 50) -> list[dict]:
        with get_db() as conn:
            cursor = conn.execute('''
                SELECT id, mode, label, started_at, stopped_at, file_path, event_count, size_bytes, metadata
                FROM recording_sessions
                ORDER BY started_at DESC
                LIMIT ?
            ''', (limit,))
            rows = []
            for row in cursor:
                rows.append({
                    'id': row['id'],
                    'mode': row['mode'],
                    'label': row['label'],
                    'started_at': row['started_at'],
                    'stopped_at': row['stopped_at'],
                    'file_path': row['file_path'],
                    'event_count': row['event_count'],
                    'size_bytes': row['size_bytes'],
                    'metadata': json.loads(row['metadata']) if row['metadata'] else {},
                })
            return rows

    def get_recording(self, session_id: str) -> dict | None:
        with get_db() as conn:
            cursor = conn.execute('''
                SELECT id, mode, label, started_at, stopped_at, file_path, event_count, size_bytes, metadata
                FROM recording_sessions
                WHERE id = ?
            ''', (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                'id': row['id'],
                'mode': row['mode'],
                'label': row['label'],
                'started_at': row['started_at'],
                'stopped_at': row['stopped_at'],
                'file_path': row['file_path'],
                'event_count': row['event_count'],
                'size_bytes': row['size_bytes'],
                'metadata': json.loads(row['metadata']) if row['metadata'] else {},
            }

    def get_active(self) -> list[dict]:
        with self._lock:
            sessions = []
            for session in self._active_by_mode.values():
                sessions.append({
                    'id': session.id,
                    'mode': session.mode,
                    'label': session.label,
                    'started_at': session.started_at.isoformat(),
                    'event_count': session.event_count,
                    'size_bytes': session.size_bytes,
                })
            return sessions


_recording_manager: RecordingManager | None = None
_recording_lock = threading.Lock()


def get_recording_manager() -> RecordingManager:
    global _recording_manager
    with _recording_lock:
        if _recording_manager is None:
            _recording_manager = RecordingManager()
        return _recording_manager
