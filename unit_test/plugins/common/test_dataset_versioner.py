# unit_test/plugins/common/test_dataset_versioner.py
"""Tests for the dataset_versioner plugin.

Covers:
  - Registration (Req 8.7)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.3: determinism — same input → same hash
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/dataset_versioner/"
NODE_TYPE = "dataset_versioner"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_dataset(seed: int = 42):
    """Return a real DatasetArtifact for testing."""
    # DatasetArtifact is defined in the dataset_builder plugin — import lazily
    # after the plugin is installed (module-scoped fixture ensures this).
    try:
        from dataset_builder.types import DatasetArtifact  # type: ignore
    except ImportError:
        from PluginPackage.Common.dataset_builder.types import DatasetArtifact  # type: ignore

    rng = np.random.default_rng(seed)
    X = rng.standard_normal((10, 4, 2, 1)).astype(np.float32)
    y = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1], dtype=np.int32)
    X_val = rng.standard_normal((4, 4, 2, 1)).astype(np.float32)
    y_val = np.array([0, 1, 0, 1], dtype=np.int32)
    X_test = rng.standard_normal((4, 4, 2, 1)).astype(np.float32)
    y_test = np.array([0, 1, 0, 1], dtype=np.int32)

    return DatasetArtifact(
        X_train=X, y_train=y,
        X_val=X_val, y_val=y_val,
        X_test=X_test, y_test=y_test,
        labels=["cat", "dog"],
        n_classes=2,
    )


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("dataset_versioner_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.7 — dataset_versioner registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    """Req 8.12 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke(installed_cls, tmp_path):
    node = installed_cls(
        config={"output_dir": str(tmp_path / "versioned")},
        seed=0,
    )
    dataset = _make_dataset()
    result = node.process({"input": dataset})
    assert result is not None
    assert "output" in result


# ── Req 10.3: determinism ─────────────────────────────────────────────────────

def test_determinism_same_hash(installed_cls, tmp_path):
    """Req 10.3 — same DatasetArtifact input produces same SHA-256 hash both times."""
    dataset = _make_dataset(seed=42)

    node1 = installed_cls(config={"output_dir": str(tmp_path / "v1")}, seed=0)
    result1 = node1.process({"input": dataset})["output"]

    node2 = installed_cls(config={"output_dir": str(tmp_path / "v2")}, seed=0)
    result2 = node2.process({"input": dataset})["output"]

    assert result1.content_hash == result2.content_hash, (
        f"Same input should produce same hash: "
        f"{result1.content_hash!r} != {result2.content_hash!r}"
    )


def test_different_data_different_hash(installed_cls, tmp_path):
    """Different datasets should produce different hashes."""
    dataset_a = _make_dataset(seed=1)
    dataset_b = _make_dataset(seed=99)

    node_a = installed_cls(config={"output_dir": str(tmp_path / "va")}, seed=0)
    node_b = installed_cls(config={"output_dir": str(tmp_path / "vb")}, seed=0)

    result_a = node_a.process({"input": dataset_a})["output"]
    result_b = node_b.process({"input": dataset_b})["output"]

    assert result_a.content_hash != result_b.content_hash, (
        "Different datasets should produce different hashes"
    )


def test_version_tag_set(installed_cls, tmp_path):
    """Output dataset should have a non-empty version and content_hash."""
    dataset = _make_dataset()
    node = installed_cls(config={"output_dir": str(tmp_path / "vt")}, seed=0)
    result = node.process({"input": dataset})["output"]
    assert result.version, "version should be non-empty"
    assert result.content_hash, "content_hash should be non-empty"
