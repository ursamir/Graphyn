"""Integration: add credential then resolve / llm_chat without restart."""
from __future__ import annotations

import pytest

from app.core.credentials import create_connection, resolve_connection
from app.core.llm_client import NeedsCredentialsError, chat_completion
from app.core.smtp_notify import send_email


@pytest.fixture
def cred_home(tmp_path, monkeypatch):
    home = tmp_path / "ghome"
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GRAPHYN_SMTP_HOST", raising=False)
    monkeypatch.delenv("GRAPHYN_SMTP_DRY_RUN", raising=False)
    return home


def test_add_then_resolve_without_restart(cred_home):
    # Before: fail closed
    with pytest.raises(NeedsCredentialsError):
        resolve_connection(kind="openai_compat")
    # Hot create
    meta = create_connection(
        name="hot-openai",
        kind="openai_compat",
        payload={"api_key": "sk-hot"},
        is_default=True,
    )
    # Same process resolves immediately
    r = resolve_connection(kind="openai_compat")
    assert r["source"] == "workspace_default"
    assert r["payload"]["api_key"] == "sk-hot"
    assert r["connection_id"] == meta["id"]


def test_smtp_dry_run_via_connection(cred_home):
    meta = create_connection(
        name="smtp-dry",
        kind="smtp",
        payload={
            "host": "smtp.example.com",
            "from_addr": "ops@example.com",
            "password": "hidden",
            "dry_run": True,
        },
    )
    receipt = send_email(
        to="user@example.com",
        subject="hi",
        body="body",
        connection_id=meta["id"],
    )
    assert receipt["ok"] is True
    assert receipt["dry_run"] is True
    assert "hidden" not in str(receipt)


def test_llm_chat_stub_still_works(cred_home):
    out = chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        provider="stub",
    )
    assert "stub" in out["content"].lower() or out["provider"] == "stub"


def test_llm_needs_credentials_without_connection(cred_home):
    with pytest.raises(NeedsCredentialsError):
        chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            provider="openai_compat",
        )


def test_llm_uses_connection_id_for_ollama_without_key(cred_home, monkeypatch):
    """Ollama connection resolves; chat_completion may still fail on network — we only check resolve path."""
    meta = create_connection(
        name="local-ollama",
        kind="ollama",
        payload={"base_url": "http://127.0.0.1:9/v1", "default_model": "tinyllama"},
    )
    r = resolve_connection(kind="ollama", connection_id=meta["id"])
    assert r["payload"]["base_url"].startswith("http://127.0.0.1:9")
    # Force stub via credentials inline to avoid network in unit test
    out = chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        provider="stub",
        connection_id=meta["id"],
    )
    assert out["provider"] == "stub"
