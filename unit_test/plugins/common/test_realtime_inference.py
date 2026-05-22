# unit_test/plugins/common/test_realtime_inference.py
"""Tests for the realtime_inference plugin.

Covers:
  - Registration (Req 8.5)
  - Metadata (Req 8.12)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/realtime_inference/"
NODE_TYPE = "realtime_inference"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("realtime_inference_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.5 — realtime_inference registers in a fresh registry."""
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

def test_construct_requires_model_path(installed_cls):
    """RealtimeInferenceNode requires model_path — construction without it raises."""
    import pydantic
    with pytest.raises((pydantic.ValidationError, ValueError, TypeError)):
        installed_cls(config={}, seed=0)


def test_construct_with_model_path(installed_cls, tmp_path):
    """Construction succeeds when model_path is provided."""
    fake_model = tmp_path / "model.tflite"
    fake_model.write_bytes(b"\x00" * 16)
    node = installed_cls(config={"model_path": str(fake_model)}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke(installed_cls, tmp_path):
    """Smoke test: RealtimeInferenceNode.process() with a TFLite model."""
    tf = pytest.importorskip("tensorflow")
    keras = pytest.importorskip("keras")
    import numpy as np
    from app.models.feature_array import FeatureArray

    # Build a tiny Keras model and convert to TFLite
    model = keras.Sequential([
        keras.layers.Input(shape=(4, 2, 1)),
        keras.layers.Flatten(),
        keras.layers.Dense(2, activation="softmax"),
    ])

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_model = converter.convert()
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(tflite_model)

    # Write labels.txt
    (tmp_path / "labels.txt").write_text("a\nb\n")

    feature = FeatureArray(
        data=np.zeros((4, 2), dtype=np.float32),
        label="a",
        source_path="/fake/audio.wav",
        sample_rate=16000,
    )

    node = installed_cls(
        config={"model_path": str(model_path), "backend": "tflite"},
        seed=0,
    )
    try:
        node.setup()
    except ImportError:
        pytest.skip("tflite_runtime/tensorflow not available for inference")

    result = node.process({"input": [feature]})
    assert "output" in result
