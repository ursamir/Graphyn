# unit_test/f19/test_f19_doc_counts.py
"""F19 / F-21 — counts in the docs are generated and checked, not hand-typed.

Before: NODES.md / ARCHITECTURE.md said 49 node types, AGENTS.md 9 packs / 156
manifests, PLUGIN_GUIDE 48 plugins, README 77 MCP tools — none matched what
actually registers. ``scripts/sync_doc_counts.py`` now owns those numbers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location("sync_doc_counts", REPO / "scripts" / "sync_doc_counts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_are_in_sync_with_what_ships():
    problems = _script().sync(check=True)
    assert problems == [], problems


def test_manifest_counts_match_a_real_registry(tmp_path):
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.venv_manager import PluginVenvManager

    values = _script().compute_values(with_mcp=False)
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path))
    mgr._plugins_dir = str(tmp_path)
    installed = 0
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for toml in sorted((REPO / "PluginPackage").glob("*/*/plugin.toml")):
            mgr.install(str(toml.parent) + "/")
            installed += 1
    assert installed == int(values["plugins"])
    assert len(reg) == int(values["node_types"])


def test_mcp_count_matches_the_server_catalog(monkeypatch):
    from app.mcp import server

    monkeypatch.delenv("GRAPHYN_MCP_HUMAN_APPROVAL", raising=False)
    values = _script().compute_values(with_mcp=True)
    monkeypatch.setattr(server, "_TOOLS", {})
    from app.mcp.tool_registry import register_all_tools

    register_all_tools(server._register)
    assert len(server._TOOLS) == int(values["mcp_tools"])
    assert int(values["mcp_tools_with_approval"]) == int(values["mcp_tools"]) + 1


def test_check_mode_flags_a_stale_number(tmp_path):
    mod = _script()
    for rel in mod.DOCS:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(readme.read_text().replace("<!-- count:mcp_tools -->", "<!-- count:mcp_tools -->1", 1))
    values = mod.compute_values(REPO)
    problems = mod.sync(tmp_path, check=True, values=values)
    assert any("README.md: counts are stale" in p for p in problems), problems
    assert mod.sync(tmp_path, check=False, values=values) == []
    assert mod.sync(tmp_path, check=True, values=values) == []
