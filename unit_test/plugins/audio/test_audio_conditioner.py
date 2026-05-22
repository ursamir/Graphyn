# unit_test/plugins/audio/test_audio_conditioner.py
"""Tests for the audio_conditioner plugin.

Covers:
  - Registration (Req 7.1)
  - Metadata (Req 7.1)
  - Construction and smoke process
  - Req 9 criteria 1–5: sample_rate invariant, mono invariant,
    normalization bound, output count, metadata propagation
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/audio_conditioner/"
NODE_TYPE = "audio_conditioner"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("audio_conditioner_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.1 — audio_conditioner registers in a fresh registry."""
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

def test_process_smoke(installed_cls, make_audio_sample):
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


# ── Req 9.1: sample_rate invariant ───────────────────────────────────────────

@given(
    target_sr=st.sampled_from([8000, 16000, 22050, 44100]),
    n=st.integers(min_value=4000, max_value=32000),
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_sample_rate_invariant(installed_cls, make_audio_sample, target_sr, n):
    """Req 9.1 — output sample_rate equals target_sample_rate for all valid inputs.

    **Validates: Requirement 9.1**
    """
    node = installed_cls(
        config={"target_sample_rate": target_sr, "trim_silence": False},
        seed=0,
    )
    sample = make_audio_sample(sr=16000, n=n)
    result = node.process({"input": [sample]})
    assert len(result["output"]) == 1
    assert result["output"][0].sample_rate == target_sr


# ── Req 9.2: mono invariant ───────────────────────────────────────────────────

def test_mono_invariant(installed_cls, make_audio_sample):
    """Req 9.2 — output data.ndim == 1 when mono=True.

    **Validates: Requirement 9.2**
    """
    node = installed_cls(config={"mono": True, "trim_silence": False}, seed=0)
    sample = make_audio_sample(sr=16000, n=4000)
    result = node.process({"input": [sample]})
    assert len(result["output"]) == 1
    assert result["output"][0].data.ndim == 1


# ── Req 9.3: normalization bound ─────────────────────────────────────────────

@given(n=st.integers(min_value=4000, max_value=32000))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_normalization_bound(installed_cls, make_audio_sample, n):
    """Req 9.3 — peak normalization with limiter keeps max(abs(data)) <= 1.0 + 1e-5.

    **Validates: Requirement 9.3**
    """
    node = installed_cls(
        config={
            "normalize": True,
            "normalize_method": "peak",
            "limiter": True,
            "trim_silence": False,
        },
        seed=0,
    )
    sample = make_audio_sample(sr=16000, n=n)
    result = node.process({"input": [sample]})
    if result["output"]:
        out_data = result["output"][0].data
        assert float(np.max(np.abs(out_data))) <= 1.0 + 1e-5


# ── Req 9.4: output count invariant ──────────────────────────────────────────

@given(n_samples=st.integers(min_value=1, max_value=8))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_output_count_invariant(installed_cls, make_audio_sample, n_samples):
    """Req 9.4 — output count <= N when skip_clipped=False.

    **Validates: Requirement 9.4**
    """
    node = installed_cls(config={"skip_clipped": False, "trim_silence": False}, seed=0)
    samples = [make_audio_sample(sr=16000, n=4000) for _ in range(n_samples)]
    result = node.process({"input": samples})
    assert len(result["output"]) <= n_samples


# ── Req 9.5: metadata propagation ────────────────────────────────────────────

def test_metadata_propagation_compress(installed_cls, make_audio_sample):
    """Req 9.5 — compress=True adds 'conditioning' key with compress=True to metadata.

    **Validates: Requirement 9.5**
    """
    node = installed_cls(
        config={"compress": True, "trim_silence": False},
        seed=0,
    )
    sample = make_audio_sample(sr=16000, n=4000)
    result = node.process({"input": [sample]})
    assert len(result["output"]) == 1
    meta = result["output"][0].metadata
    assert "conditioning" in meta
    assert meta["conditioning"]["compress"] is True
