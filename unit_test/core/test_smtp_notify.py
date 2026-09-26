"""Tests for smtp_notify + run_notify email sink."""
from __future__ import annotations

from app.core.smtp_notify import send_email
from app.core.run_notify import notify_run_terminal


def test_send_email_dry_run(monkeypatch):
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    receipt = send_email(to="a@b.com", subject="s", body="b")
    assert receipt["ok"] is True
    assert receipt["dry_run"] is True


def test_send_email_needs_host(monkeypatch):
    monkeypatch.delenv("GRAPHYN_SMTP_DRY_RUN", raising=False)
    monkeypatch.delenv("GRAPHYN_SMTP_HOST", raising=False)
    try:
        send_email(to="a@b.com", subject="s", body="b", dry_run=False)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "needs-credentials" in str(exc)


def test_run_notify_email_sink(monkeypatch):
    calls = []

    class FakeWH:
        def notify(self, event, payload):
            calls.append(("wh", event, payload))

    def fake_send_email(**kwargs):
        calls.append(("email", kwargs))
        return {"ok": True, "dry_run": True}

    monkeypatch.setattr("app.core.webhook.WebhookService", FakeWH)
    monkeypatch.setattr("app.core.smtp_notify.send_email", fake_send_email)
    monkeypatch.setenv("GRAPHYN_NOTIFY_EMAIL_TO", "ops@example.com")
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    notify_run_terminal("completed", "r9", graph_name="g")
    assert any(c[0] == "wh" and c[1] == "pipeline_complete" for c in calls)
    assert any(c[0] == "email" and c[1]["to"] == "ops@example.com" for c in calls)


def test_run_notify_skips_email_without_to(monkeypatch):
    calls = []

    class FakeWH:
        def notify(self, event, payload):
            calls.append(event)

    def boom(**kwargs):
        raise AssertionError("send_email should not be called")

    monkeypatch.setattr("app.core.webhook.WebhookService", FakeWH)
    monkeypatch.setattr("app.core.smtp_notify.send_email", boom)
    monkeypatch.delenv("GRAPHYN_NOTIFY_EMAIL_TO", raising=False)
    notify_run_terminal("failed", "r10", error="x")
    assert calls == ["pipeline_failed"]
