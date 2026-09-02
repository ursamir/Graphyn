"""Unauthenticated GET / and GET /health on the FastAPI app."""
from __future__ import annotations


def test_root_landing_json(api_client):
    resp = api_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "graphyn-api"
    assert body["api"] == "/api/v1/"
    assert "5173" in body["ui"]
    assert body["health"] == "/health"


def test_root_health_ok(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_public_routes_without_token_when_auth_required(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "secret-token")
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/").status_code == 200
    protected = api_client.get("/api/v1/nodes")
    assert protected.status_code == 401
