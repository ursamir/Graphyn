# unit_test/api/test_public_system_paths.py
"""Public honesty endpoints must not require Bearer when a token is configured."""
from __future__ import annotations


def test_auth_status_public_without_bearer(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "production")
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "public-path-token")
    resp = api_client.get("/api/v1/system/auth-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_required"] is True
    assert body["token_configured"] is True
    assert body["ok"] is True


def test_readiness_public_without_bearer(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "public-path-token")
    resp = api_client.get("/api/v1/system/readiness")
    assert resp.status_code == 200
    assert "backend_mode" in resp.json()


def test_nodes_still_require_bearer(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "public-path-token")
    resp = api_client.get("/api/v1/nodes")
    assert resp.status_code == 401
