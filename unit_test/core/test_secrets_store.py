"""Unit tests for the local named secret store (no network)."""
from __future__ import annotations

import os
import stat

import pytest

from app.core.secrets import (
    SecretError,
    delete_secret,
    get_secret,
    list_secret_names,
    resolve_secret,
    set_secret,
    file_mode,
)


@pytest.fixture
def secret_home(tmp_path, monkeypatch):
    home = tmp_path / "ghome"
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    return home


def test_set_list_get_names_only(secret_home):
    set_secret("OPENAI_API_KEY", "sk-test-value")
    names = list_secret_names()
    assert names == ["OPENAI_API_KEY"]
    assert "sk-test-value" not in str(names)
    assert get_secret("OPENAI_API_KEY") == "sk-test-value"


def test_mode_0600(secret_home):
    set_secret("DEEPGRAM_API_KEY", "dg-secret")
    mode = file_mode("DEEPGRAM_API_KEY")
    assert mode == 0o600
    path = secret_home / "secrets" / "DEEPGRAM_API_KEY"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_name_rejected(secret_home):
    with pytest.raises(SecretError):
        set_secret("../etc/passwd", "x")
    with pytest.raises(SecretError):
        set_secret("has space", "x")


def test_resolve_store_then_env(secret_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert resolve_secret("OPENAI_API_KEY") == "from-env"
    set_secret("OPENAI_API_KEY", "from-store")
    assert resolve_secret("OPENAI_API_KEY") == "from-store"


def test_delete(secret_home):
    set_secret("ASSEMBLYAI_API_KEY", "aa")
    assert delete_secret("ASSEMBLYAI_API_KEY") is True
    assert list_secret_names() == []
    assert delete_secret("ASSEMBLYAI_API_KEY") is False
