# unit_test/core/test_property_based.py
"""All 8 Hypothesis property-based tests from Req 16.

Each test uses @settings(max_examples=100).
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.nodes.compat import CompatibilityChecker
from app.core.nodes.retry import RetryPolicy
from app.core.pipeline_cache import PipelineCache


# ── 1. Cache key determinism (Req 16 criterion 1) ────────────────────────────

@given(
    node_type=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"),
        min_size=1,
        max_size=30,
    ),
    config=st.dictionaries(
        keys=st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz_"),
        values=st.one_of(
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(max_size=20),
        ),
        max_size=5,
    ),
    input_hash=st.text(min_size=1, max_size=64, alphabet="0123456789abcdef"),
)
@settings(max_examples=100)
def test_cache_key_determinism(node_type, config, input_hash):
    """Req 16.1 — PipelineCache.key() returns same value for same inputs."""
    cache = PipelineCache()
    k1 = cache.key(node_type, config, input_hash)
    k2 = cache.key(node_type, config, input_hash)
    assert k1 == k2
    assert len(k1) == 64  # SHA-256 hex


# ── 2. IR idempotent round-trip (Req 16 criterion 2) ─────────────────────────

_valid_id = st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,15}", fullmatch=True)
_valid_node_type = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)
_valid_name = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip())


@st.composite
def _valid_graph_ir(draw):
    from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
    n = draw(st.integers(min_value=1, max_value=5))
    ids = draw(st.lists(_valid_id, min_size=n, max_size=n, unique=True))
    types = draw(st.lists(_valid_node_type, min_size=n, max_size=n))
    nodes = [IRNode(id=ids[i], node_type=types[i]) for i in range(n)]
    edges = [
        IREdge(src_id=ids[i], src_port="output", dst_id=ids[i + 1], dst_port="input")
        for i in range(n - 1)
    ]
    name = draw(_valid_name)
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    return GraphIR(
        schema_version="1.1",
        metadata=IRMetadata(name=name, seed=seed),
        nodes=nodes,
        edges=edges,
    )


@given(graph=_valid_graph_ir())
@settings(max_examples=100)
def test_ir_idempotent_round_trip(graph):
    """Req 16.2 — load_ir(dump_ir(graph)) == graph for all valid GraphIR objects."""
    from app.core.ir.loader import dump_ir, load_ir
    restored = load_ir(dump_ir(graph))
    assert restored == graph


# ── 3. Retry monotonicity (Req 16 criterion 3) ───────────────────────────────

@given(
    backoff_s=st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
    multiplier=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    attempt=st.integers(min_value=1, max_value=9),
)
@settings(max_examples=100)
def test_retry_monotonicity(backoff_s, multiplier, attempt):
    """Req 16.3 — wait_before_attempt(n) >= wait_before_attempt(n-1) for all valid params."""
    p = RetryPolicy(max_attempts=10, backoff_seconds=backoff_s, backoff_multiplier=multiplier)
    assert p.wait_before_attempt(attempt) >= p.wait_before_attempt(attempt - 1)


# ── 4. NodeConfig round-trip (Req 16 criterion 4) ────────────────────────────

@given(
    target_sr=st.sampled_from([8000, 16000, 22050, 44100]),
    mono=st.booleans(),
    normalize=st.booleans(),
)
@settings(max_examples=100)
def test_node_config_round_trip(target_sr, mono, normalize):
    """Req 16.4 — Config.model_validate(config.model_dump()) == config for valid configs."""
    from app.core.plugins.manager import PluginManager
    from app.core.nodes.registry import NodeRegistry
    import tempfile, pathlib

    # Install audio_conditioner to get its Config class
    with tempfile.TemporaryDirectory() as tmp:
        reg = NodeRegistry()
        mgr = PluginManager(registry=reg)
        mgr._plugins_dir = tmp
        mgr.install("PluginPackage/Audio/audio_conditioner/")
        cls = reg.get_class("audio_conditioner")

    config = cls.Config(target_sample_rate=target_sr, mono=mono, normalize=normalize)
    dumped = config.model_dump()
    restored = cls.Config.model_validate(dumped)
    assert restored.target_sample_rate == config.target_sample_rate
    assert restored.mono == config.mono
    assert restored.normalize == config.normalize


# ── 5. Valid manifest acceptance (Req 16 criterion 5) ────────────────────────

_slug = st.from_regex(r"[a-z][a-z0-9_-]{0,30}", fullmatch=True)
_version = st.builds(
    lambda a, b, c: f"{a}.{b}.{c}",
    a=st.integers(min_value=0, max_value=99),
    b=st.integers(min_value=0, max_value=99),
    c=st.integers(min_value=0, max_value=99),
)
_entry_points = st.lists(
    st.from_regex(r"[a-z][a-z0-9_]{0,20}\.py", fullmatch=True),
    min_size=1,
    max_size=5,
)


@given(
    name=_slug,
    version=_version,
    description=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
    author=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
    entry_points=_entry_points,
)
@settings(max_examples=100)
def test_valid_manifest_acceptance(name, version, description, author, entry_points):
    """Req 16.5 — valid PluginManifest dicts always construct without raising."""
    from app.core.plugins.manifest import PluginManifest
    m = PluginManifest.model_validate({
        "name": name,
        "version": version,
        "description": description,
        "author": author,
        "platform_version": ">=0.0",
        "entry_points": entry_points,
    })
    assert m.name == name
    assert m.version == version


# ── 6. AudioConditionerNode normalization bound (Req 16 criterion 6) ─────────

@given(n=st.integers(min_value=4000, max_value=32000))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_audio_conditioner_normalization_bound(n, make_audio_sample):
    """Req 16.6 — max(abs(output.data)) <= 1.0 + 1e-5 when normalize=True, peak, limiter=True."""
    from app.core.plugins.manager import PluginManager
    from app.core.nodes.registry import NodeRegistry
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        reg = NodeRegistry()
        mgr = PluginManager(registry=reg)
        mgr._plugins_dir = tmp
        mgr.install("PluginPackage/Audio/audio_conditioner/")
        cls = reg.get_class("audio_conditioner")

    node = cls(config={"normalize": True, "normalize_method": "peak", "limiter": True, "trim_silence": False}, seed=0)
    sample = make_audio_sample(sr=16000, n=n)
    result = node.process({"input": [sample]})
    if result["output"]:
        out_data = result["output"][0].data
        assert float(np.max(np.abs(out_data))) <= 1.0 + 1e-5


# ── 7. PipelineGraph completeness (Req 16 criterion 7) ───────────────────────

@given(n_nodes=st.integers(min_value=1, max_value=6))
@settings(max_examples=100)
def test_pipeline_graph_completeness(n_nodes):
    """Req 16.7 — execution_order contains every node exactly once for valid acyclic graphs."""
    from app.core.planner import EdgeSpec, NodeSpec, PipelineConfig, PipelineGraph

    nodes = [
        NodeSpec(node_id=f"n{i}", node_type="audio_conditioner", config={})
        for i in range(n_nodes)
    ]
    edges = [
        EdgeSpec(src_id=f"n{i}", src_port="output", dst_id=f"n{i+1}", dst_port="input")
        for i in range(n_nodes - 1)
    ]
    cfg = PipelineConfig(seed=0, nodes=nodes, edges=edges)
    graph = PipelineGraph(cfg)
    order = graph.execution_order
    assert len(order) == n_nodes
    assert set(order) == {f"n{i}" for i in range(n_nodes)}


# ── 8. CompatibilityChecker reflexivity (Req 16 criterion 8) ─────────────────

@given(use_list=st.booleans())
@settings(max_examples=100)
def test_compatibility_checker_reflexivity(use_list):
    """Req 16.8 — are_compatible(T, T) returns True for any non-None type T."""
    from app.models.audio_sample import AudioSample
    from app.models.feature_array import FeatureArray
    from app.core.nodes.ports import PortDataType

    types = [AudioSample, FeatureArray, PortDataType, list, str, int]
    for T in types:
        assert CompatibilityChecker.are_compatible(T, T) is True, (
            f"are_compatible({T}, {T}) should be True"
        )
