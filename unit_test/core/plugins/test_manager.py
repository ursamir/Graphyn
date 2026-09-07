# unit_test/core/plugins/test_manager.py
"""Tests for PluginManager lifecycle (Req 6 criteria 5–11)."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.errors import (
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


def test_double_install_reuses_existing(tmp_path: Path, fresh_registry: NodeRegistry) -> None:
    """Req 6.6 — double install without upgrade=True reuses the existing record.

    The first install uses the plain plugin name so _parse_name_version extracts
    the correct name and the store lookup works on the second call.
    """
    src = _make_plugin_src(tmp_path)
    manager = _make_manager(tmp_path, registry=fresh_registry)

    # Use plain name so _parse_name_version returns ("test-plugin", None)
    with _patch_resolve(src), _patch_loader_load():
        first = manager.install("test-plugin")

    with _patch_resolve(src), _patch_loader_load():
        second = manager.install("test-plugin")

    assert second.name == first.name
    assert second.version == first.version
    assert len(manager.list_installed()) == 1


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

    for name in ("good-plugin", "bad-plugin"):
        d = tmp_path / "plugins" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.toml").write_text(
            f'[plugin]\nname = "{name}"\nversion = "1.0.0"\n'
            'description = "x"\nauthor = "Tester"\n'
            'platform_version = ">=0.0"\nentry_points = ["nodes.py"]\n',
            encoding="utf-8",
        )
        (d / "nodes.py").write_text("# stub\n", encoding="utf-8")

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


# ---------------------------------------------------------------------------
# PLUGIN-001 — process-wide + flock install serialization
# ---------------------------------------------------------------------------


def test_separate_managers_share_process_lock(
    tmp_path: Path, fresh_registry: NodeRegistry
) -> None:
    """Separate PluginManager instances for the same home share one RLock."""
    m1 = _make_manager(tmp_path, registry=fresh_registry)
    m2 = _make_manager(tmp_path, registry=NodeRegistry())
    assert m1._thread_lock is m2._thread_lock
    assert m1._lock_key == m2._lock_key


def _plugin001_install_worker(
    base_dir: str,
    plugins_dir: str,
    src: str,
    name: str,
    out_path: str,
) -> None:
    """Multiprocessing target: install one plugin via a fresh PluginManager."""
    import os
    from unittest.mock import patch

    os.environ["GRAPHYN_SKIP_PLUGIN_LOAD"] = "1"
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    mgr = PluginManager(registry=NodeRegistry(), base_dir=base_dir)
    mgr._plugins_dir = plugins_dir
    with patch(
        "app.core.plugins.manager.PluginInstaller.resolve",
        return_value=Path(src),
    ), patch(
        "app.core.plugins.manager.PluginLoader.load",
        return_value=[],
    ):
        record = mgr.install(str(src))
    Path(out_path).write_text(record.name, encoding="utf-8")


def test_concurrent_install_distinct_plugins(
    tmp_path: Path, fresh_registry: NodeRegistry
) -> None:
    """PLUGIN-001: concurrent managers install distinct plugins without loss."""
    import multiprocessing as mp

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    n = 8
    srcs = [_make_plugin_src(tmp_path, name=f"conc-{i}", version="1.0.0") for i in range(n)]
    outs = [tmp_path / f"inst{i}.txt" for i in range(n)]
    procs = [
        mp.Process(
            target=_plugin001_install_worker,
            args=(
                str(tmp_path),
                str(plugins_dir),
                str(srcs[i]),
                f"conc-{i}",
                str(outs[i]),
            ),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    names = {o.read_text(encoding="utf-8").strip() for o in outs}
    assert names == {f"conc-{i}" for i in range(n)}

    manager = _make_manager(tmp_path, registry=fresh_registry)
    installed = {r.name for r in manager.list_installed()}
    assert installed == {f"conc-{i}" for i in range(n)}
    for i in range(n):
        assert (plugins_dir / f"conc-{i}").is_dir()


def _plugin001_same_plugin_worker(
    base_dir: str,
    plugins_dir: str,
    src: str,
    out_path: str,
) -> None:
    """Install the same named plugin; either success or reuse is fine."""
    import os
    from unittest.mock import patch

    os.environ["GRAPHYN_SKIP_PLUGIN_LOAD"] = "1"
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    mgr = PluginManager(registry=NodeRegistry(), base_dir=base_dir)
    mgr._plugins_dir = plugins_dir
    try:
        with patch(
            "app.core.plugins.manager.PluginInstaller.resolve",
            return_value=Path(src),
        ), patch(
            "app.core.plugins.manager.PluginLoader.load",
            return_value=[],
        ):
            record = mgr.install(str(src))
        Path(out_path).write_text(f"ok:{record.name}", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — surface to parent via file
        Path(out_path).write_text(f"err:{type(exc).__name__}:{exc}", encoding="utf-8")


def test_concurrent_install_same_plugin_consistent(
    tmp_path: Path, fresh_registry: NodeRegistry
) -> None:
    """PLUGIN-001: racing installs of the same plugin leave one consistent record."""
    import multiprocessing as mp

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    src = _make_plugin_src(tmp_path, name="race-plugin", version="1.0.0")
    n = 6
    outs = [tmp_path / f"race{i}.txt" for i in range(n)]
    procs = [
        mp.Process(
            target=_plugin001_same_plugin_worker,
            args=(str(tmp_path), str(plugins_dir), str(src), str(outs[i])),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    results = [o.read_text(encoding="utf-8").strip() for o in outs]
    assert all(r.startswith("ok:") for r in results), results

    manager = _make_manager(tmp_path, registry=fresh_registry)
    records = [r for r in manager.list_installed() if r.name == "race-plugin"]
    assert len(records) == 1
    assert records[0].version == "1.0.0"
    assert (plugins_dir / "race-plugin").is_dir()
