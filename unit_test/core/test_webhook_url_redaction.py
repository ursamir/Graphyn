"""SEC-P0: webhook URL must never be returned raw via API / audit."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.trust.audit import list_audit, record_audit
from app.core.trust.egress import redact_webhook_url_for_api
from app.core.notify.webhook import WebhookService


SECRET_URL = "https://hooks.example.com/hooks/very-secret-token-xyz?sig=abc"


def test_redact_webhook_url_for_api_strips_query_and_userinfo() -> None:
    assert redact_webhook_url_for_api("") == ""
    assert (
        redact_webhook_url_for_api("https://user:pass@hooks.example.com/h?token=1#x")
        == "https://hooks.example.com/***"
    )
    assert redact_webhook_url_for_api("https://hooks.example.com/") == "https://hooks.example.com"
    assert redact_webhook_url_for_api("not-a-url") == "***"


def test_public_config_redacts_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    svc = WebhookService()
    with patch("app.core.notify.webhook.validate_webhook_target_url"):
        svc.save(SECRET_URL, ["run_done"])
    # Disk still has the real URL for delivery
    raw = json.loads(svc.CONFIG_PATH.read_text())
    assert raw["url"] == SECRET_URL
    pub = svc.public_config()
    assert SECRET_URL not in json.dumps(pub)
    assert "very-secret-token-xyz" not in json.dumps(pub)
    assert pub["url_configured"] is True
    assert pub["url"] == "https://hooks.example.com/***"


def test_rotation_clears_old_secret_from_public_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    svc = WebhookService()
    new_url = "https://hooks.example.com/hooks/rotated-other"
    with patch("app.core.notify.webhook.validate_webhook_target_url"):
        svc.save(SECRET_URL, ["run_done"])
        svc.save(new_url, ["run_done"])
    pub = svc.public_config()
    assert "very-secret-token-xyz" not in json.dumps(pub)
    assert "rotated-other" not in json.dumps(pub)
    assert pub["url"] == "https://hooks.example.com/***"
    # Raw load has only the new URL
    assert svc.load()["url"] == new_url


def test_url_for_save_keeps_secret_instead_of_redacted_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    svc = WebhookService()
    with patch("app.core.notify.webhook.validate_webhook_target_url"):
        svc.save(SECRET_URL, ["pipeline_complete"])
    preview = svc.public_config()["url"]
    assert svc.url_for_save(preview, keep_url=False) == SECRET_URL
    assert svc.url_for_save("", keep_url=True) == SECRET_URL
    with pytest.raises(ValueError, match="redacted preview"):
        svc.url_for_save("https://other.example/***", keep_url=False)


def test_audit_list_redacts_historical_webhook_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    # Simulate a legacy audit row that stored the raw secret as resource_id
    record_audit(
        actor="tester",
        action="webhook.set",
        resource_type="webhook",
        resource_id=SECRET_URL,
        meta={},
        base_dir=tmp_path,
    )
    events = list_audit(limit=10, base_dir=tmp_path)
    assert events
    blob = json.dumps(events)
    assert "very-secret-token-xyz" not in blob
    assert "sig=abc" not in blob
    assert events[0]["resource_id"] == "https://hooks.example.com/***"
