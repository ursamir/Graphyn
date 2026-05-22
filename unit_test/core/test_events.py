"""Unit tests for app/core/events.py — Req 19 criteria 7–11."""
from __future__ import annotations

import asyncio

import pytest

from app.core.events import (
    EventSource,
    QueueSource,
    TimerSource,
    create_event_source,
)


# ── Factory function ──────────────────────────────────────────────────────────

def test_create_event_source_timer_returns_timer_source():
    """Req 19.7 — create_event_source('timer', ...) returns a TimerSource."""
    source = create_event_source("timer", {"interval_s": 0.1})
    assert isinstance(source, TimerSource)


def test_create_event_source_queue_returns_queue_source():
    """Req 19.8 — create_event_source('queue', ...) returns a QueueSource."""
    q = asyncio.Queue()
    source = create_event_source("queue", {"queue": q})
    assert isinstance(source, QueueSource)


def test_create_event_source_unknown_type_raises_value_error():
    """Req 19.9 — create_event_source('unknown_type', {}) raises ValueError."""
    with pytest.raises(ValueError):
        create_event_source("unknown_type", {})


# ── Inheritance ───────────────────────────────────────────────────────────────

def test_timer_source_is_subclass_of_event_source():
    """Req 19.10 — TimerSource is a subclass of EventSource."""
    assert issubclass(TimerSource, EventSource)


# ── QueueSource.watch() ───────────────────────────────────────────────────────

def test_queue_source_watch_yields_put_item():
    """Req 19.11 — QueueSource.watch() yields the dict put into the queue."""
    async def _run():
        q: asyncio.Queue = asyncio.Queue()
        payload = {"key": "value", "num": 42}
        await q.put(payload)

        source = QueueSource(queue=q)
        gen = source.watch()
        result = await gen.__anext__()
        await gen.aclose()
        return result

    result = asyncio.run(_run())
    assert result == {"key": "value", "num": 42}
