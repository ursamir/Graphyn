"""Unit tests for app/core/logger.py — Req 5 criteria 6–7."""
from __future__ import annotations

import pytest

from app.core.logger import PipelineLogger


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def logger() -> PipelineLogger:
    """Return a fresh PipelineLogger with no queue."""
    return PipelineLogger()


# ── pipeline_start ────────────────────────────────────────────────────────────

def test_pipeline_start_appends_entry_with_correct_type(logger: PipelineLogger):
    """Req 5.6 — pipeline_start(N) appends entry with type='pipeline_start'."""
    logger.pipeline_start(5)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "pipeline_start"]
    assert len(structured) >= 1


def test_pipeline_start_records_total_nodes(logger: PipelineLogger):
    """Req 5.6 — pipeline_start(N) appends entry with total_nodes=N."""
    logger.pipeline_start(7)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "pipeline_start"]
    assert structured[-1]["total_nodes"] == 7


def test_pipeline_start_zero_nodes(logger: PipelineLogger):
    """pipeline_start(0) records total_nodes=0."""
    logger.pipeline_start(0)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "pipeline_start"]
    assert structured[-1]["total_nodes"] == 0


def test_pipeline_start_timestamp_is_utc(logger: PipelineLogger):
    """Req 5.6 — timestamp in pipeline_start entry is UTC ISO 8601."""
    logger.pipeline_start(3)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "pipeline_start"]
    ts = structured[-1]["timestamp"]
    # UTC ISO 8601 timestamps end with +00:00 or Z
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"Timestamp not UTC: {ts!r}"


# ── node_end ──────────────────────────────────────────────────────────────────

def test_node_end_appends_entry_with_correct_type(logger: PipelineLogger):
    """Req 5.7 — node_end() appends entry with type='node_end'."""
    logger.node_end("audio_conditioner", 0, 0.5)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "node_end"]
    assert len(structured) >= 1


def test_node_end_records_node_type(logger: PipelineLogger):
    """node_end() records the correct node_type."""
    logger.node_end("segmenter", 1, 1.2)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "node_end"]
    assert structured[-1]["node_type"] == "segmenter"


def test_node_end_output_count_passthrough(logger: PipelineLogger):
    """node_end() records output_count correctly."""
    logger.node_end("audio_conditioner", 0, 0.3, output_count=42)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "node_end"]
    assert structured[-1]["output_count"] == 42


def test_node_end_output_count_defaults_to_zero(logger: PipelineLogger):
    """node_end() defaults output_count to 0 when not provided."""
    logger.node_end("audio_conditioner", 0, 0.1)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "node_end"]
    assert structured[-1]["output_count"] == 0


def test_node_end_timestamp_is_utc(logger: PipelineLogger):
    """Timestamps in node_end entries are UTC ISO 8601."""
    logger.node_end("audio_conditioner", 0, 0.5)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "node_end"]
    ts = structured[-1]["timestamp"]
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"Timestamp not UTC: {ts!r}"


def test_node_end_records_duration(logger: PipelineLogger):
    """node_end() records the duration value as 'duration_s'."""
    logger.node_end("audio_conditioner", 0, 2.5)
    structured = [e for e in logger.logs if isinstance(e, dict) and e.get("type") == "node_end"]
    assert structured[-1]["duration_s"] == pytest.approx(2.5)


# ── Multiple events accumulate ────────────────────────────────────────────────

def test_multiple_events_accumulate_in_logs(logger: PipelineLogger):
    """Multiple calls accumulate entries in logger.logs."""
    logger.pipeline_start(2)
    logger.node_end("audio_conditioner", 0, 0.1)
    logger.node_end("segmenter", 1, 0.2)
    types = [e.get("type") for e in logger.logs if isinstance(e, dict)]
    assert "pipeline_start" in types
    assert types.count("node_end") == 2


# ── Queue forwarding ──────────────────────────────────────────────────────────

def test_events_forwarded_to_queue_when_provided():
    """Events are put onto the queue when one is provided."""
    from queue import Queue
    q: Queue = Queue()
    log = PipelineLogger(queue=q)
    log.pipeline_start(1)
    assert not q.empty()
    # pipeline_start calls _emit (plain log) then _emit_structured (typed event)
    # Drain the queue and look for the structured event
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    typed = [e for e in events if isinstance(e, dict) and e.get("type") == "pipeline_start"]
    assert typed, f"No pipeline_start event found in queue. Got: {events}"
