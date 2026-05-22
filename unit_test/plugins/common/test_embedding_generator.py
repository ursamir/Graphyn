# unit_test/plugins/common/test_embedding_generator.py
"""Tests for the embedding_generator plugin.

Covers:
  - Registration (Req 8.10)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.5: embedding dimension consistency invariant
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/embedding_generator/"
NODE_TYPE = "embedding_generator"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("embedding_generator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.10 — embedding_generator registers in a fresh registry."""
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
    node = installed_cls(config={"model": "wav2vec2"}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke(installed_cls, make_audio_sample):
    """Smoke test: EmbeddingGeneratorNode.process() with wav2vec2 model."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    node = installed_cls(config={"model": "wav2vec2", "normalize": True}, seed=0)
    sample = make_audio_sample(sr=16000, n=16000)
    result = node.process({"input": [sample]})
    assert "output" in result
    assert len(result["output"]) == 1


# ── Req 10.5: embedding dimension consistency ─────────────────────────────────

def test_embedding_dimension_consistency(installed_cls, make_audio_sample):
    """Req 10.5 — all embeddings from the same model have the same shape.

    **Validates: Requirement 10.5**
    """
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    node = installed_cls(config={"model": "wav2vec2", "normalize": True}, seed=0)

    # Create multiple samples with different lengths
    samples = [
        make_audio_sample(sr=16000, n=8000),
        make_audio_sample(sr=16000, n=16000),
        make_audio_sample(sr=16000, n=24000),
    ]

    result = node.process({"input": samples})
    assert "output" in result
    embeddings = result["output"]
    assert len(embeddings) == 3

    # All embeddings should have the same shape
    shapes = [emb.embedding.shape for emb in embeddings]
    assert len(set(shapes)) == 1, (
        f"All embeddings should have the same shape, got: {shapes}"
    )


def test_embedding_is_normalized(installed_cls, make_audio_sample):
    """With normalize=True, embedding L2 norm should be ~1.0."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    node = installed_cls(config={"model": "wav2vec2", "normalize": True}, seed=0)
    sample = make_audio_sample(sr=16000, n=16000)
    result = node.process({"input": [sample]})

    emb = result["output"][0].embedding
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-4, f"Normalized embedding should have norm ~1.0, got {norm}"
