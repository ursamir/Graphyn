"""Tests for in-app notification store + run_notify sink."""
from __future__ import annotations

from app.core.in_app_notify import append_notification, list_notifications, mark_read
from app.core.run_notify import notify_run_terminal


def test_append_list_mark(tmp_path, monkeypatch):
    path = tmp_path / "notifications.jsonl"
    monkeypatch.setenv("GRAPHYN_NOTIFICATIONS_PATH", str(path))
    a = append_notification(title="t1", body="b1", level="info")
    b = append_notification(title="t2", body="b2", level="error", run_id="r1")
    listed = list_notifications(limit=10)
    assert listed["total"] == 2
    assert listed["unread_count"] == 2
    assert listed["notifications"][0]["id"] == b["id"]  # newest first
    mark_read([a["id"]])
    listed2 = list_notifications(unread_only=True)
    assert listed2["total"] == 1
    assert listed2["notifications"][0]["id"] == b["id"]
    mark_read(all_read=True)
    listed3 = list_notifications(unread_only=True)
    assert listed3["total"] == 0
    assert list_notifications()["unread_count"] == 0


def test_run_notify_writes_in_app(tmp_path, monkeypatch):
    path = tmp_path / "notifications.jsonl"
    monkeypatch.setenv("GRAPHYN_NOTIFICATIONS_PATH", str(path))
    monkeypatch.delenv("GRAPHYN_NOTIFY_EMAIL_TO", raising=False)

    class FakeWH:
        def notify(self, event, payload):
            pass

    monkeypatch.setattr("app.core.webhook.WebhookService", FakeWH)
    notify_run_terminal("completed", "run-xyz", graph_name="g", project="p")
    listed = list_notifications()
    assert listed["total"] == 1
    ev = listed["notifications"][0]
    assert ev["run_id"] == "run-xyz"
    assert ev["event"] == "pipeline_complete"
    assert "g" in ev["body"]
