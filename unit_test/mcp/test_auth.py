# unit_test/mcp/test_auth.py
"""Tests for app/mcp/auth.py — Req 25 criteria 1–5."""
from __future__ import annotations

import pytest


def _check_auth(arguments, token=None, monkeypatch=None):
    """Call check_auth with a fresh module import so _TOKEN is re-evaluated."""
    import importlib
    import app.mcp.auth as auth_mod
    if monkeypatch is not None:
        if token is None:
            monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
            monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
        else:
            monkeypatch.setenv("GRAPHYN_API_TOKEN", token)
    # Reload so _TOKEN picks up the env change
    importlib.reload(auth_mod)
    return auth_mod.check_auth(arguments)


class TestCheckAuthNoToken:
    def test_no_env_token_returns_none(self, monkeypatch):
        """Req 25.1 — check_auth({}) returns None when GRAPHYN_API_TOKEN is unset."""
        result = _check_auth({}, token=None, monkeypatch=monkeypatch)
        assert result is None

    def test_no_env_token_with_meta_returns_none(self, monkeypatch):
        """No auth configured — any token in _meta is ignored."""
        result = _check_auth(
            {"_meta": {"auth_token": "anything"}},
            token=None,
            monkeypatch=monkeypatch,
        )
        assert result is None


class TestCheckAuthWithToken:
    def test_correct_token_returns_none(self, monkeypatch):
        """Req 25.2 — correct token in _meta returns None."""
        result = _check_auth(
            {"_meta": {"auth_token": "secret123"}},
            token="secret123",
            monkeypatch=monkeypatch,
        )
        assert result is None

    def test_wrong_token_returns_unauthorized(self, monkeypatch):
        """Req 25.3 — wrong token returns unauthorized dict."""
        result = _check_auth(
            {"_meta": {"auth_token": "wrong"}},
            token="secret123",
            monkeypatch=monkeypatch,
        )
        assert result is not None
        assert result.get("error_type") == "unauthorized"

    def test_missing_token_with_env_set_returns_unauthorized(self, monkeypatch):
        """Req 25.4 — no token provided when env is set returns unauthorized."""
        result = _check_auth({}, token="secret123", monkeypatch=monkeypatch)
        assert result is not None
        assert result.get("error_type") == "unauthorized"

    def test_error_dict_has_required_keys(self, monkeypatch):
        """Req 25.5 — error dict contains error, error_type, and message keys."""
        result = _check_auth(
            {"_meta": {"auth_token": "bad"}},
            token="secret123",
            monkeypatch=monkeypatch,
        )
        assert result["error"] is True
        assert result["error_type"] == "unauthorized"
        assert "message" in result
        assert result["message"]
