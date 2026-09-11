# unit_test/core/test_run_notify.py
"""Tests for terminal run webhook notify mapping."""
from __future__ import annotations

from app.core.run_notify import notify_run_terminal


def test_notify_maps_completed(monkeypatch):
    calls = []

    class Fake:
        def notify(self, event, payload):
            calls.append((event, payload))

    monkeypatch.setattr("app.core.webhook.WebhookService", Fake)
    notify_run_terminal("completed", "r1", graph_name="g", project="p")
    assert calls == [("pipeline_complete", {"run_id": "r1", "status": "completed", "graph_name": "g", "project": "p"})]


def test_notify_maps_failed(monkeypatch):
    calls = []

    class Fake:
        def notify(self, event, payload):
            calls.append((event, payload))

    monkeypatch.setattr("app.core.webhook.WebhookService", Fake)
    notify_run_terminal("failed", "r2", error="boom")
    assert calls[0][0] == "pipeline_failed"
    assert calls[0][1]["error"] == "boom"


def test_notify_ignores_running(monkeypatch):
    calls = []

    class Fake:
        def notify(self, event, payload):
            calls.append((event, payload))

    monkeypatch.setattr("app.core.webhook.WebhookService", Fake)
    notify_run_terminal("running", "r3")
    assert calls == []
