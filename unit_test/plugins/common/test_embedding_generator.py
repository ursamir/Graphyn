# unit_test/plugins/common/test_embedding_generator.py
"""Tests for the embedding_generator plugin.

Covers:
  - Registration (Req 8.10)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.5: embedding dimension consistency invariant
"""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

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
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.10 — embedding_generator registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
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

@pytest.mark.heavy
def test_process_smoke(installed_cls, make_audio_sample):
    """Smoke test: EmbeddingGeneratorNode.process() with wav2vec2 model."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    node = installed_cls(config={"model": "wav2vec2", "normalize": True}, seed=0)
    node.setup()  # NodeExecutor calls setup() before process().
    sample = make_audio_sample(sr=16000, n=16000)
    result = node.process({"input": [sample]})
    assert "output" in result
    assert len(result["output"]) == 1


# ── Req 10.5: embedding dimension consistency ─────────────────────────────────

@pytest.mark.heavy
def test_embedding_dimension_consistency(installed_cls, make_audio_sample):
    """Req 10.5 — all embeddings from the same model have the same shape.

    **Validates: Requirement 10.5**
    """
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    node = installed_cls(config={"model": "wav2vec2", "normalize": True}, seed=0)
    node.setup()  # NodeExecutor calls setup() before process().

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


@pytest.mark.heavy
def test_embedding_is_normalized(installed_cls, make_audio_sample):
    """With normalize=True, embedding L2 norm should be ~1.0."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    node = installed_cls(config={"model": "wav2vec2", "normalize": True}, seed=0)
    node.setup()  # NodeExecutor calls setup() before process().
    sample = make_audio_sample(sr=16000, n=16000)
    result = node.process({"input": [sample]})

    emb = result["output"][0].embedding
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-4, f"Normalized embedding should have norm ~1.0, got {norm}"


# ── v2 schema: dead options removed ───────────────────────────────────────────

def test_schema_has_no_dead_options(installed_cls):
    fields = installed_cls.Config.model_fields
    # `backend` was never read; openl3 cannot install on Python 3.12 (kapre/TF pins).
    assert "backend" not in fields
    from typing import get_args
    models = set(get_args(fields["model"].annotation))
    assert models == {"wav2vec2", "hubert", "clap", "xvector", "ecapa", "yamnet"}


def test_empty_audio_is_an_error(installed_cls):
    from app.models.audio_sample import AudioSample

    node = installed_cls(config={"model": "xvector"}, seed=0)
    with pytest.raises(ValueError, match="empty audio"):
        node.process({"input": [AudioSample(path="/e.wav", sample_rate=16000, data=np.zeros(0, np.float32))]})


def test_pooling_modes(installed_cls):
    hidden = np.arange(12, dtype=np.float32).reshape(3, 4)
    for pooling, expect in [("mean", hidden.mean(0)), ("max", hidden[2]), ("first", hidden[0]),
                            ("last", hidden[2]), ("none", hidden.reshape(-1))]:
        node = installed_cls(config={"pooling": pooling}, seed=0)
        assert np.allclose(node._pool(hidden), expect)


@pytest.mark.heavy
@pytest.mark.parametrize("model,dim", [("clap", 512), ("xvector", 512), ("ecapa", 192)])
def test_projection_models(installed_cls, make_audio_sample, model, dim):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("speechbrain")
    node = installed_cls(config={"model": model}, seed=0)
    node.setup()
    out = node.process({"input": [make_audio_sample(sr=16000, n=16000)]})["output"]
    assert out[0].embedding.shape == (dim,)
    assert out[0].pooling == "projection"
    assert abs(float(np.linalg.norm(out[0].embedding)) - 1.0) < 1e-4
