# unit_test/mcp/test_mcp_auth_integration.py
"""Integration test: MCP handler with wrong token returns unauthorized — Req 12."""
from __future__ import annotations

import importlib


def _reload_auth(monkeypatch, token):
    """Reload auth module with a specific token env var."""
    if token is None:
        monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
        monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GRAPHYN_API_TOKEN", token)
    import app.mcp.auth as auth_mod
    importlib.reload(auth_mod)
    return auth_mod


class TestMCPAuthIntegration:
    def test_wrong_token_returns_unauthorized(self, monkeypatch):
        """Handler called with wrong token returns unauthorized dict."""
        auth_mod = _reload_auth(monkeypatch, "correct-token")
        result = auth_mod.check_auth({"_meta": {"auth_token": "wrong-token"}})
        assert result is not None
        assert result.get("error_type") == "unauthorized"
        assert result.get("error") is True

    def test_correct_token_allows_through(self, monkeypatch):
        """Handler called with correct token returns None (allowed)."""
        auth_mod = _reload_auth(monkeypatch, "correct-token")
        result = auth_mod.check_auth({"_meta": {"auth_token": "correct-token"}})
        assert result is None

    def test_no_token_env_allows_all(self, monkeypatch):
        """No token configured — all requests allowed (returns None)."""
        auth_mod = _reload_auth(monkeypatch, None)
        result = auth_mod.check_auth({"_meta": {"auth_token": "anything"}})
        assert result is None

    def test_discovery_handler_with_wrong_token_still_works(self, monkeypatch):
        """Discovery handler itself doesn't check auth — auth is checked by server.

        The handler returns nodes regardless; auth enforcement is in server.py.
        This test verifies the handler works independently of auth.
        """
        from app.mcp.handlers.discovery import list_nodes_handler
        result = list_nodes_handler({})
        assert "nodes" in result

    def test_unauthorized_dict_structure(self, monkeypatch):
        """Unauthorized dict has all required keys: error, error_type, message."""
        auth_mod = _reload_auth(monkeypatch, "secret")
        result = auth_mod.check_auth({})
        assert result["error"] is True
        assert result["error_type"] == "unauthorized"
        assert isinstance(result["message"], str)
        assert result["message"]
