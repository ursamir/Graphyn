"""MCP secrets tools — list names only, set does not echo values."""
from __future__ import annotations

from app.mcp.handlers.secrets import secrets_list_handler, secrets_set_handler


def test_secrets_set_and_list_no_value(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    listed = secrets_list_handler({})
    assert listed == {"names": []}
    result = secrets_set_handler({"name": "DEEPGRAM_API_KEY", "value": "dg-secret"})
    assert result["ok"] is True
    assert result["name"] == "DEEPGRAM_API_KEY"
    assert "dg-secret" not in str(result)
    listed = secrets_list_handler({})
    assert listed["names"] == ["DEEPGRAM_API_KEY"]
    assert "dg-secret" not in str(listed)
