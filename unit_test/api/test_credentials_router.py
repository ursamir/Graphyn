"""REST /api/v1/credentials — redaction + auth."""
from __future__ import annotations


def test_credentials_roundtrip_redacted(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)

    kinds = api_client.get("/api/v1/credentials/kinds")
    assert kinds.status_code == 200
    assert any(k["id"] == "smtp" for k in kinds.json()["kinds"])

    secret = "sk-must-never-appear"
    created = api_client.post(
        "/api/v1/credentials",
        json={
            "name": "openai-1",
            "kind": "openai_compat",
            "payload": {"api_key": secret, "base_url": "https://api.openai.com/v1"},
            "is_default": True,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["ok"] is True
    assert body["fields"]["api_key"] == "***"
    assert secret not in created.text
    cid = body["id"]

    listed = api_client.get("/api/v1/credentials")
    assert listed.status_code == 200
    assert secret not in listed.text
    assert listed.json()["total"] == 1

    got = api_client.get(f"/api/v1/credentials/{cid}")
    assert got.status_code == 200
    assert secret not in got.text
    assert got.json()["fields"]["api_key"] == "***"

    rotated = api_client.patch(
        f"/api/v1/credentials/{cid}",
        json={"payload": {"api_key": "sk-rotated-value"}, "rotate": False},
    )
    assert rotated.status_code == 200
    assert "sk-rotated-value" not in rotated.text

    deleted = api_client.delete(f"/api/v1/credentials/{cid}?delete=true")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_credentials_auth_gate(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "cred-token")
    assert api_client.get("/api/v1/credentials").status_code == 401
    headers = {"Authorization": "Bearer cred-token"}
    assert api_client.get("/api/v1/credentials", headers=headers).status_code == 200
