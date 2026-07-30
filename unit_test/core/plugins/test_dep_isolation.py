# unit_test/core/plugins/test_dep_isolation.py
"""Tests for plugin dependency status, conflict guard, venvs, and runtime field."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.plugins.dependencies import DependencyChecker, PLATFORM_CONSTRAINTS
from app.core.plugins.errors import PluginDependencyError, PluginManifestError
from app.core.plugins.manifest import PluginManifest
from app.core.plugins.runtime_registry import (
    IsolatedPluginSpec,
    PluginRuntimeRegistry,
)
from app.core.plugins.venv_manager import PluginVenvManager


def test_manifest_runtime_default_inprocess() -> None:
    m = PluginManifest(
        name="demo-plugin",
        version="1.0.0",
        description="demo",
        author="t",
        platform_version=">=0.0",
        entry_points=["nodes.py"],
    )
    assert m.runtime == "inprocess"


def test_manifest_runtime_isolated() -> None:
    m = PluginManifest(
        name="demo-plugin",
        version="1.0.0",
        description="demo",
        author="t",
        platform_version=">=0.0",
        entry_points=["nodes.py"],
        runtime="isolated",
        optional_dependencies=["pytest>=0.1"],
    )
    assert m.runtime == "isolated"


def test_manifest_runtime_invalid() -> None:
    with pytest.raises(PluginManifestError):
        PluginManifest(
            name="demo-plugin",
            version="1.0.0",
            description="demo",
            author="t",
            platform_version=">=0.0",
            entry_points=["nodes.py"],
            runtime="container",
        )


def test_dependency_status_lists_optional() -> None:
    rows = DependencyChecker().status(
        ["pytest>=0.1"],
        optional_dependencies=["this-package-does-not-exist-graphyn-xyz"],
    )
    assert rows[0].satisfied is True
    assert rows[0].optional is False
    assert rows[1].satisfied is False
    assert rows[1].optional is True


def test_conflict_platform_numpy_pin() -> None:
    conflicts = DependencyChecker().check_conflicts(["numpy>=99"])
    # Either platform requires conflict or installed-version conflict
    assert conflicts


def test_runtime_registry_roundtrip() -> None:
    reg = PluginRuntimeRegistry()
    spec = IsolatedPluginSpec(
        plugin_name="trainer",
        install_path="/tmp/trainer",
        venv_python="/tmp/venv/bin/python",
        node_types=("trainer", "model_builder"),
    )
    reg.register(spec)
    assert reg.get_for_node("trainer") is spec
    reg.unregister_plugin("trainer")
    assert reg.get_for_node("trainer") is None


def test_venv_manager_create_and_gc(tmp_path: Path) -> None:
    mgr = PluginVenvManager(base_dir=tmp_path)
    py = mgr.ensure("tiny-plugin", ["pip"])  # pip already present; no-op install
    assert Path(py).exists()
    lock = mgr.lockfile_path("tiny-plugin")
    assert lock.exists()
    removed = mgr.gc_unused(set())
    assert "tiny-plugin" in removed
    assert not mgr.venv_dir("tiny-plugin").exists()


def test_platform_constraints_nonempty() -> None:
    assert any(c.startswith("numpy") for c in PLATFORM_CONSTRAINTS)
