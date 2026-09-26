"""Unit tests for the live credential store (no network)."""
from __future__ import annotations

import os
import stat

import pytest

from app.core.credentials import (
    CredentialError,
    NeedsCredentialsError,
    create_connection,
    get_connection,
    get_payload,
    list_connections,
    list_kinds,
    resolve_connection,
    revoke_connection,
    set_default,
    update_connection,
)
from app.core.credentials.kinds import redact_payload


@pytest.fixture
def cred_home(tmp_path, monkeypatch):
    home = tmp_path / "ghome"
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GRAPHYN_SMTP_HOST", raising=False)
    return home


def test_kinds_builtin(cred_home):
    ids = {k.id for k in list_kinds()}
    assert {"openai_compat", "anthropic", "gemini", "ollama", "smtp", "webhook"} <= ids


def test_create_list_redacted(cred_home):
    meta = create_connection(
        name="prod-openai",
        kind="openai_compat",
        payload={"api_key": "sk-secret-never-list", "base_url": "https://api.openai.com/v1"},
    )
    assert meta["id"]
    assert meta["fields"]["api_key"] == "***"
    assert meta["fields"]["base_url"] == "https://api.openai.com/v1"
    assert "sk-secret-never-list" not in str(meta)
    listed = list_connections()
    assert len(listed) == 1
    assert "sk-secret-never-list" not in str(listed)
    got = get_connection(meta["id"])
    assert got["fields"]["api_key"] == "***"
    kind, payload = get_payload(meta["id"])
    assert kind == "openai_compat"
    assert payload["api_key"] == "sk-secret-never-list"


def test_key_file_mode(cred_home):
    create_connection(
        name="x",
        kind="ollama",
        payload={"base_url": "http://127.0.0.1:11434/v1"},
    )
    key = cred_home / "credentials" / ".key"
    assert key.is_file()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    db = cred_home / "credentials" / "store.sqlite"
    assert db.is_file()
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_rotate_and_revoke(cred_home):
    meta = create_connection(
        name="smtp1",
        kind="smtp",
        payload={"host": "smtp.example.com", "password": "pw1", "from_addr": "a@b.c", "dry_run": True},
    )
    cid = meta["id"]
    updated = update_connection(cid, payload={"password": "pw2"}, rotate=False)
    assert updated["fields"]["password"] == "***"
    _, payload = get_payload(cid)
    assert payload["password"] == "pw2"
    assert payload["host"] == "smtp.example.com"
    revoke_connection(cid)
    with pytest.raises(NeedsCredentialsError):
        resolve_connection(kind="smtp", connection_id=cid)


def test_resolve_precedence(cred_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    # env only
    r = resolve_connection(kind="openai_compat")
    assert r["source"] == "env"
    assert r["payload"]["api_key"] == "from-env"
    # workspace default beats env
    meta = create_connection(
        name="def",
        kind="openai_compat",
        payload={"api_key": "from-default"},
        is_default=True,
    )
    r2 = resolve_connection(kind="openai_compat")
    assert r2["source"] == "workspace_default"
    assert r2["payload"]["api_key"] == "from-default"
    # explicit id beats default
    other = create_connection(
        name="other",
        kind="openai_compat",
        payload={"api_key": "from-explicit"},
    )
    r3 = resolve_connection(kind="openai_compat", connection_id=other["id"])
    assert r3["source"] == "connection"
    assert r3["payload"]["api_key"] == "from-explicit"
    assert r3["connection_id"] == other["id"]


def test_fail_closed_missing(cred_home, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NeedsCredentialsError):
        resolve_connection(kind="openai_compat")


def test_redact_helper():
    assert redact_payload("openai_compat", {"api_key": "sk", "base_url": "http://x"}) == {
        "api_key": "***",
        "base_url": "http://x",
    }


def test_invalid_kind(cred_home):
    with pytest.raises(CredentialError):
        create_connection(name="x", kind="nope", payload={})


def test_set_default_helper(cred_home):
    a = create_connection(name="a", kind="ollama", payload={"base_url": "http://a"})
    b = create_connection(name="b", kind="ollama", payload={"base_url": "http://b"})
    set_default(b["id"])
    listed = list_connections(kind="ollama")
    defaults = [c for c in listed if c["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == b["id"]
