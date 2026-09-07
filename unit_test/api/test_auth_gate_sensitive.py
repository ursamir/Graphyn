"""Sensitive /api/v1 routes share the same bearer gate when a token is configured."""
from __future__ import annotations

import pytest


SENSITIVE_GETS = (
    "/api/v1/secrets",
    "/api/v1/workers",
    "/api/v1/plugins",
)

SENSITIVE_POSTS = (
    ("/api/v1/plugins/install", {"source": "file:///tmp/not-a-real-plugin"}),
    ("/api/v1/workers/register", {"worker_id": "w1", "labels": {}}),
)


@pytest.fixture
def token_env(monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "gate-token-phase2")
    return "gate-token-phase2"


def test_unauthenticated_sensitive_gets_rejected(api_client, token_env):
    for path in SENSITIVE_GETS:
        resp = api_client.get(path)
        assert resp.status_code == 401, path
        assert resp.json()["detail"] == "Missing Bearer token"


def test_wrong_token_sensitive_gets_rejected(api_client, token_env):
    headers = {"Authorization": "Bearer wrong-token"}
    for path in SENSITIVE_GETS:
        resp = api_client.get(path, headers=headers)
        assert resp.status_code == 401, path
        assert resp.json()["detail"] == "Invalid Bearer token"


def test_unauthenticated_sensitive_posts_rejected(api_client, token_env):
    for path, body in SENSITIVE_POSTS:
        resp = api_client.post(path, json=body)
        assert resp.status_code == 401, path


def test_valid_bearer_allows_sensitive_get(api_client, token_env):
    headers = {"Authorization": f"Bearer {token_env}"}
    for path in SENSITIVE_GETS:
        resp = api_client.get(path, headers=headers)
        # Auth passed; business 2xx/4xx (e.g. empty list) is fine — not 401.
        assert resp.status_code != 401, path
