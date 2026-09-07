"""Regression: initialize_registry populates NodeRegistry (catalog empty bug)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.store import PluginRecord, PluginStore


MANIFEST = """\
[plugin]
name = "{name}"
version = "1.0.0"
description = "Init registry fixture."
author = "Tester"
platform_version = ">=0.0"
entry_points = ["nodes.py"]
"""

NODES = """\
from typing import ClassVar
from app.core.nodes.base import Node
from app.core.nodes.metadata import NodeMetadata


class InitFixtureNode(Node):
    node_type: ClassVar[str] = "init_fixture_node"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="init_fixture_node",
        label="Init Fixture",
        description="Registered by initialize_registry regression test.",
        category="test",
    )

    class Config(Node.Config):
        pass

    def process(self, inputs):
        return {}
"""


def _reset_nodes_package() -> None:
    """Reload app.core.nodes so initialize_registry is idempotent-fresh."""
    import app.core.nodes as nodes_pkg

    nodes_pkg._initialized = False
    nodes_pkg.registry._classes.clear()
    nodes_pkg.registry._metadata.clear()
    nodes_pkg.registry._plugin_ui_fields.clear()


def _write_installed_plugin(plugins_installed: Path, name: str = "init-fixture") -> Path:
    d = plugins_installed / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.toml").write_text(MANIFEST.format(name=name), encoding="utf-8")
    (d / "nodes.py").write_text(NODES, encoding="utf-8")
    return d


def test_initialize_registry_loads_temp_plugin_install_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After init with a temp GRAPHYN_HOME install dir, get_registry() is non-empty."""
    home = tmp_path / "graphyn-home"
    installed = home / "plugins" / "installed"
    installed.mkdir(parents=True)
    plugin_dir = _write_installed_plugin(installed)

    store = PluginStore(base_dir=str(home))
    store.save(
        PluginRecord(
            name="init-fixture",
            version="1.0.0",
            source=str(plugin_dir),
            install_path=str(plugin_dir),
            enabled=True,
            installed_at="2024-01-01T00:00:00+00:00",
            manifest={
                "name": "init-fixture",
                "version": "1.0.0",
                "entry_points": ["nodes.py"],
                "node_types": ["init_fixture_node"],
            },
        )
    )

    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "")
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_PLUGINS_DIR", raising=False)

    _reset_nodes_package()
    from app.core.nodes import initialize_registry, registry
    from app.core.registry_runtime import get_registry

    initialize_registry()
    reg = get_registry()
    assert len(reg) >= 1
    assert "init_fixture_node" in registry._classes
    assert reg is registry


def test_initialize_registry_heals_stale_pytest_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale /tmp/pytest-of-* records heal via plugins_home or are pruned."""
    home = tmp_path / "graphyn-home"
    installed = home / "plugins" / "installed"
    installed.mkdir(parents=True)
    plugin_dir = _write_installed_plugin(installed, name="healed-plug")

    store = PluginStore(base_dir=str(home))
    store.save(
        PluginRecord(
            name="healed-plug",
            version="1.0.0",
            source="/tmp/pytest-of-box/gone/healed-plug",
            install_path="/tmp/pytest-of-box/gone/healed-plug",
            enabled=True,
            installed_at="2024-01-01T00:00:00+00:00",
            manifest={
                "name": "healed-plug",
                "version": "1.0.0",
                "entry_points": ["nodes.py"],
                "node_types": ["init_fixture_node"],
            },
        )
    )
    store.save(
        PluginRecord(
            name="totally-gone",
            version="1.0.0",
            source="/tmp/pytest-of-box/gone/totally-gone",
            install_path="/tmp/pytest-of-box/gone/totally-gone",
            enabled=True,
            installed_at="2024-01-01T00:00:00+00:00",
            manifest={"name": "totally-gone", "version": "1.0.0", "entry_points": ["nodes.py"]},
        )
    )

    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "")
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_PLUGINS_DIR", raising=False)

    _reset_nodes_package()
    from app.core.nodes import initialize_registry, registry

    initialize_registry()
    assert "init_fixture_node" in registry._classes
    names = {r.name for r in PluginStore(base_dir=str(home)).list()}
    assert "healed-plug" in names
    assert "totally-gone" not in names
    healed = PluginStore(base_dir=str(home)).get("healed-plug")
    assert Path(healed.install_path).resolve() == plugin_dir.resolve()


def test_initialize_registry_skip_flag_leaves_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GRAPHYN_SKIP_PLUGIN_LOAD=1 must still skip install/load (test isolation)."""
    home = tmp_path / "graphyn-home"
    installed = home / "plugins" / "installed"
    installed.mkdir(parents=True)
    _write_installed_plugin(installed)

    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "1")
    monkeypatch.setenv("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")

    _reset_nodes_package()
    from app.core.nodes import initialize_registry, registry

    initialize_registry()
    assert len(registry) == 0
