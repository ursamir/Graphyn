"""Legacy REST /api/v1/secrets removed — Credentials is the product secret system."""
from __future__ import annotations


def test_legacy_secrets_routes_gone(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)

    assert api_client.get("/api/v1/secrets").status_code == 404
    assert api_client.post(
        "/api/v1/secrets", json={"name": "OPENAI_API_KEY", "value": "x"}
    ).status_code == 404
    assert api_client.put(
        "/api/v1/secrets/OPENAI_API_KEY", json={"value": "x"}
    ).status_code == 404
    assert api_client.delete("/api/v1/secrets/OPENAI_API_KEY").status_code == 404
