"""SEC-P0 API-level checks for webhook redaction and project name validation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


SECRET_URL = "https://hooks.example.com/hooks/api-secret-token-999"


class TestWebhookApiRedaction:
    def test_get_put_test_never_echo_raw_url(self, api_client, tmp_workspace: Path):
        from app.core.notify.webhook import WebhookService

        WebhookService._class_config_cache = None
        with patch("app.core.notify.webhook.validate_webhook_target_url"):
            put = api_client.put(
                "/api/v1/system/webhooks",
                json={"url": SECRET_URL, "events": ["run_done"]},
            )
        assert put.status_code == 200, put.text
        put_body = put.json()
        assert SECRET_URL not in put.text
        assert "api-secret-token-999" not in put.text
        assert put_body.get("url_configured") is True
        assert put_body.get("url") == "https://hooks.example.com/***"

        got = api_client.get("/api/v1/system/webhooks")
        assert got.status_code == 200
        assert SECRET_URL not in got.text
        assert "api-secret-token-999" not in got.text
        assert got.json().get("url_configured") is True

        test = api_client.post("/api/v1/system/webhooks/test")
        assert test.status_code == 200
        assert SECRET_URL not in test.text
        assert "api-secret-token-999" not in test.text

        audit = api_client.get("/api/v1/audit")
        if audit.status_code == 200:
            assert "api-secret-token-999" not in audit.text


class TestProjectNameTraversalApi:
    def test_get_project_rejects_traversal(self, api_client, tmp_workspace: Path):
        resp = api_client.get("/api/v1/projects/../etc")
        assert resp.status_code in (422, 404)
        assert resp.status_code != 200
