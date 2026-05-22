# unit_test/plugins/common/test_edge_optimizer.py
"""Tests for the edge_optimizer plugin.

Covers:
  - Registration (Req 8.4)
  - Metadata (Req 8.12)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/edge_optimizer/"
NODE_TYPE = "edge_optimizer"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("edge_optimizer_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.4 — edge_optimizer registers in a fresh registry."""
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
    """Smoke test: EdgeOptimizerNode.process() with a minimal Keras SavedModel."""
    tf = pytest.importorskip("tensorflow")
    keras = pytest.importorskip("keras")
    import numpy as np
    from app.models.model_artifact import ModelArtifact

    # Build and export a tiny Keras model as SavedModel
    model = keras.Sequential([
        keras.layers.Input(shape=(4, 2, 1)),
        keras.layers.Flatten(),
        keras.layers.Dense(2, activation="softmax"),
    ])
    saved_model_path = str(tmp_path / "saved_model")
    try:
        model.export(saved_model_path)
    except AttributeError:
        tf.saved_model.save(model, saved_model_path)

    # Save representative data for INT8 calibration
    import os
    os.makedirs(saved_model_path, exist_ok=True)
    np.save(str(tmp_path / "saved_model" / "X_train_repr.npy"),
            np.zeros((4, 4, 2, 1), dtype=np.float32))

    artifact = ModelArtifact(
        model_path=saved_model_path,
        labels=["a", "b"],
    )

    node = installed_cls(
        config={
            "backend": "tflite",
            "quantization": "float32",
            "output_path": str(tmp_path / "optimized"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})
    assert "output" in result
