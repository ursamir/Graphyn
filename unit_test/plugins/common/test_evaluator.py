# unit_test/plugins/common/test_evaluator.py
"""Tests for the evaluator plugin.

Covers:
  - Registration (Req 8.3)
  - Metadata (Req 8.12)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/evaluator/"
NODE_TYPE = "evaluator"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("evaluator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.3 — evaluator registers in a fresh registry."""
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
    """Smoke test: EvaluatorNode.process() with a minimal Keras model and dataset."""
    keras = pytest.importorskip("keras")
    import numpy as np
    from app.models.model_artifact import ModelArtifact

    # Build and train a tiny Keras model
    model = keras.Sequential([
        keras.layers.Input(shape=(4, 2, 1)),
        keras.layers.Flatten(),
        keras.layers.Dense(4, activation="relu"),
        keras.layers.Dense(2, activation="softmax"),
    ])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])

    # Save model to tmp_path
    model_path = str(tmp_path / "model.keras")
    model.save(model_path)

    artifact = ModelArtifact(
        model_path=model_path,
        labels=["a", "b"],
        history={"loss": [0.5], "val_loss": [0.6], "accuracy": [0.8], "val_accuracy": [0.7]},
        metrics={"keras_model_path": model_path},
    )

    class _FakeDataset:
        X_test = np.zeros((4, 4, 2, 1), dtype=np.float32)
        y_test = np.array([0, 1, 0, 1], dtype=np.int32)
        labels = ["a", "b"]
        metadata = {}

    node = installed_cls(
        config={
            "output_path": str(tmp_path / "eval_out"),
            "plot_confusion_matrix": False,
            "plot_training_curves": False,
            "compute_roc": False,
        },
        seed=0,
    )
    result = node.process({"model_artifact": artifact, "dataset": _FakeDataset()})
    assert "output" in result
