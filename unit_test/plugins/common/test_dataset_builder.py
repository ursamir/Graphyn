# unit_test/plugins/common/test_dataset_builder.py
"""Tests for the dataset_builder plugin.

Covers:
  - Registration (Req 8.1)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.1: split size preservation invariant
  - Req 10.2: output format invariant (numpy)
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/dataset_builder/"
NODE_TYPE = "dataset_builder"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_feature_arrays(n: int = 20, n_frames: int = 10, n_feats: int = 8):
    """Return a list of minimal FeatureArray-like objects for testing."""
    from app.models.feature_array import FeatureArray
    rng = np.random.default_rng(0)
    labels = ["cat", "dog"]
    arrays = []
    for i in range(n):
        data = rng.standard_normal((n_frames, n_feats)).astype(np.float32)
        label = labels[i % len(labels)]
        arrays.append(FeatureArray(
            data=data,
            label=label,
            source_path=f"/fake/{label}_{i}.wav",
            sample_rate=16000,
        ))
    return arrays


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("dataset_builder_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.1 — dataset_builder registers in a fresh registry."""
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
    node = installed_cls(config={"stratify": False}, seed=0)
    features = _make_feature_arrays(n=20)
    result = node.process({"input": features})
    assert "output" in result


# ── Req 10.1: split size preservation ────────────────────────────────────────

def test_split_size_preservation(installed_cls):
    """Req 10.1 — len(X_train) + len(X_val) + len(X_test) == N.

    **Validates: Requirement 10.1**
    """
    n = 30
    features = _make_feature_arrays(n=n)
    node = installed_cls(
        config={
            "split_ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
            "stratify": False,
            "shuffle": True,
        },
        seed=0,
    )
    result = node.process({"input": features})
    artifact = result["output"]
    total = len(artifact.X_train) + len(artifact.X_val) + len(artifact.X_test)
    assert total == n, f"Expected {n} total samples, got {total}"


def test_split_size_preservation_various_sizes(installed_cls):
    """Req 10.1 — split size preservation holds for different N values."""
    for n in [10, 20, 50]:
        features = _make_feature_arrays(n=n)
        node = installed_cls(
            config={
                "split_ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "stratify": False,
                "shuffle": False,
            },
            seed=0,
        )
        result = node.process({"input": features})
        artifact = result["output"]
        total = len(artifact.X_train) + len(artifact.X_val) + len(artifact.X_test)
        assert total == n, f"N={n}: expected {n} total, got {total}"


# ── Req 10.2: output format invariant ────────────────────────────────────────

def test_output_format_numpy(installed_cls):
    """Req 10.2 — output_format='numpy' produces numpy arrays for X_train.

    **Validates: Requirement 10.2**
    """
    features = _make_feature_arrays(n=20)
    node = installed_cls(
        config={"output_format": "numpy", "stratify": False},
        seed=0,
    )
    result = node.process({"input": features})
    artifact = result["output"]
    assert isinstance(artifact.X_train, np.ndarray), (
        f"Expected numpy.ndarray, got {type(artifact.X_train)}"
    )


def test_empty_input(installed_cls):
    """Empty input returns a DatasetArtifact with n_classes=0."""
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": []})
    assert "output" in result
    assert result["output"].n_classes == 0
