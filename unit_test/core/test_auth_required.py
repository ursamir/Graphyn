"""Fail-closed auth when GRAPHYN_AUTH_REQUIRED=1 or GRAPHYN_ENV=production."""
from __future__ import annotations

import importlib

from app.core.config import auth_required


def test_auth_required_flag(monkeypatch):
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.delenv("GRAPHYN_ENV", raising=False)
    assert auth_required() is True


def test_auth_required_production(monkeypatch):
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("GRAPHYN_ENV", "production")
    assert auth_required() is True


def test_auth_optional_development(monkeypatch):
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    assert auth_required() is False


def test_mcp_fail_closed_empty_token(monkeypatch):
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    import app.mcp.auth as auth_mod
    importlib.reload(auth_mod)
    result = auth_mod.check_auth({})
    assert result is not None
    assert result["error_type"] == "unauthorized"
    assert "GRAPHYN_API_TOKEN" in result["message"]


def test_mcp_dev_empty_token_allows(monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "0")
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    import app.mcp.auth as auth_mod
    importlib.reload(auth_mod)
    assert auth_mod.check_auth({}) is None
