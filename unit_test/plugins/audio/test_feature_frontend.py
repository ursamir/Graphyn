# unit_test/plugins/audio/test_feature_frontend.py
"""Tests for the feature_frontend plugin.

Covers:
  - Registration (Req 7.2)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - Req 9 criteria 6–7: MFCC dimension invariant, ZCR shape invariant
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/feature_frontend/"
NODE_TYPE = "feature_frontend"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("feature_frontend_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.2 — feature_frontend registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke(installed_cls, make_audio_sample):
    node = installed_cls(config={"feature_type": "log_mel"}, seed=0)
    result = node.process({"input": [make_audio_sample(sr=16000, n=4000)]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


# ── Req 9.6: MFCC dimension invariant ────────────────────────────────────────

@given(n_mfcc=st.integers(min_value=5, max_value=40))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_mfcc_dimension_invariant(installed_cls, make_audio_sample, n_mfcc):
    """Req 9.6 — FeatureArray.data.shape[1] == n_mfcc for feature_type='mfcc'.

    The node transposes librosa's (n_mfcc, T) output to (T, n_mfcc) for
    downstream compatibility, so the coefficient dimension is axis 1.

    **Validates: Requirement 9.6**
    """
    node = installed_cls(
        config={"feature_type": "mfcc", "n_mfcc": n_mfcc},
        seed=0,
    )
    # Need enough samples for at least one STFT frame
    sample = make_audio_sample(sr=16000, n=8000)
    result = node.process({"input": [sample]})
    assert len(result["output"]) == 1
    feature_array = result["output"][0]
    # After transpose: shape is (T, n_mfcc) — axis 1 is the coefficient dimension
    assert feature_array.data.shape[1] == n_mfcc


# ── Req 9.7: ZCR shape invariant ─────────────────────────────────────────────

@given(n=st.integers(min_value=4000, max_value=32000))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_zcr_shape_invariant(installed_cls, make_audio_sample, n):
    """Req 9.7 — FeatureArray.data.shape[1] == 1 for feature_type='zcr'.

    The node transposes librosa's (1, T) output to (T, 1), so the feature
    dimension is axis 1.

    **Validates: Requirement 9.7**
    """
    node = installed_cls(config={"feature_type": "zcr"}, seed=0)
    sample = make_audio_sample(sr=16000, n=n)
    result = node.process({"input": [sample]})
    assert len(result["output"]) == 1
    feature_array = result["output"][0]
    # After transpose: shape is (T, 1) — axis 1 is the feature dimension
    assert feature_array.data.shape[1] == 1
