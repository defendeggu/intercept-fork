"""Alerting engine for cross-mode events."""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generator

from config import ALERT_WEBHOOK_URL, ALERT_WEBHOOK_TIMEOUT, ALERT_WEBHOOK_SECRET
from utils.database import get_db

logger = logging.getLogger('intercept.alerts')


@dataclass
class AlertRule:
    id: int
    name: str
    mode: str | None
    event_type: str | None
    match: dict
    severity: str
    enabled: bool
    notify: dict
    created_at: str | None = None


class AlertManager:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._rules_cache: list[AlertRule] = []
        self._rules_loaded_at = 0.0
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            self._rules_loaded_at = 0.0

    def _load_rules(self) -> None:
        with get_db() as conn:
            cursor = conn.execute('''
                SELECT id, name, mode, event_type, match, severity, enabled, notify, created_at
                FROM alert_rules
                WHERE enabled = 1
                ORDER BY id ASC
            ''')
            rules: list[AlertRule] = []
            for row in cursor:
                match = {}
                notify = {}
                try:
                    match = json.loads(row['match']) if row['match'] else {}
                except json.JSONDecodeError:
                    match = {}
                try:
                    notify = json.loads(row['notify']) if row['notify'] else {}
                except json.JSONDecodeError:
                    notify = {}
                rules.append(AlertRule(
                    id=row['id'],
                    name=row['name'],
                    mode=row['mode'],
                    event_type=row['event_type'],
                    match=match,
                    severity=row['severity'] or 'medium',
                    enabled=bool(row['enabled']),
                    notify=notify,
                    created_at=row['created_at'],
                ))
        with self._cache_lock:
            self._rules_cache = rules
            self._rules_loaded_at = time.time()

    def _get_rules(self) -> list[AlertRule]:
        with self._cache_lock:
            stale = (time.time() - self._rules_loaded_at) > 10
        if stale:
            self._load_rules()
        with self._cache_lock:
            return list(self._rules_cache)

    def list_rules(self, include_disabled: bool = False) -> list[dict]:
        with get_db() as conn:
            if include_disabled:
                cursor = conn.execute('''
                    SELECT id, name, mode, event_type, match, severity, enabled, notify, created_at
                    FROM alert_rules
                    ORDER BY id DESC
                ''')
            else:
                cursor = conn.execute('''
                    SELECT id, name, mode, event_type, match, severity, enabled, notify, created_at
                    FROM alert_rules
                    WHERE enabled = 1
                    ORDER BY id DESC
                ''')

            return [
                {
                    'id': row['id'],
                    'name': row['name'],
                    'mode': row['mode'],
                    'event_type': row['event_type'],
                    'match': json.loads(row['match']) if row['match'] else {},
                    'severity': row['severity'],
                    'enabled': bool(row['enabled']),
                    'notify': json.loads(row['notify']) if row['notify'] else {},
                    'created_at': row['created_at'],
                }
                for row in cursor
            ]

    def add_rule(self, rule: dict) -> int:
        with get_db() as conn:
            cursor = conn.execute('''
                INSERT INTO alert_rules (name, mode, event_type, match, severity, enabled, notify)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                rule.get('name') or 'Alert Rule',
                rule.get('mode'),
                rule.get('event_type'),
                json.dumps(rule.get('match') or {}),
                rule.get('severity') or 'medium',
                1 if rule.get('enabled', True) else 0,
                json.dumps(rule.get('notify') or {}),
            ))
            rule_id = cursor.lastrowid
        self.invalidate_cache()
        return int(rule_id)

    def update_rule(self, rule_id: int, updates: dict) -> bool:
        fields = []
        params = []
        for key in ('name', 'mode', 'event_type', 'severity'):
            if key in updates:
                fields.append(f"{key} = ?")
                params.append(updates[key])
        if 'enabled' in updates:
            fields.append('enabled = ?')
            params.append(1 if updates['enabled'] else 0)
        if 'match' in updates:
            fields.append('match = ?')
            params.append(json.dumps(updates['match'] or {}))
        if 'notify' in updates:
            fields.append('notify = ?')
            params.append(json.dumps(updates['notify'] or {}))

        if not fields:
            return False

        params.append(rule_id)
        with get_db() as conn:
            cursor = conn.execute(
                f"UPDATE alert_rules SET {', '.join(fields)} WHERE id = ?",
                params
            )
            updated = cursor.rowcount > 0

        if updated:
            self.invalidate_cache()
        return updated

    def delete_rule(self, rule_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.execute('DELETE FROM alert_rules WHERE id = ?', (rule_id,))
            deleted = cursor.rowcount > 0
        if deleted:
            self.invalidate_cache()
        return deleted

    def list_events(self, limit: int = 100, mode: str | None = None, severity: str | None = None) -> list[dict]:
        query = 'SELECT id, rule_id, mode, event_type, severity, title, message, payload, created_at FROM alert_events'
        clauses = []
        params: list[Any] = []
        if mode:
            clauses.append('mode = ?')
            params.append(mode)
        if severity:
            clauses.append('severity = ?')
            params.append(severity)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY id DESC LIMIT ?'
        params.append(limit)

        with get_db() as conn:
            cursor = conn.execute(query, params)
            events = []
            for row in cursor:
                events.append({
                    'id': row['id'],
                    'rule_id': row['rule_id'],
                    'mode': row['mode'],
                    'event_type': row['event_type'],
                    'severity': row['severity'],
                    'title': row['title'],
                    'message': row['message'],
                    'payload': json.loads(row['payload']) if row['payload'] else {},
                    'created_at': row['created_at'],
                })
            return events

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    def process_event(self, mode: str, event: dict, event_type: str | None = None) -> None:
        if not isinstance(event, dict):
            return

        if event_type in ('keepalive', 'ping', 'status'):
            return

        rules = self._get_rules()
        if not rules:
            return

        for rule in rules:
            if rule.mode and rule.mode != mode:
                continue
            if rule.event_type and event_type and rule.event_type != event_type:
                continue
            if rule.event_type and not event_type:
                continue
            if not self._match_rule(rule.match, event):
                continue

            title = rule.name or 'Alert'
            message = self._build_message(rule, event, event_type)
            payload = {
                'mode': mode,
                'event_type': event_type,
                'event': event,
                'rule': {
                    'id': rule.id,
                    'name': rule.name,
                },
            }
            event_id = self._store_event(rule.id, mode, event_type, rule.severity, title, message, payload)
            alert_payload = {
                'id': event_id,
                'rule_id': rule.id,
                'mode': mode,
                'event_type': event_type,
                'severity': rule.severity,
                'title': title,
                'message': message,
                'payload': payload,
                'created_at': datetime.now(timezone.utc).isoformat(),
            }
            self._queue_event(alert_payload)
            self._maybe_send_webhook(alert_payload, rule.notify)

    def _build_message(self, rule: AlertRule, event: dict, event_type: str | None) -> str:
        if isinstance(rule.notify, dict) and rule.notify.get('message'):
            return str(rule.notify.get('message'))
        summary_bits = []
        if event_type:
            summary_bits.append(event_type)
        if 'name' in event:
            summary_bits.append(str(event.get('name')))
        if 'ssid' in event:
            summary_bits.append(str(event.get('ssid')))
        if 'bssid' in event:
            summary_bits.append(str(event.get('bssid')))
        if 'address' in event:
            summary_bits.append(str(event.get('address')))
        if 'mac' in event:
            summary_bits.append(str(event.get('mac')))
        summary = ' | '.join(summary_bits) if summary_bits else 'Alert triggered'
        return summary

    def _store_event(
        self,
        rule_id: int,
        mode: str,
        event_type: str | None,
        severity: str,
        title: str,
        message: str,
        payload: dict,
    ) -> int:
        with get_db() as conn:
            cursor = conn.execute('''
                INSERT INTO alert_events (rule_id, mode, event_type, severity, title, message, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                rule_id,
                mode,
                event_type,
                severity,
                title,
                message,
                json.dumps(payload),
            ))
            return int(cursor.lastrowid)

    def _queue_event(self, alert_payload: dict) -> None:
        try:
            self._queue.put_nowait(alert_payload)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(alert_payload)
            except queue.Empty:
                pass

    def _maybe_send_webhook(self, payload: dict, notify: dict) -> None:
        if not ALERT_WEBHOOK_URL:
            return
        if isinstance(notify, dict) and notify.get('webhook') is False:
            return

        try:
            import urllib.request
            req = urllib.request.Request(
                ALERT_WEBHOOK_URL,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Intercept-Alert',
                    'X-Alert-Token': ALERT_WEBHOOK_SECRET or '',
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=ALERT_WEBHOOK_TIMEOUT) as _:
                pass
        except Exception as e:
            logger.debug(f"Alert webhook failed: {e}")

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _match_rule(self, rule_match: dict, event: dict) -> bool:
        if not rule_match:
            return True

        for key, expected in rule_match.items():
            actual = self._extract_value(event, key)
            if not self._match_value(actual, expected):
                return False
        return True

    def _extract_value(self, event: dict, key: str) -> Any:
        if '.' not in key:
            return event.get(key)
        current: Any = event
        for part in key.split('.'):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _match_value(self, actual: Any, expected: Any) -> bool:
        if isinstance(expected, dict) and 'op' in expected:
            op = expected.get('op')
            value = expected.get('value')
            return self._apply_op(op, actual, value)

        if isinstance(expected, list):
            return actual in expected

        if isinstance(expected, str):
            if actual is None:
                return False
            return str(actual).lower() == expected.lower()

        return actual == expected

    def _apply_op(self, op: str, actual: Any, value: Any) -> bool:
        if op == 'exists':
            return actual is not None
        if op == 'eq':
            return actual == value
        if op == 'neq':
            return actual != value
        if op == 'gt':
            return _safe_number(actual) is not None and _safe_number(actual) > _safe_number(value)
        if op == 'gte':
            return _safe_number(actual) is not None and _safe_number(actual) >= _safe_number(value)
        if op == 'lt':
            return _safe_number(actual) is not None and _safe_number(actual) < _safe_number(value)
        if op == 'lte':
            return _safe_number(actual) is not None and _safe_number(actual) <= _safe_number(value)
        if op == 'in':
            return actual in (value or [])
        if op == 'contains':
            if actual is None:
                return False
            if isinstance(actual, list):
                return any(str(value).lower() in str(item).lower() for item in actual)
            return str(value).lower() in str(actual).lower()
        if op == 'regex':
            if actual is None or value is None:
                return False
            try:
                return re.search(str(value), str(actual)) is not None
            except re.error:
                return False
        return False

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream_events(self, timeout: float = 1.0) -> Generator[dict, None, None]:
        while True:
            try:
                event = self._queue.get(timeout=timeout)
                yield event
            except queue.Empty:
                yield {'type': 'keepalive'}


_alert_manager: AlertManager | None = None
_alert_lock = threading.Lock()


def get_alert_manager() -> AlertManager:
    global _alert_manager
    with _alert_lock:
        if _alert_manager is None:
            _alert_manager = AlertManager()
        return _alert_manager


def _safe_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
