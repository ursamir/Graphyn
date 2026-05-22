# unit_test/core/nodes/test_observers.py
"""Tests for app/core/nodes/observers.py — Req 18 criteria 4–8."""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

from app.core.nodes.observers import CompositeObserver, LoggingObserver


class TestLoggingObserverOnNodeStart:
    """Req 18.4 — on_node_start emits JSON with 'event': 'node_start' at INFO."""

    def test_emits_json_with_event_node_start(self, caplog):
        obs = LoggingObserver()
        with caplog.at_level(logging.INFO, logger="node_observer"):
            obs.on_node_start("audio_conditioner", "run-001")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.INFO
        payload = json.loads(record.getMessage())
        assert payload["event"] == "node_start"
        assert payload["node_type"] == "audio_conditioner"
        assert payload["run_id"] == "run-001"


class TestLoggingObserverOnNodeEnd:
    """Req 18.5 — on_node_end emits JSON with 'event': 'node_end' and 'duration_s' at INFO."""

    def test_emits_json_with_event_node_end_and_duration(self, caplog):
        obs = LoggingObserver()
        with caplog.at_level(logging.INFO, logger="node_observer"):
            obs.on_node_end(
                "audio_conditioner",
                "run-001",
                duration_s=1.23,
                input_counts={"input": 5},
                output_counts={"output": 5},
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.INFO
        payload = json.loads(record.getMessage())
        assert payload["event"] == "node_end"
        assert "duration_s" in payload
        assert payload["duration_s"] == pytest.approx(1.23)

    def test_emits_at_info_level(self, caplog):
        obs = LoggingObserver()
        with caplog.at_level(logging.DEBUG, logger="node_observer"):
            obs.on_node_end("n", "r", 0.5, {}, {})
        assert caplog.records[0].levelno == logging.INFO


class TestLoggingObserverOnNodeError:
    """Req 18.6 — on_node_error emits JSON with 'event': 'node_error' at ERROR."""

    def test_emits_json_with_event_node_error(self, caplog):
        obs = LoggingObserver()
        exc = ValueError("something went wrong")
        with caplog.at_level(logging.ERROR, logger="node_observer"):
            obs.on_node_error("audio_conditioner", "run-001", exc)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.ERROR
        payload = json.loads(record.getMessage())
        assert payload["event"] == "node_error"
        assert payload["node_type"] == "audio_conditioner"
        assert payload["run_id"] == "run-001"

    def test_error_message_included(self, caplog):
        obs = LoggingObserver()
        exc = RuntimeError("boom")
        with caplog.at_level(logging.ERROR, logger="node_observer"):
            obs.on_node_error("n", "r", exc)
        payload = json.loads(caplog.records[0].getMessage())
        assert "error" in payload
        assert "boom" in payload["error"]


class TestCompositeObserver:
    """Req 18.7–8 — CompositeObserver fans out to children."""

    def test_on_node_start_calls_both_children(self):
        """Req 18.7: on_node_start calls on_node_start on both child observers."""
        obs1 = MagicMock()
        obs2 = MagicMock()
        composite = CompositeObserver([obs1, obs2])
        composite.on_node_start("audio_conditioner", "run-001")
        obs1.on_node_start.assert_called_once_with("audio_conditioner", "run-001")
        obs2.on_node_start.assert_called_once_with("audio_conditioner", "run-001")

    def test_on_node_end_calls_both_children(self):
        obs1 = MagicMock()
        obs2 = MagicMock()
        composite = CompositeObserver([obs1, obs2])
        composite.on_node_end("n", "r", 1.0, {}, {})
        obs1.on_node_end.assert_called_once()
        obs2.on_node_end.assert_called_once()

    def test_on_node_error_calls_both_children(self):
        obs1 = MagicMock()
        obs2 = MagicMock()
        composite = CompositeObserver([obs1, obs2])
        exc = ValueError("err")
        composite.on_node_error("n", "r", exc)
        obs1.on_node_error.assert_called_once_with("n", "r", exc)
        obs2.on_node_error.assert_called_once_with("n", "r", exc)

    def test_empty_composite_does_not_raise_on_start(self):
        """Req 18.8: CompositeObserver with empty list does not raise."""
        composite = CompositeObserver([])
        composite.on_node_start("n", "r")  # must not raise

    def test_empty_composite_does_not_raise_on_end(self):
        composite = CompositeObserver([])
        composite.on_node_end("n", "r", 0.0, {}, {})  # must not raise

    def test_empty_composite_does_not_raise_on_error(self):
        composite = CompositeObserver([])
        composite.on_node_error("n", "r", ValueError("x"))  # must not raise
