"""REST /api/v1/secrets — names only, values never listed."""
from __future__ import annotations


def test_secrets_roundtrip_names_only(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    listed = api_client.get("/api/v1/secrets")
    assert listed.status_code == 200
    assert listed.json()["names"] == []
    created = api_client.post("/api/v1/secrets", json={"name": "OPENAI_API_KEY", "value": "sk-never-list"})
    assert created.status_code == 200
    body = created.json()
    assert body["ok"] is True
    assert body["name"] == "OPENAI_API_KEY"
    assert "sk-never-list" not in str(body)
    listed = api_client.get("/api/v1/secrets")
    assert listed.json()["names"] == ["OPENAI_API_KEY"]
    assert "sk-never-list" not in listed.text


def test_auth_required_rejects_without_token(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    resp = api_client.get("/api/v1/secrets")
    assert resp.status_code == 401
    assert "GRAPHYN_API_TOKEN" in resp.json()["detail"]
