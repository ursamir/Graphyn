# unit_test/plugins/common/test_dataset_balancer.py
"""Tests for the dataset_balancer plugin.

Covers:
  - Registration (Req 8.6)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.4: oversample size invariant
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/dataset_balancer/"
NODE_TYPE = "dataset_balancer"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_imbalanced_dataset(n_majority: int = 20, n_minority: int = 5):
    """Return a real DatasetArtifact with imbalanced classes."""
    try:
        from dataset_builder.types import DatasetArtifact  # type: ignore
    except ImportError:
        from PluginPackage.Common.dataset_builder.types import DatasetArtifact  # type: ignore

    rng = np.random.default_rng(42)
    n_total = n_majority + n_minority
    X = rng.standard_normal((n_total, 4, 2, 1)).astype(np.float32)
    y = np.array([0] * n_majority + [1] * n_minority, dtype=np.int32)

    return DatasetArtifact(
        X_train=X, y_train=y,
        X_val=np.zeros((2, 4, 2, 1), dtype=np.float32),
        y_val=np.array([0, 1], dtype=np.int32),
        X_test=np.zeros((2, 4, 2, 1), dtype=np.float32),
        y_test=np.array([0, 1], dtype=np.int32),
        labels=["cat", "dog"],
        n_classes=2,
    )


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("dataset_balancer_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.6 — dataset_balancer registers in a fresh registry."""
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

def test_process_smoke(installed_cls):
    node = installed_cls(config={"strategy": "oversample"}, seed=0)
    dataset = _make_imbalanced_dataset()
    result = node.process({"input": dataset})
    assert result is not None
    assert "output" in result


# ── Req 10.4: oversample size invariant ──────────────────────────────────────

def test_oversample_size_invariant(installed_cls):
    """Req 10.4 — oversample produces >= original training set size."""
    dataset = _make_imbalanced_dataset(n_majority=20, n_minority=5)
    original_count = len(dataset.X_train)

    node = installed_cls(config={"strategy": "oversample"}, seed=0)
    result = node.process({"input": dataset})["output"]

    assert len(result.X_train) >= original_count, (
        f"Oversample should produce >= {original_count} samples, "
        f"got {len(result.X_train)}"
    )


def test_oversample_balances_classes(installed_cls):
    """Oversample should make all classes have equal count (matching majority)."""
    dataset = _make_imbalanced_dataset(n_majority=20, n_minority=5)
    node = installed_cls(config={"strategy": "oversample"}, seed=0)
    result = node.process({"input": dataset})["output"]

    classes, counts = np.unique(result.y_train, return_counts=True)
    assert counts.min() >= 20, (
        f"After oversample, minority class should have >= 20 samples, got {counts.min()}"
    )


def test_undersample_reduces_majority(installed_cls):
    """Undersample should reduce majority class to match minority."""
    dataset = _make_imbalanced_dataset(n_majority=20, n_minority=5)
    node = installed_cls(config={"strategy": "undersample"}, seed=0)
    result = node.process({"input": dataset})["output"]

    classes, counts = np.unique(result.y_train, return_counts=True)
    assert counts.max() <= 20, "Undersample should not exceed original majority count"
    assert len(result.X_train) <= len(dataset.X_train)
