# unit_test/f19/test_f19_cli_and_registry.py
"""F19 / F-25 — `graphyn --help` is instant and the host registry drops removed packs.

Before: importing app.cli.main ran initialize_registry() (PluginManager
install/load of every bundled plugin) so even ``graphyn --help`` booted the
plugin manager, and registry records of packs removed from PluginPackage kept
advertising node types the server no longer had (48 vs 36).
"""
from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_help_does_not_boot_plugin_manager(tmp_path):
    env = {**os.environ, "GRAPHYN_HOME": str(tmp_path / "home"), "GRAPHYN_SKIP_PLUGIN_LOAD": ""}
    env.pop("GRAPHYN_SKIP_PLUGIN_LOAD")
    for argv in (["--help"], ["run", "--help"], ["plugin", "--help"]):
        r = subprocess.run(
            [sys.executable, "-c", "import sys; from app.cli.main import main; sys.argv=['graphyn',*sys.argv[1:]]; main()", *argv],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr
        assert "usage:" in r.stdout
        assert "loading plugins" not in r.stderr
        assert not (tmp_path / "home" / "plugins" / "registry.json").exists()


def test_needs_registry_matrix():
    from app.cli.main import _needs_registry

    assert _needs_registry(Namespace(command="run")) is True
    assert _needs_registry(Namespace(command="validate")) is True
    assert _needs_registry(Namespace(command="nodes", api_url=None)) is True
    assert _needs_registry(Namespace(command="nodes", api_url="http://x")) is False
    for cmd in ("runs", "secrets", "data", "users", None):
        assert _needs_registry(Namespace(command=cmd)) is False


def test_prune_removed_bundled_plugins(tmp_path):
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.store import PluginRecord

    pkg_root = tmp_path / "PluginPackage"
    kept = pkg_root / "Common" / "kept"
    kept.mkdir(parents=True)
    (kept / "plugin.toml").write_text("[plugin]\nname='kept'\n")
    gone = pkg_root / "Vision" / "yolo"  # pack removed: no dir at all
    outside = tmp_path / "elsewhere" / "custom"
    outside.mkdir(parents=True)  # user plugin outside PluginPackage, source vanished files
    mgr = PluginManager(registry=NodeRegistry(), base_dir=str(tmp_path / "home"))
    mgr._plugins_dir = str(tmp_path / "home" / "plugins")

    def rec(name, src, nts):
        return PluginRecord(
            name=name, version="1.0.0", source=str(src), install_path=str(tmp_path / "inst" / name),
            enabled=True, installed_at="2026-10-08T00:00:00Z", manifest={"node_types": nts},
        )

    mgr._store.save(rec("kept", kept, ["kept_node"]))
    mgr._store.save(rec("yolo", gone, ["yolo_detect"]))
    mgr._store.save(rec("custom", outside / "missing", ["custom_node"]))
    mgr._store.save(rec("remote", "https://example.invalid/p.zip", ["remote_node"]))

    pruned = mgr.prune_removed_bundled_plugins(pkg_root)
    assert pruned == ["yolo"]
    assert sorted(r.name for r in mgr._store.list()) == ["custom", "kept", "remote"]
    assert mgr.prune_removed_bundled_plugins(pkg_root) == []
