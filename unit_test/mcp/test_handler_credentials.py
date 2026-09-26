"""MCP credential tools — redaction."""
from __future__ import annotations

from app.mcp.handlers.credentials import (
    create_credential_handler,
    get_credential_handler,
    list_credentials_handler,
    revoke_credential_handler,
    update_credential_handler,
)


def test_mcp_credentials_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)
    secret = "smtp-password-secret"
    created = create_credential_handler({
        "name": "smtp-dry",
        "kind": "smtp",
        "payload": {
            "host": "smtp.example.com",
            "password": secret,
            "from_addr": "ops@example.com",
            "dry_run": True,
        },
        "is_default": True,
    })
    assert created.get("ok") is True
    assert secret not in str(created)
    assert created["fields"]["password"] == "***"
    cid = created["id"]
    listed = list_credentials_handler({})
    assert secret not in str(listed)
    got = get_credential_handler({"id": cid})
    assert secret not in str(got)
    updated = update_credential_handler({"id": cid, "payload": {"password": "new-secret"}})
    assert "new-secret" not in str(updated)
    revoked = revoke_credential_handler({"id": cid, "delete": True})
    assert revoked.get("ok") is True
