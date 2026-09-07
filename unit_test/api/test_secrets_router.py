"""REST /api/v1/secrets — names only, values never listed; auth + 422 redaction."""
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
    replaced = api_client.put(
        "/api/v1/secrets/OPENAI_API_KEY",
        json={"value": "sk-replaced-value"},
    )
    assert replaced.status_code == 200
    assert "sk-replaced-value" not in replaced.text
    assert replaced.json()["name"] == "OPENAI_API_KEY"


def test_auth_required_rejects_without_token(api_client, monkeypatch):
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    resp = api_client.get("/api/v1/secrets")
    assert resp.status_code == 401
    assert "GRAPHYN_API_TOKEN" in resp.json()["detail"]


def test_secrets_unauthenticated_rejected_when_token_configured(api_client, tmp_path, monkeypatch):
    """When GRAPHYN_API_TOKEN is set, secrets routes require Bearer."""
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "op-token-secrets")
    headers = {"Authorization": "Bearer op-token-secrets"}

    assert api_client.get("/api/v1/secrets").status_code == 401
    assert api_client.post(
        "/api/v1/secrets",
        json={"name": "OPENAI_API_KEY", "value": "sk-nope"},
    ).status_code == 401
    assert api_client.put(
        "/api/v1/secrets/OPENAI_API_KEY",
        json={"value": "sk-nope"},
    ).status_code == 401
    assert api_client.delete("/api/v1/secrets/OPENAI_API_KEY").status_code == 401

    created = api_client.post(
        "/api/v1/secrets",
        json={"name": "OPENAI_API_KEY", "value": "sk-ok"},
        headers=headers,
    )
    assert created.status_code == 200
    assert "sk-ok" not in created.text
    listed = api_client.get("/api/v1/secrets", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["names"] == ["OPENAI_API_KEY"]
    assert "sk-ok" not in listed.text


def test_secrets_validation_error_redacts_value_input(api_client, monkeypatch):
    """422 on /secrets must not echo the submitted secret value."""
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    leaked = "sk-must-not-appear-in-422"
    resp = api_client.post(
        "/api/v1/secrets",
        json={"name": "OPENAI_API_KEY", "value": {"nested": leaked}},
    )
    assert resp.status_code == 422
    assert leaked not in resp.text
    detail = resp.json()["detail"]
    assert any(
        err.get("input") == "[redacted]"
        for err in detail
        if "value" in (err.get("loc") or [])
    )

    put = api_client.put(
        "/api/v1/secrets/OPENAI_API_KEY",
        json={"value": [leaked]},
    )
    assert put.status_code == 422
    assert leaked not in put.text
