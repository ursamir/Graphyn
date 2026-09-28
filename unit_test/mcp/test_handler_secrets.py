"""Legacy MCP secrets_list/secrets_set removed — use credential tools."""
from __future__ import annotations

import importlib
import pytest

from app.mcp.tool_registry import register_all_tools


def test_secrets_handlers_module_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.mcp.handlers.secrets")


def test_secrets_tools_not_registered():
    names = []
    register_all_tools(lambda name, desc, schema, handler: names.append(name))
    assert "secrets_list" not in names
    assert "secrets_set" not in names
    assert "list_credentials" in names
    assert "create_credential" in names
