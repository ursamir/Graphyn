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
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.14 — audio_classifier registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
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
