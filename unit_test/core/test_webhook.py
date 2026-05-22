"""Unit tests for app/core/webhook.py — Req 19 criteria 18–22."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.webhook import WebhookService


@pytest.fixture
def webhook_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebhookService:
    """Return a WebhookService whose CONFIG_PATH points to a tmp directory.

    Uses monkeypatch to override the webhooks_path config function so that
    WebhookService.CONFIG_PATH (a property) resolves to tmp_path/webhooks.json.
    """
    webhooks_file = tmp_path / "webhooks.json"
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    return WebhookService()


# ── save / load ───────────────────────────────────────────────────────────────

def test_save_writes_webhooks_json(webhook_service: WebhookService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Req 19.18 — save(url, events) writes webhooks.json with correct content."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    url = "https://example.com/hook"
    events = ["run_done", "run_failed"]

    webhook_service.save(url, events)

    config_path = webhook_service.CONFIG_PATH
    assert config_path.exists()
    data = json.loads(config_path.read_text())
    assert data == {"url": url, "events": events}


def test_load_returns_empty_dict_when_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Req 19.19 — load() returns {} when webhooks.json does not exist."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    svc = WebhookService()

    result = svc.load()

    assert result == {}


# ── notify — no URL configured ────────────────────────────────────────────────

def test_notify_does_not_raise_when_no_url_configured(webhook_service: WebhookService):
    """Req 19.20 — notify(event, payload) does not raise when no URL is configured."""
    # CONFIG_PATH does not exist → load() returns {} → no URL
    webhook_service.notify("run_done", {"status": "ok"})  # must not raise


# ── notify — httpx raises ─────────────────────────────────────────────────────

def test_notify_does_not_raise_when_httpx_post_raises(webhook_service: WebhookService):
    """Req 19.21 — notify does not raise when httpx.post raises (fire-and-forget)."""
    webhook_service.save("https://example.com/hook", ["run_done"])

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("connection refused")

        # _send must not raise
        webhook_service._send("https://example.com/hook", "run_done", {})


# ── notify — event not subscribed ────────────────────────────────────────────

def test_notify_does_not_call_httpx_when_event_not_subscribed(
    webhook_service: WebhookService,
):
    """Req 19.22 — notify('run_done', {}) does not call httpx.post when event not subscribed."""
    webhook_service.save("https://example.com/hook", ["run_failed"])

    with patch("app.core.webhook.threading.Thread") as mock_thread_cls:
        webhook_service.notify("run_done", {})
        mock_thread_cls.assert_not_called()
