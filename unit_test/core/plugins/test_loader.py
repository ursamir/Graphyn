# unit_test/core/plugins/test_loader.py
"""Tests for PluginLoader platform version compatibility (Req 6)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.plugins.loader import PluginLoader
from app.core.plugins.errors import PluginCompatibilityError
from app.core.plugins.manifest import PluginManifest


def _make_manifest(**overrides) -> PluginManifest:
    """Build a minimal valid PluginManifest."""
    data = {
        "name": "test-plugin",
        "version": "1.0.0",
        "description": "Test plugin.",
        "author": "Tester",
        "platform_version": ">=0.0",
        "entry_points": ["nodes.py"],
        **overrides,
    }
    return PluginManifest.model_validate(data)


def test_platform_compat_accepts_matching_version(fresh_registry) -> None:
    """Req 6 — platform version compat check accepts a matching version."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest(platform_version=">=0.0")

    # Should not raise — >=0.0 matches any version including 0.0.0
    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="1.0.0"
    ):
        loader._check_platform_compat(manifest, Path("/fake"))


def test_platform_compat_rejects_incompatible_major(fresh_registry) -> None:
    """Req 6 — platform version compat check rejects incompatible major version."""
    loader = PluginLoader(fresh_registry)
    # Plugin requires platform >=10.0 but current platform is 1.0.0
    manifest = _make_manifest(platform_version=">=10.0")

    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="1.0.0"
    ):
        with pytest.raises(PluginCompatibilityError):
            loader._check_platform_compat(manifest, Path("/fake"))


def test_platform_compat_exact_version_match(fresh_registry) -> None:
    """Exact version specifier matches correctly."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest(platform_version="==5.0.0")

    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="5.0.0"
    ):
        loader._check_platform_compat(manifest, Path("/fake"))  # no raise


def test_platform_compat_exact_version_mismatch(fresh_registry) -> None:
    """Exact version specifier rejects non-matching version."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest(platform_version="==5.0.0")

    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="4.0.0"
    ):
        with pytest.raises(PluginCompatibilityError):
            loader._check_platform_compat(manifest, Path("/fake"))


def test_python_compat_no_min_python_passes(fresh_registry) -> None:
    """min_python=None skips the Python version check."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest()  # min_python defaults to None
    # Should not raise
    loader._check_python_compat(manifest, Path("/fake"))


def test_python_compat_satisfied(fresh_registry) -> None:
    """min_python satisfied by current interpreter."""
    loader = PluginLoader(fresh_registry)
    # Require Python 2.7 — always satisfied by any modern Python
    manifest = _make_manifest(min_python="2.7")
    loader._check_python_compat(manifest, Path("/fake"))  # no raise


def test_python_compat_unsatisfied(fresh_registry) -> None:
    """min_python higher than current interpreter raises PluginCompatibilityError."""
    loader = PluginLoader(fresh_registry)
    # Require a future Python version that doesn't exist yet
    manifest = _make_manifest(min_python="99.0.0")
    with pytest.raises(PluginCompatibilityError):
        loader._check_python_compat(manifest, Path("/fake"))



TYPES_PY = """\
from app.core.nodes.ports import PortDataType

class StructuredDocument(PortDataType):
    text: str = ""
"""

NODES_PY = """\
from typing import ClassVar
import importlib
from app.core.nodes.base import Node
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
StructuredDocument = _types.StructuredDocument


class StructuredLlmNode(Node):
    node_type: ClassVar[str] = "structured_llm"
    input_ports: ClassVar[dict] = {
        "text": InputPort(name="text", data_type=str),
    }
    output_ports: ClassVar[dict] = {
        "doc": OutputPort(name="doc", data_type=StructuredDocument),
    }
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="structured_llm",
        label="Structured LLM",
        description="Test node.",
        category="test",
    )

    class Config(Node.Config):
        pass

    def process(self, inputs):
        return {}
"""

TOML = """\
[plugin]
name = "structured-llm"
version = "1.0.0"
description = "Test dual entry points."
author = "Tester"
platform_version = ">=0.0"
entry_points = ["types.py", "nodes.py"]
runtime = "inprocess"
node_types = ["structured_llm"]
"""


def _write_dual_entry_plugin(tmp_path: Path, name: str = "structured-llm") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "plugin.toml").write_text(TOML.replace("structured-llm", name), encoding="utf-8")
    (d / "types.py").write_text(TYPES_PY, encoding="utf-8")
    (d / "nodes.py").write_text(NODES_PY, encoding="utf-8")
    return d


def test_inprocess_types_and_nodes_load_and_reload(tmp_path: Path, fresh_registry) -> None:
    """types.py then nodes.py must register nodes; a second load must not fail."""
    plugin_dir = _write_dual_entry_plugin(tmp_path)
    loader = PluginLoader(fresh_registry)
    first = loader.load(plugin_dir)
    assert "structured_llm" in first
    assert "structured_llm" in fresh_registry
    # Simulate a second loader pass (auto-install + load_enabled) without
    # relying solely on the already-loaded name skip.
    loader._loaded_plugins.discard("structured-llm")
    second = loader.load(plugin_dir)
    assert "structured_llm" in second or second == []
    assert "structured_llm" in fresh_registry


def test_import_file_reuses_sys_modules(tmp_path: Path, fresh_registry) -> None:
    """Re-importing the same plugin file under the same module name must reuse sys.modules."""
    import sys
    from app.core.nodes.discovery import AutoDiscovery

    plugin_dir = _write_dual_entry_plugin(tmp_path)
    discovery = AutoDiscovery(fresh_registry)
    path = plugin_dir / "types.py"
    first = discovery._import_file(path, package_prefix=None)
    second = discovery._import_file(path, package_prefix=None)
    assert first is second
    assert sys.modules[first.__name__] is first


def test_load_enabled_skips_already_loaded_plugin(tmp_path: Path, fresh_registry) -> None:
    """auto-install + load_enabled must not fail a plugin whose nodes are already registered."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.store import PluginRecord

    plugin_dir = _write_dual_entry_plugin(tmp_path)
    manager = PluginManager(registry=fresh_registry, base_dir=str(tmp_path))
    manager._plugins_dir = str(tmp_path / "plugins")
    loader = PluginLoader(fresh_registry)
    manager._loader = loader
    types = loader.load(plugin_dir)
    assert "structured_llm" in types
    record = PluginRecord(
        name="structured-llm",
        version="1.0.0",
        source=str(plugin_dir),
        install_path=str(plugin_dir),
        enabled=True,
        installed_at="2024-01-01T00:00:00+00:00",
        manifest={
            "name": "structured-llm",
            "version": "1.0.0",
            "entry_points": ["types.py", "nodes.py"],
            "node_types": ["structured_llm"],
        },
    )
    manager._store.save(record)
    # Must not log a failed load / PluginInstallError.
    manager.load_enabled_plugins()
    assert "structured_llm" in fresh_registry


def test_isolated_already_registered_is_quiet(
    tmp_path: Path, fresh_registry, caplog
) -> None:
    import logging
    from unittest.mock import patch
    from app.core.plugins.venv_manager import PluginVenvManager
    from app.core.plugins.runtime_registry import get_runtime_registry

    d = tmp_path / "iso-plugin"
    d.mkdir()
    (d / "plugin.toml").write_text(
        """\
[plugin]
name = "iso-plugin"
version = "1.0.0"
description = "iso"
author = "t"
platform_version = ">=0.0"
entry_points = ["nodes.py"]
runtime = "isolated"
node_types = ["iso_node"]
""",
        encoding="utf-8",
    )
    (d / "nodes.py").write_text("node_type = \"iso_node\"\n", encoding="utf-8")
    loader = PluginLoader(fresh_registry)
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        loader.load(d)
        loader._loaded_plugins.discard("iso-plugin")
        with caplog.at_level(logging.WARNING):
            loader.load(d)
    try:
        assert "iso_node" in fresh_registry
        assert not any("already registered" in r.message for r in caplog.records)
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")
