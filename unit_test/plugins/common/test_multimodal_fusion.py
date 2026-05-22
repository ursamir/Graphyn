# unit_test/plugins/common/test_multimodal_fusion.py
"""Tests for the multimodal_fusion plugin.

Covers:
  - Registration (Req 8.11)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.6: output existence with concat strategy
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/multimodal_fusion/"
NODE_TYPE = "multimodal_fusion"

# Also install embedding_generator so EmbeddingVector type is available
EMBEDDING_SOURCE = "PluginPackage/Common/embedding_generator/"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_embedding_vector(dim: int = 768, label: str = "test"):
    """Return a real EmbeddingVector for testing."""
    try:
        from embedding_generator.types import EmbeddingVector  # type: ignore
    except ImportError:
        from PluginPackage.Common.embedding_generator.types import EmbeddingVector  # type: ignore

    rng = np.random.default_rng(42)
    emb = rng.standard_normal(dim).astype(np.float32)
    emb /= np.linalg.norm(emb)
    return EmbeddingVector(
        embedding=emb,
        source_path="/fake/audio.wav",
        label=label,
        embedding_model="wav2vec2",
        pooling="mean",
    )


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("multimodal_fusion_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    # Install embedding_generator first so EmbeddingVector type is registered
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(EMBEDDING_SOURCE)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.11 — multimodal_fusion registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(EMBEDDING_SOURCE)
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

def test_process_smoke_audio_only(installed_cls):
    """Smoke test: MultimodalFusionNode with audio-only input."""
    audio_vecs = [_make_embedding_vector(dim=768)]
    node = installed_cls(
        config={"fusion_type": "concat", "audio_dim": 768, "output_dim": 512},
        seed=0,
    )
    result = node.process({"audio": audio_vecs})
    assert "output" in result
    assert len(result["output"]) == 1


# ── Req 10.6: output existence with concat strategy ──────────────────────────

def test_concat_output_exists(installed_cls):
    """Req 10.6 — concat fusion produces output embedding for audio + text inputs.

    **Validates: Requirement 10.6**
    """
    audio_dim = 768
    text_dim = 512

    audio_vecs = [_make_embedding_vector(dim=audio_dim)]
    text_vecs = [_make_embedding_vector(dim=text_dim)]

    node = installed_cls(
        config={
            "fusion_type": "concat",
            "audio_dim": audio_dim,
            "text_dim": text_dim,
            "output_dim": 256,
        },
        seed=0,
    )
    result = node.process({"audio": audio_vecs, "text": text_vecs})
    assert "output" in result
    assert len(result["output"]) >= 1, "concat fusion should produce at least one output"


def test_concat_output_shape(installed_cls):
    """Concat fusion output embedding should have the configured output_dim."""
    audio_dim = 768
    text_dim = 512
    output_dim = 256

    audio_vecs = [_make_embedding_vector(dim=audio_dim)]
    text_vecs = [_make_embedding_vector(dim=text_dim)]

    node = installed_cls(
        config={
            "fusion_type": "concat",
            "audio_dim": audio_dim,
            "text_dim": text_dim,
            "output_dim": output_dim,
        },
        seed=0,
    )
    result = node.process({"audio": audio_vecs, "text": text_vecs})
    output = result["output"][0]
    emb = getattr(output, "embedding", output)
    assert emb.shape == (output_dim,), (
        f"Expected output shape ({output_dim},), got {emb.shape}"
    )


def test_attention_fusion_output_exists(installed_cls):
    """Attention fusion also produces output."""
    audio_vecs = [_make_embedding_vector(dim=768)]
    text_vecs = [_make_embedding_vector(dim=768)]

    node = installed_cls(
        config={"fusion_type": "attention", "audio_dim": 768, "output_dim": 512},
        seed=0,
    )
    result = node.process({"audio": audio_vecs, "text": text_vecs})
    assert "output" in result
    assert len(result["output"]) == 1


def test_empty_audio_returns_empty(installed_cls):
    """Empty audio input returns empty output list."""
    node = installed_cls(config={"fusion_type": "concat"}, seed=0)
    result = node.process({"audio": []})
    assert result["output"] == []
