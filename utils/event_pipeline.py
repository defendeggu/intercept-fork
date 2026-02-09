"""Shared event pipeline for alerts and recordings."""

from __future__ import annotations

from typing import Any

from utils.alerts import get_alert_manager
from utils.recording import get_recording_manager

IGNORE_TYPES = {'keepalive', 'ping'}


def process_event(mode: str, event: dict | Any, event_type: str | None = None) -> None:
    if event_type in IGNORE_TYPES:
        return
    if not isinstance(event, dict):
        return

    try:
        get_recording_manager().record_event(mode, event, event_type)
    except Exception:
        # Recording failures should never break streaming
        pass

    try:
        get_alert_manager().process_event(mode, event, event_type)
    except Exception:
        # Alert failures should never break streaming
        pass
