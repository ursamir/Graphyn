"""Bundled PluginPackage sync: same-version code drift is reinstalled.

Startup used to skip a bundled plugin whose installed version equalled the
source version, so edited ``PluginPackage`` code never reached
``plugins/installed`` (live Example 06: stale trainer without progress code).
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.content_hash import plugin_tree_hash, requirements_signature
from app.core.plugins.store import PluginStore

from unit_test.core.plugins.test_manager import _make_manager, _patch_loader_load

_TOML = (
    '[plugin]\nname = "{name}"\nversion = "{version}"\n'
    'description = "x"\nauthor = "t"\nplatform_version = ">=0.0"\n'
    'entry_points = ["nodes.py"]\n'
    "dependencies = [{deps}]\n"
)


def _write_pkg_plugin(
    root: Path, name: str = "drift-plug", version: str = "1.0.0", code: str = "# v1\n", deps: str = ""
) -> Path:
    d = root / "PluginPackage" / "Common" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.toml").write_text(_TOML.format(name=name, version=version, deps=deps), encoding="utf-8")
    (d / "nodes.py").write_text(code, encoding="utf-8")
    return d


@pytest.fixture()
def venv_remove():
    with patch("app.core.plugins.venv_manager.PluginVenvManager.remove") as rm:
        yield rm


# ── content hash ─────────────────────────────────────────────────────────────


def test_tree_hash_deterministic_and_ignores_bytecode_and_venvs(tmp_path: Path) -> None:
    d = _write_pkg_plugin(tmp_path)
    h1 = plugin_tree_hash(d)
    assert h1 == plugin_tree_hash(d)
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "nodes.cpython-312.pyc").write_bytes(b"\x00junk")
    (d / "stray.pyc").write_bytes(b"x")
    (d / ".git").mkdir()
    (d / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    venv = d / "localenv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr", encoding="utf-8")
    (venv / "lib.py").write_text("x = 1", encoding="utf-8")
    (d / "venv").mkdir()
    (d / "venv" / "a.py").write_text("x", encoding="utf-8")
    assert plugin_tree_hash(d) == h1


def test_tree_hash_changes_on_content_and_new_file(tmp_path: Path) -> None:
    d = _write_pkg_plugin(tmp_path)
    h1 = plugin_tree_hash(d)
    (d / "nodes.py").write_text("# v2\n", encoding="utf-8")
    h2 = plugin_tree_hash(d)
    assert h2 != h1
    (d / "presets").mkdir()
    (d / "presets" / "p.json").write_text("{}", encoding="utf-8")
    assert plugin_tree_hash(d) not in (h1, h2)


def test_tree_hash_independent_of_location(tmp_path: Path) -> None:
    a = _write_pkg_plugin(tmp_path / "a")
    b = _write_pkg_plugin(tmp_path / "b")
    assert plugin_tree_hash(a) == plugin_tree_hash(b)


def test_requirements_signature_dict_and_order_insensitive() -> None:
    a = {"dependencies": ["numpy>=1", "scipy"], "optional_dependencies": [], "runtime": "isolated"}
    b = {"dependencies": ["scipy", "numpy>=1"], "runtime": "isolated"}
    assert requirements_signature(a) == requirements_signature(b)
    c = dict(a, dependencies=["numpy>=2", "scipy"])
    assert requirements_signature(a) != requirements_signature(c)


# ── startup sync ─────────────────────────────────────────────────────────────


def test_install_stores_source_hash(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    src = _write_pkg_plugin(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)
    with _patch_loader_load(["fixture_node"]):
        record = manager.install(str(src))
    assert record.source_hash == plugin_tree_hash(src)
    assert PluginStore(base_dir=str(tmp_path)).get("drift-plug").source_hash == record.source_hash


def test_same_version_code_change_refreshes_code_and_keeps_venv(
    tmp_path: Path, fresh_registry: NodeRegistry, venv_remove, caplog
) -> None:
    src = _write_pkg_plugin(tmp_path, code="# v1 old trainer\n")
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
    venv_remove.reset_mock()
    installed = tmp_path / "plugins" / "drift-plug"
    assert (installed / "nodes.py").read_text(encoding="utf-8") == "# v1 old trainer\n"

    (src / "nodes.py").write_text("# v1 new trainer with progress\n", encoding="utf-8")
    with patch.object(manager, "install", wraps=manager.install) as install:
        with caplog.at_level(logging.WARNING, logger="app.core.plugins.manager"):
            n = manager._upgrade_bundled_plugins_on_version_drift(pkg)

    assert n == 1
    install.assert_not_called()  # code-only path, not a full reinstall
    venv_remove.assert_not_called()  # isolated venv kept
    assert (installed / "nodes.py").read_text(encoding="utf-8") == "# v1 new trainer with progress\n"
    rec = PluginStore(base_dir=str(tmp_path)).get("drift-plug")
    assert rec.version == "1.0.0"
    assert rec.source_hash == plugin_tree_hash(src)
    assert any("source code changed at the same version" in r.message for r in caplog.records)
    assert not (tmp_path / "plugins" / "drift-plug.__backup__").exists()
    assert not (tmp_path / "plugins" / "drift-plug.__staging__").exists()


def test_unchanged_plugin_is_skipped(tmp_path: Path, fresh_registry: NodeRegistry, venv_remove) -> None:
    _write_pkg_plugin(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
    venv_remove.reset_mock()
    with patch.object(manager, "install") as install, patch.object(
        manager, "_refresh_plugin_code"
    ) as refresh:
        assert manager._upgrade_bundled_plugins_on_version_drift(pkg) == 0
        assert manager.install_bundled_plugins(pkg, upgrade=True) == 1
    install.assert_not_called()
    refresh.assert_not_called()
    venv_remove.assert_not_called()


def test_same_version_requirements_change_does_full_reinstall(
    tmp_path: Path, fresh_registry: NodeRegistry, venv_remove
) -> None:
    src = _write_pkg_plugin(tmp_path, deps="")
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
        venv_remove.reset_mock()
        _write_pkg_plugin(tmp_path, deps='"numpy"')
        with patch.object(manager, "_refresh_plugin_code") as refresh:
            n = manager._upgrade_bundled_plugins_on_version_drift(pkg)
    assert n == 1
    refresh.assert_not_called()
    venv_remove.assert_called_once_with("drift-plug")  # uninstall → venv rebuilt
    rec = PluginStore(base_dir=str(tmp_path)).get("drift-plug")
    assert rec.manifest["dependencies"] == ["numpy"]
    assert rec.source_hash == plugin_tree_hash(src)


def test_legacy_record_without_hash_compares_installed_tree(
    tmp_path: Path, fresh_registry: NodeRegistry, venv_remove
) -> None:
    src = _write_pkg_plugin(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
    store = PluginStore(base_dir=str(tmp_path))
    store.save(store.get("drift-plug").model_copy(update={"source_hash": None}))

    # Same tree → unchanged, hash backfilled.
    assert manager._upgrade_bundled_plugins_on_version_drift(pkg) == 0
    assert store.get("drift-plug").source_hash == plugin_tree_hash(src)

    # Stale installed tree (container case) → refreshed.
    store.save(store.get("drift-plug").model_copy(update={"source_hash": None}))
    (tmp_path / "plugins" / "drift-plug" / "nodes.py").write_text("# stale\n", encoding="utf-8")
    assert manager._upgrade_bundled_plugins_on_version_drift(pkg) == 1
    assert (tmp_path / "plugins" / "drift-plug" / "nodes.py").read_text(encoding="utf-8") == "# v1\n"
    venv_remove.assert_not_called()


def test_refresh_reloads_when_plugin_already_loaded(
    tmp_path: Path, fresh_registry: NodeRegistry, venv_remove
) -> None:
    src = _write_pkg_plugin(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
    manager._loader._loaded_plugins.add("drift-plug")
    (src / "nodes.py").write_text("# v1b\n", encoding="utf-8")
    with patch("app.core.plugins.manager.PluginLoader.load", return_value=["fixture_node"]) as load:
        assert manager._upgrade_bundled_plugins_on_version_drift(pkg) == 1
    load.assert_called_once()
    assert Path(load.call_args.args[0]).name == "drift-plug"


def test_version_bump_still_full_upgrade(tmp_path: Path, fresh_registry: NodeRegistry, venv_remove) -> None:
    _write_pkg_plugin(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
        _write_pkg_plugin(tmp_path, version="1.0.1")
        assert manager._upgrade_bundled_plugins_on_version_drift(pkg) == 1
    assert PluginStore(base_dir=str(tmp_path)).get("drift-plug").version == "1.0.1"
    venv_remove.assert_called_with("drift-plug")


def test_force_reinstalls_unchanged(tmp_path: Path, fresh_registry: NodeRegistry, venv_remove) -> None:
    _write_pkg_plugin(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)
    pkg = tmp_path / "PluginPackage"
    with _patch_loader_load(["fixture_node"]):
        manager.install_bundled_plugins(pkg, upgrade=True)
        with patch.object(manager, "install", wraps=manager.install) as install:
            assert manager.install_bundled_plugins(pkg, upgrade=True, force=True) == 1
    install.assert_called_once()
