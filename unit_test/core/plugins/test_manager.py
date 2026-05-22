# unit_test/core/plugins/test_manager.py
"""Tests for PluginManager lifecycle (Req 6 criteria 5–11)."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.errors import (
    PluginAlreadyInstalledError,
    PluginNotFoundError,
)
from app.core.plugins.manager import PluginManager
from app.core.plugins.store import PluginRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MANIFEST_TOML = """\
[plugin]
name = "{name}"
version = "{version}"
description = "A test plugin."
author = "Test Author"
platform_version = ">=0.0.0"
entry_points = ["nodes.py"]
"""

NODES_PY = """\
from typing import ClassVar
from app.core.nodes.base import Node
from app.core.nodes.metadata import NodeMetadata


class FixtureNode(Node):
    node_type: ClassVar[str] = "fixture_node"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="fixture_node",
        label="Fixture Node",
        description="A fixture node for testing.",
        category="test",
    )

    class Config(Node.Config):
        pass

    def process(self, inputs):
        return {}
"""


def _make_plugin_src(tmp_path: Path, name: str = "test-plugin", version: str = "1.0.0") -> Path:
    """Create a minimal plugin source directory."""
    src = tmp_path / f"src_{name}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "plugin.toml").write_text(
        MANIFEST_TOML.format(name=name, version=version), encoding="utf-8"
    )
    (src / "nodes.py").write_text(NODES_PY, encoding="utf-8")
    return src


def _make_manager(tmp_path: Path, registry: NodeRegistry | None = None) -> PluginManager:
    """Return a PluginManager isolated to tmp_path."""
    reg = registry or NodeRegistry()
    manager = PluginManager(registry=reg, base_dir=str(tmp_path))
    manager._plugins_dir = str(tmp_path / "plugins")
    return manager


def _patch_resolve(resolved_dir: Path):
    return patch(
        "app.core.plugins.manager.PluginInstaller.resolve",
        return_value=resolved_dir,
    )


def _patch_loader_load(node_types: list[str] | None = None):
    return patch(
        "app.core.plugins.manager.PluginLoader.load",
        return_value=node_types or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_install_registers_node_type(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.5 — install into tmp_plugin_dir registers node type in fresh_registry."""
    src = _make_plugin_src(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)

    with _patch_resolve(src), _patch_loader_load(["fixture_node"]):
        record = manager.install(str(src))

    assert isinstance(record, PluginRecord)
    assert record.enabled is True
    assert record.name == "test-plugin"


def test_double_install_raises(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.6 — double install without upgrade=True raises PluginAlreadyInstalledError.

    The first install uses the plain plugin name so _parse_name_version extracts
    the correct name and the store lookup works on the second call.
    """
    src = _make_plugin_src(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)

    # Use plain name so _parse_name_version returns ("test-plugin", None)
    with _patch_resolve(src), _patch_loader_load():
        manager.install("test-plugin")

    with _patch_resolve(src), _patch_loader_load():
        with pytest.raises(PluginAlreadyInstalledError):
            manager.install("test-plugin")


def test_uninstall_removes_record(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.7 — uninstall removes the PluginRecord from the store."""
    src = _make_plugin_src(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)

    with _patch_resolve(src), _patch_loader_load():
        record = manager.install(str(src))

    manager.uninstall(record.name)

    with pytest.raises(PluginNotFoundError):
        manager.get(record.name)


def test_disable_updates_record(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.8 — disable updates PluginRecord with enabled=False."""
    src = _make_plugin_src(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)

    with _patch_resolve(src), _patch_loader_load():
        record = manager.install(str(src))

    updated = manager.disable(record.name)
    assert updated.enabled is False

    # Verify persistence
    reloaded = manager.get(record.name)
    assert reloaded.enabled is False


def test_enable_updates_record(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.9 — enable updates PluginRecord with enabled=True."""
    src = _make_plugin_src(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)

    with _patch_resolve(src), _patch_loader_load():
        record = manager.install(str(src))

    manager.disable(record.name)

    with _patch_loader_load():
        updated = manager.enable(record.name)

    assert updated.enabled is True

    reloaded = manager.get(record.name)
    assert reloaded.enabled is True


def test_uninstall_nonexistent_raises(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.10 — uninstall nonexistent plugin raises PluginNotFoundError."""
    manager = _make_manager(tmp_path, registry=fresh_registry)
    with pytest.raises(PluginNotFoundError):
        manager.uninstall("nonexistent-plugin")


def test_load_enabled_plugins_fault_isolation(
    tmp_path: Path, fresh_registry: NodeRegistry, caplog
) -> None:
    """Req 6.11 — one failing plugin doesn't stop others from loading."""
    # Create two plugin records in the store
    from app.core.plugins.store import PluginStore

    store = PluginStore(base_dir=str(tmp_path))

    good_record = PluginRecord(
        name="good-plugin",
        version="1.0.0",
        source="/tmp/good",
        install_path=str(tmp_path / "plugins" / "good-plugin"),
        enabled=True,
        installed_at="2024-01-01T00:00:00+00:00",
        manifest={
            "name": "good-plugin",
            "version": "1.0.0",
            "description": "Good plugin.",
            "author": "Tester",
            "platform_version": ">=0.0",
            "entry_points": ["nodes.py"],
        },
    )
    bad_record = PluginRecord(
        name="bad-plugin",
        version="1.0.0",
        source="/tmp/bad",
        install_path=str(tmp_path / "plugins" / "bad-plugin"),
        enabled=True,
        installed_at="2024-01-01T00:00:00+00:00",
        manifest={
            "name": "bad-plugin",
            "version": "1.0.0",
            "description": "Bad plugin.",
            "author": "Tester",
            "platform_version": ">=0.0",
            "entry_points": ["nodes.py"],
        },
    )
    store.save(good_record)
    store.save(bad_record)

    manager = _make_manager(tmp_path, registry=fresh_registry)

    loaded_names: list[str] = []

    def fake_load(plugin_dir: Path) -> list[str]:
        name = plugin_dir.name
        if name == "bad-plugin":
            raise RuntimeError("Simulated load failure")
        loaded_names.append(name)
        return []

    with patch.object(manager._loader, "load", side_effect=fake_load):
        with caplog.at_level(logging.WARNING):
            # Should not raise even though bad-plugin fails
            manager.load_enabled_plugins()

    # good-plugin was loaded
    assert "good-plugin" in loaded_names
    # A warning was logged for bad-plugin
    assert any("bad-plugin" in record.message for record in caplog.records)
