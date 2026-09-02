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


def _load_edge_nodes():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "PluginPackage/Common/edge_optimizer/nodes.py"
    spec = importlib.util.spec_from_file_location("graphyn_edge_nodes_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_tflite_converter_uses_keras_file_not_saved_model(tmp_path):
    """model_path as a file uses from_keras_model; dirs keep from_saved_model. No TF download."""
    from unittest.mock import MagicMock, patch
    from app.models.model_artifact import ModelArtifact

    nodes = _load_edge_nodes()
    keras_file = tmp_path / "model.keras"
    keras_file.write_bytes(b"fake-keras")
    saved_dir = tmp_path / "saved_model"
    saved_dir.mkdir()
    (saved_dir / "X_train_repr.npy").write_bytes(b"")

    fake_tf = MagicMock()
    conv = MagicMock()
    fake_tf.lite.TFLiteConverter.from_keras_model.return_value = conv
    fake_tf.lite.TFLiteConverter.from_saved_model.return_value = conv
    loaded = MagicMock()

    with patch.dict("sys.modules", {"keras": MagicMock(), "keras.models": MagicMock()}):
        import keras

        keras.models.load_model.return_value = loaded
        art_file = ModelArtifact(model_path=str(keras_file), labels=["a"])
        nodes.EdgeOptimizerNode._tflite_converter(fake_tf, art_file)
        fake_tf.lite.TFLiteConverter.from_keras_model.assert_called_once_with(loaded)
        fake_tf.lite.TFLiteConverter.from_saved_model.assert_not_called()

        art_dir = ModelArtifact(model_path=str(saved_dir), labels=["a"])
        fake_tf.lite.TFLiteConverter.from_keras_model.reset_mock()
        nodes.EdgeOptimizerNode._tflite_converter(fake_tf, art_dir)
        fake_tf.lite.TFLiteConverter.from_saved_model.assert_called_once_with(str(saved_dir))


def test_int8_repr_path_sibling_of_keras_file(tmp_path):
    import numpy as np
    from app.models.model_artifact import ModelArtifact

    nodes = _load_edge_nodes()
    keras_file = tmp_path / "model.keras"
    keras_file.write_bytes(b"x")
    saved = tmp_path / "saved_model"
    saved.mkdir()
    np.save(str(saved / "X_train_repr.npy"), np.zeros((2, 1), dtype=np.float32))
    art = ModelArtifact(
        model_path=str(keras_file),
        labels=["a"],
        metrics={"keras_model_path": str(keras_file)},
    )
    found = nodes.EdgeOptimizerNode._int8_repr_path(art)
    assert found.name == "X_train_repr.npy"
    assert found.exists()
