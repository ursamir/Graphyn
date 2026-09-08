# unit_test/plugins/audio/test_audio_classifier.py
"""Tests for the audio_classifier plugin.

Covers:
  - Registration (Req 7.14)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - audio_classifier is SISO: process(list[AudioSample | FeatureArray]) -> list[PredictionResult]
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/audio_classifier/"
NODE_TYPE = "audio_classifier"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("audio_classifier_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.14 — audio_classifier registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    """Req 7.19 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────
# AudioClassifierNode.process(self, inputs: list) has its second parameter named
# "inputs", so the SISO wrapper does NOT activate (it only wraps when the param
# is NOT named "inputs"). The node therefore expects the raw list directly.
# With backend="auto" and no model_path, it tries YAMNet (tensorflow_hub).
# If TF is not installed, the node raises ImportError — we skip gracefully.

def _call_process(node, items):
    """Call process() correctly regardless of SISO-wrapper state.

    AudioClassifierNode uses 'inputs' as its parameter name, so the SISO
    wrapper does not activate. We detect this and call accordingly.
    """
    import inspect
    if hasattr(node, "setup"):
        node.setup()
    # Check if the SISO wrapper activated (it stores the original as __wrapped__)
    if hasattr(node.process, "__wrapped__"):
        # SISO-wrapped: pass the dict
        return node.process({"input": items})
    # Not wrapped: inspect the bound method signature (no 'self' in params)
    params = list(inspect.signature(node.process).parameters.keys())
    # If first param is "inputs", the node expects the raw list directly
    if params and params[0] == "inputs":
        result = node.process(items)
        return {"output": result}
    # Fallback: pass dict
    return node.process({"input": items})


def test_process_smoke(installed_cls, make_audio_sample):
    """Smoke test: process returns a list of PredictionResult objects."""
    node = installed_cls(config={}, seed=0)
    try:
        result = _call_process(node, [make_audio_sample()])
    except ImportError:
        pytest.skip("tensorflow/tensorflow_hub not installed — YAMNet backend unavailable")
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


def test_process_empty_input(installed_cls):
    """Empty input list produces empty output."""
    node = installed_cls(config={}, seed=0)
    try:
        result = _call_process(node, [])
    except ImportError:
        pytest.skip("tensorflow/tensorflow_hub not installed — YAMNet backend unavailable")
    assert result["output"] == []


def test_process_output_has_predicted_label(installed_cls, make_audio_sample):
    """Each PredictionResult has a predicted_label attribute."""
    node = installed_cls(config={}, seed=0)
    try:
        result = _call_process(node, [make_audio_sample()])
    except ImportError:
        pytest.skip("tensorflow/tensorflow_hub not installed — YAMNet backend unavailable")
    for pred in result["output"]:
        assert hasattr(pred, "predicted_label")
        assert pred.predicted_label  # non-empty string


def test_confidence_threshold_field_default_off(installed_cls):
    """confidence_threshold None/0 disables filtering."""
    node = installed_cls(config={}, seed=0)
    assert node.config.confidence_threshold is None
    node0 = installed_cls(config={"confidence_threshold": 0.0}, seed=0)
    assert node0.config.confidence_threshold is None


def test_confidence_threshold_rejects_out_of_range(installed_cls):
    import pytest
    with pytest.raises(Exception):
        installed_cls(config={"confidence_threshold": 1.5}, seed=0)


def test_confidence_threshold_filters_predictions(installed_cls, make_audio_sample, monkeypatch):
    """When threshold is set, low top-1 scores are dropped from output."""
    import numpy as np

    node = installed_cls(config={"confidence_threshold": 0.9, "top_k": 3, "backend": "pytorch"}, seed=0)
    calls = {"n": 0}
    scores = [
        (np.array([0.01, 0.02, 0.97], dtype=np.float32), ["a", "b", "c"]),  # keep
        (np.array([0.4, 0.35, 0.25], dtype=np.float32), ["a", "b", "c"]),   # drop (top 0.4 < 0.9)
    ]

    def side_effect(sample, backend):
        i = calls["n"]
        calls["n"] += 1
        return scores[i]

    node._resolved_backend = "pytorch"
    node._labels = ["a", "b", "c"]
    node._model_obj = object()
    monkeypatch.setattr(node, "_classify_audio", side_effect)

    s1 = make_audio_sample()
    s2 = make_audio_sample()
    try:
        s2.path = str(s2.path) + "_low"
    except Exception:
        pass
    out = node.process([s1, s2])
    assert len(out) == 1
    assert out[0].predicted_label == "c"
    assert out[0].metadata.get("confidence_threshold") == 0.9
    assert all(v >= 0.9 for v in out[0].probabilities.values())
