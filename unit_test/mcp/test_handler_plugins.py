
"""Tests for MCP plugin lifecycle tools (install/list/manage) — local path, no network."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.mcp.handlers.plugins import (
    install_plugin_handler,
    list_plugins_handler,
    manage_plugin_handler,
)
from app.mcp.handlers.discovery import list_nodes_handler


@pytest.fixture
def isolated_plugin_home(tmp_path, monkeypatch):
    home = tmp_path / "graphyn-home"
    home.mkdir()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    monkeypatch.setenv("GRAPHYN_PLUGINS_DIR", str(plugins))
    monkeypatch.delenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", raising=False)
    return plugins


def test_install_plugin_local_set_map(isolated_plugin_home):
    source = str(Path("PluginPackage/Common/set_map").resolve())
    result = install_plugin_handler({"source": source, "upgrade": True})
    assert not result.get("error"), result
    assert result["name"] == "set-map"
    assert "set_map" in result["node_types"]
    listed = list_plugins_handler({})
    names = [p["name"] for p in listed["plugins"]]
    assert "set-map" in names
    nodes = list_nodes_handler({})
    types = [n["node_type"] for n in nodes.get("nodes", [])]
    assert "set_map" in types


def test_install_plugin_missing_source():
    result = install_plugin_handler({})
    assert result.get("error") is True
    assert result.get("error_type") == "missing_argument"


def test_manage_plugin_invalid_action(isolated_plugin_home):
    result = manage_plugin_handler({"action": "explode", "name": "nope"})
    assert result.get("error") is True
    assert result.get("error_type") == "invalid_action"


def test_manage_plugin_disable_enable(isolated_plugin_home):
    source = str(Path("PluginPackage/Common/wait_delay").resolve())
    installed = install_plugin_handler({"source": source, "upgrade": True})
    assert not installed.get("error"), installed
    disabled = manage_plugin_handler({"action": "disable", "name": installed["name"]})
    assert disabled.get("ok") is True
    assert disabled.get("enabled") is False
    enabled = manage_plugin_handler({"action": "enable", "name": installed["name"]})
    assert enabled.get("ok") is True
    assert enabled.get("enabled") is True
