"""Tests for SSE fanout queue behavior."""

from __future__ import annotations

import queue
import time
import uuid

import pytest

from utils.sse import subscribe_fanout_queue


def _channel_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def test_fanout_drains_source_queue_without_subscribers() -> None:
    """Queued messages should be dropped while no SSE clients are connected."""
    source = queue.Queue()
    channel_key = _channel_key("sse-idle")

    # Start fanout distributor, then remove the only subscriber.
    _, unsubscribe = subscribe_fanout_queue(source, channel_key=channel_key, source_timeout=0.01)
    unsubscribe()

    source.put({"type": "aprs", "callsign": "N0CALL"})
    time.sleep(0.05)

    assert source.qsize() == 0


def test_fanout_does_not_replay_stale_message_after_re_subscribe() -> None:
    """A message queued while disconnected should not be replayed on reconnect."""
    source = queue.Queue()
    channel_key = _channel_key("sse-resub")

    _, unsubscribe = subscribe_fanout_queue(source, channel_key=channel_key, source_timeout=0.01)
    unsubscribe()

    source.put({"type": "aprs", "callsign": "K1ABC"})

    subscriber, unsubscribe2 = subscribe_fanout_queue(
        source,
        channel_key=channel_key,
        source_timeout=0.01,
    )
    try:
        with pytest.raises(queue.Empty):
            subscriber.get(timeout=0.1)
        live = {"type": "aprs", "callsign": "LIVE01"}
        source.put(live)
        got = subscriber.get(timeout=0.25)
    finally:
        unsubscribe2()

    assert got == live
