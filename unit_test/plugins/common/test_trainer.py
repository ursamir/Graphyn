# unit_test/plugins/common/test_trainer.py
"""Tests for the trainer plugin.

Covers:
  - Registration (Req 8.2)
  - Metadata (Req 8.12)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/trainer/"
NODE_TYPE = "trainer"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("trainer_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.2 — trainer registers in a fresh registry."""
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
    """Smoke test: TrainerNode.process() with a minimal Keras model and dataset."""
    keras = pytest.importorskip("keras")
    import numpy as np

    # Build a tiny Keras model
    model = keras.Sequential([
        keras.layers.Input(shape=(4, 2, 1)),
        keras.layers.Flatten(),
        keras.layers.Dense(4, activation="relu"),
        keras.layers.Dense(2, activation="softmax"),
    ])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])

    # Build a minimal DatasetArtifact-like object
    class _FakeDataset:
        X_train = np.zeros((4, 4, 2, 1), dtype=np.float32)
        y_train = np.array([0, 1, 0, 1], dtype=np.int32)
        X_val = np.zeros((2, 4, 2, 1), dtype=np.float32)
        y_val = np.array([0, 1], dtype=np.int32)
        labels = ["a", "b"]

    node = installed_cls(
        config={
            "backend": "keras",
            "epochs": 1,
            "batch_size": 2,
            "output_path": str(tmp_path / "trainer_out"),
        },
        seed=0,
    )
    result = node.process({"model": model, "dataset": _FakeDataset()})
    assert "output" in result
