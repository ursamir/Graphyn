"""Bundled PluginPackage auto-install at startup (no network)."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.config import auto_install_plugins
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from app.core.plugins.store import PluginRecord

from unit_test.core.plugins.test_manager import (
    _make_manager,
    _make_plugin_src,
    _patch_loader_load,
)


def _write_package_plugin(root: Path, category: str, name: str, version: str = "1.0.0") -> Path:
    src = _make_plugin_src(root, name=name, version=version)
    dest = root / "PluginPackage" / category / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    # _make_plugin_src already created a dir; copy tree via rename of files
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "plugin.toml").write_text((src / "plugin.toml").read_text(encoding="utf-8"), encoding="utf-8")
    (dest / "nodes.py").write_text((src / "nodes.py").read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def test_auto_install_plugins_default_production(monkeypatch) -> None:
    monkeypatch.delenv("GRAPHYN_AUTO_INSTALL_PLUGINS", raising=False)
    monkeypatch.setenv("GRAPHYN_ENV", "production")
    assert auto_install_plugins() is True


def test_auto_install_plugins_explicit_off(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")
    monkeypatch.setenv("GRAPHYN_ENV", "production")
    assert auto_install_plugins() is False


def test_auto_install_plugins_explicit_on_dev(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "true")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    assert auto_install_plugins() is True


def test_install_bundled_plugins_from_temp_package(
    tmp_path: Path, fresh_registry: NodeRegistry
) -> None:
    _write_package_plugin(tmp_path, "Common", "auto-fx")
    _write_package_plugin(tmp_path, "Audio", "auto-audio")
    manager = _make_manager(tmp_path, registry=fresh_registry)
    package_root = tmp_path / "PluginPackage"

    with _patch_loader_load(["fixture_node"]):
        n = manager.install_bundled_plugins(package_root, upgrade=True)

    assert n == 2
    names = {r.name for r in manager.list_installed()}
    assert names == {"auto-fx", "auto-audio"}


def test_install_bundled_plugins_idempotent(
    tmp_path: Path, fresh_registry: NodeRegistry
) -> None:
    _write_package_plugin(tmp_path, "Common", "auto-fx")
    manager = _make_manager(tmp_path, registry=fresh_registry)
    package_root = tmp_path / "PluginPackage"

    with _patch_loader_load(["fixture_node"]):
        first = manager.install_bundled_plugins(package_root, upgrade=True)
        second = manager.install_bundled_plugins(package_root, upgrade=True)

    assert first == 1
    assert second == 1
    assert len(manager.list_installed()) == 1


def test_maybe_auto_install_skips_when_skip_flag(
    tmp_path: Path, fresh_registry: NodeRegistry, monkeypatch
) -> None:
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "1")
    manager = _make_manager(tmp_path, registry=fresh_registry)
    manager.install_bundled_plugins = MagicMock(return_value=9)  # type: ignore[method-assign]
    manager.load_enabled_plugins = MagicMock()  # type: ignore[method-assign]

    n = manager.maybe_auto_install_and_load(tmp_path / "PluginPackage")

    assert n == 0
    manager.install_bundled_plugins.assert_not_called()
    manager.load_enabled_plugins.assert_not_called()


def test_maybe_auto_install_when_enabled_list_empty(
    tmp_path: Path, fresh_registry: NodeRegistry, monkeypatch
) -> None:
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "0")
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    _write_package_plugin(tmp_path, "Common", "auto-fx")
    manager = _make_manager(tmp_path, registry=fresh_registry)

    with _patch_loader_load(["fixture_node"]):
        n = manager.maybe_auto_install_and_load(tmp_path / "PluginPackage")

    assert n == 1
    assert manager.list_installed()[0].enabled is True


def test_maybe_auto_install_respects_flag_when_plugins_present(
    tmp_path: Path, fresh_registry: NodeRegistry, monkeypatch
) -> None:
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "")
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    manager = _make_manager(tmp_path, registry=fresh_registry)
    from app.core.plugins.store import PluginStore

    store = PluginStore(base_dir=str(tmp_path))
    store.save(
        PluginRecord(
            name="already",
            version="1.0.0",
            source="/tmp/already",
            install_path=str(tmp_path / "plugins" / "already"),
            enabled=True,
            installed_at="2024-01-01T00:00:00+00:00",
            manifest={"name": "already", "version": "1.0.0"},
        )
    )
    manager.install_bundled_plugins = MagicMock(return_value=3)  # type: ignore[method-assign]
    with patch.object(manager, "load_enabled_plugins") as load:
        n = manager.maybe_auto_install_and_load(tmp_path / "PluginPackage")

    assert n == 0
    manager.install_bundled_plugins.assert_not_called()
    load.assert_called_once()


def test_install_bundled_continues_on_failure(
    tmp_path: Path, fresh_registry: NodeRegistry, caplog
) -> None:
    _write_package_plugin(tmp_path, "Common", "good-plug")
    _write_package_plugin(tmp_path, "Audio", "bad-plug")
    manager = _make_manager(tmp_path, registry=fresh_registry)

    def fake_install(source: str, upgrade: bool = False, expected_sha256=None):
        if "bad-plug" in source:
            raise RuntimeError("boom")
        return PluginRecord(
            name="good-plug",
            version="1.0.0",
            source=source,
            install_path=str(tmp_path / "plugins" / "good-plug"),
            enabled=True,
            installed_at="2024-01-01T00:00:00+00:00",
            manifest={"name": "good-plug", "version": "1.0.0"},
        )

    with patch.object(manager, "install", side_effect=fake_install):
        with caplog.at_level(logging.WARNING):
            n = manager.install_bundled_plugins(tmp_path / "PluginPackage", upgrade=True)

    assert n == 1
    assert any("bad-plug" in r.message for r in caplog.records)
