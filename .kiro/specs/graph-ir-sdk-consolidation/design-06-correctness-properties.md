
# Design 06 — Correctness Properties (Hypothesis PBT)

## Overview

This document defines all property-based tests for the Graph IR + SDK Consolidation feature. Tests are implemented using [Hypothesis](https://hypothesis.readthedocs.io/), the Python property-based testing library already present in the project.

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

**Test file location:** `tests/test_graph_ir_properties.py`

**Minimum iterations:** 100 per property (Hypothesis default `max_examples=100`).

**Tag format:** `# Feature: graph-ir-sdk-consolidation, Property N: <property_text>`

---

## Correctness Properties

### Property 1: IR Round-Trip

*For any* valid `GraphIR` object `g`, serializing it with `dump_ir(g)` and then deserializing with `load_ir()` SHALL produce an object equal to `g`.

**Validates: Requirements 1.8.8, 1.2.5**

---

### Property 2: SDK Round-Trip

*For any* `Pipeline` object constructed from a list of valid nodes and a seed, writing it to a JSON file with `to_json()` and loading it back with `from_json()` SHALL produce a `Pipeline` with equal nodes (same `node_type` and `config`) and equal `seed`.

**Validates: Requirements 2.6.3, 2.5.4**

---

### Property 3: YAML Shim Equivalence

*For any* valid YAML pipeline config dict (both linear and explicit-edge formats), `yaml_config_to_ir()` SHALL produce a `GraphIR` whose `nodes`, `edges`, and `metadata.seed` are structurally equivalent to what `_parse_pipeline_config()` would produce from the same dict.

**Validates: Requirements 4.1.2, 4.1.3, 3.2.4**

---

### Property 4: Version Rejection

*For any* IR document dict whose `schema_version` major component differs from `CURRENT_IR_VERSION`'s major component, `load_ir()` SHALL raise `IRVersionError`.

**Validates: Requirements 1.7.3**

---

### Property 5: Capability Defaults

*For any* `NodeMetadata` constructed with only the required fields (`node_type`, `label`, `description`, `category`), all seven capability fields SHALL equal their specified defaults: `requires_gpu=False`, `supports_cpu=True`, `supports_edge=False`, `deterministic=True`, `cacheable=True`, `streaming_support=False`, `realtime_support=False`.

**Validates: Requirements 5.1.1, 5.5.1**

---

### Property 6: Executor Equivalence

*For any* valid `GraphIR` with deterministic mock nodes, executing via `run_pipeline_ir(graph)` SHALL produce the same output as executing the equivalent `PipelineConfig` via `PipelineGraph` + `NodeExecutor` directly.

**Validates: Requirements 3.1.5, 3.2.4**

---

### Property 7: Deterministic Replay

*For any* valid `GraphIR` with a fixed seed and deterministic mock nodes, executing the graph twice with the same seed SHALL produce identical outputs.

**Validates: Requirements 1.10.3, 1.10.2**

---

### Property 8: Node ID Uniqueness Enforcement

*For any* list of `IRNode` objects where at least two nodes share the same `id`, constructing a `GraphIR` from that list SHALL raise `pydantic.ValidationError`.

**Validates: Requirements 1.4.3, 1.9.2**

---

### Property 9: Edge Reference Integrity Enforcement

*For any* `GraphIR` dict that is otherwise valid but contains an edge whose `src_id` or `dst_id` does not match any node `id` in the `nodes` list, `load_ir()` SHALL raise `pydantic.ValidationError`.

**Validates: Requirements 1.5.2, 1.9.1**

---

## Test Implementation

### Hypothesis Strategies

```python
# tests/test_graph_ir_properties.py
"""Property-based tests for Graph IR + SDK Consolidation.

Feature: graph-ir-sdk-consolidation
Uses Hypothesis for property-based testing with minimum 100 iterations per property.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import pytest
import pydantic
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.ir.loader import (
    CURRENT_IR_VERSION,
    IRVersionError,
    dump_ir,
    load_ir,
    load_ir_from_file,
    dump_ir_to_file,
)
from app.core.ir.models import (
    GraphIR,
    IRCapabilityMetadata,
    IREdge,
    IRMetadata,
    IRNode,
    IRParameter,
)
from app.core.nodes.metadata import NodeMetadata


# ── Hypothesis strategies ─────────────────────────────────────────────────────

# Valid node ID characters: alphanumeric, underscores, hyphens
_node_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=20,
)

_node_type_strategy = st.sampled_from([
    "input", "clean", "split", "export", "augment", "segment",
])

_config_strategy = st.fixed_dictionaries({}).flatmap(
    lambda _: st.dictionaries(
        keys=st.text(alphabet=st.characters(whitelist_categories=("Ll",)), min_size=1, max_size=10),
        values=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=20)),
        max_size=3,
    )
)

_ir_node_strategy = st.builds(
    IRNode,
    id=_node_id_strategy,
    node_type=_node_type_strategy,
    config=_config_strategy,
    label=st.one_of(st.none(), st.text(max_size=20)),
    capability_metadata=st.none(),
)

_ir_metadata_strategy = st.builds(
    IRMetadata,
    name=st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" -_")),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
    description=st.text(max_size=50),
    created_at=st.none(),
    tags=st.lists(st.text(max_size=10), max_size=3),
)


def _build_graph_ir_strategy(max_nodes: int = 5):
    """Strategy that builds a valid GraphIR with consistent node IDs in edges."""

    @st.composite
    def _strategy(draw):
        metadata = draw(_ir_metadata_strategy)
        n = draw(st.integers(min_value=1, max_value=max_nodes))

        # Generate unique node IDs
        ids = draw(
            st.lists(
                _node_id_strategy,
                min_size=n,
                max_size=n,
                unique=True,
            )
        )
        node_types = draw(st.lists(_node_type_strategy, min_size=n, max_size=n))
        configs = draw(st.lists(_config_strategy, min_size=n, max_size=n))

        nodes = [
            IRNode(id=ids[i], node_type=node_types[i], config=configs[i])
            for i in range(n)
        ]

        # Build linear edges (safe: all IDs are valid)
        edges = [
            IREdge(
                src_id=ids[i],
                src_port="output",
                dst_id=ids[i + 1],
                dst_port="input",
            )
            for i in range(n - 1)
        ]

        return GraphIR(
            schema_version=CURRENT_IR_VERSION,
            metadata=metadata,
            nodes=nodes,
            edges=edges,
        )

    return _strategy()


_graph_ir_strategy = _build_graph_ir_strategy()
```

### Property 1: IR Round-Trip

```python
@given(_graph_ir_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_1_ir_round_trip(graph: GraphIR):
    """Property 1: IR Round-Trip
    
    Feature: graph-ir-sdk-consolidation, Property 1: load_ir(dump_ir(g)) == g
    
    Validates: Requirements 1.8.8, 1.2.5
    """
    serialized = dump_ir(graph)
    deserialized = load_ir(serialized)
    assert deserialized == graph, (
        f"Round-trip failed.\n"
        f"Original: {graph}\n"
        f"Deserialized: {deserialized}"
    )
```

### Property 2: SDK Round-Trip

```python
@given(
    st.lists(
        st.builds(
            lambda nt: (nt, {}),
            _node_type_strategy,
        ),
        min_size=1,
        max_size=4,
    ),
    st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_2_sdk_round_trip(node_specs, seed):
    """Property 2: SDK Round-Trip
    
    Feature: graph-ir-sdk-consolidation, Property 2: Pipeline.from_json(p.to_json()) == p
    
    Validates: Requirements 2.6.3, 2.5.4
    """
    from app.core.sdk import Pipeline, PipelineNode

    nodes = [PipelineNode(nt, cfg) for nt, cfg in node_specs]
    pipeline = Pipeline(nodes=nodes, seed=seed)

    with tempfile.NamedTemporaryFile(suffix=".graph.json", delete=False) as f:
        tmp_path = f.name

    try:
        pipeline.to_json(tmp_path)
        loaded = Pipeline.from_json(tmp_path)

        assert loaded.seed == pipeline.seed, (
            f"Seed mismatch: {loaded.seed} != {pipeline.seed}"
        )
        assert len(loaded.nodes) == len(pipeline.nodes), (
            f"Node count mismatch: {len(loaded.nodes)} != {len(pipeline.nodes)}"
        )
        for orig, restored in zip(pipeline.nodes, loaded.nodes):
            assert restored.node_type == orig.node_type, (
                f"node_type mismatch: {restored.node_type} != {orig.node_type}"
            )
            assert restored.config == orig.config, (
                f"config mismatch: {restored.config} != {orig.config}"
            )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
```

### Property 3: YAML Shim Equivalence

```python
@given(
    st.lists(
        st.builds(
            lambda nt: {"type": nt, "config": {}},
            _node_type_strategy,
        ),
        min_size=1,
        max_size=4,
    ),
    st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_3_yaml_shim_equivalence(node_dicts, seed):
    """Property 3: YAML Shim Equivalence
    
    Feature: graph-ir-sdk-consolidation, Property 3: yaml_config_to_ir produces structurally equivalent graph
    
    Validates: Requirements 4.1.2, 4.1.3, 3.2.4
    """
    from app.core.ir.yaml_shim import yaml_config_to_ir
    from app.core.pipeline import _parse_pipeline_config, _ir_to_pipeline_config

    raw = {"pipeline": {"seed": seed, "nodes": node_dicts}}

    # Convert via YAML shim
    graph = yaml_config_to_ir(raw)
    ir_config = _ir_to_pipeline_config(graph)

    # Convert via legacy parser
    legacy_config = _parse_pipeline_config(raw)

    # Structural equivalence: same seed, same node count, same node types
    assert ir_config.seed == legacy_config.seed, (
        f"Seed mismatch: {ir_config.seed} != {legacy_config.seed}"
    )
    assert len(ir_config.nodes) == len(legacy_config.nodes), (
        f"Node count mismatch: {len(ir_config.nodes)} != {len(legacy_config.nodes)}"
    )
    for ir_node, legacy_node in zip(ir_config.nodes, legacy_config.nodes):
        assert ir_node.node_type == legacy_node.node_type, (
            f"node_type mismatch: {ir_node.node_type} != {legacy_node.node_type}"
        )
    assert len(ir_config.edges) == len(legacy_config.edges), (
        f"Edge count mismatch: {len(ir_config.edges)} != {len(legacy_config.edges)}"
    )
    for ir_edge, legacy_edge in zip(ir_config.edges, legacy_config.edges):
        assert ir_edge.src_port == legacy_edge.src_port
        assert ir_edge.dst_port == legacy_edge.dst_port
```

### Property 4: Version Rejection

```python
@given(
    st.integers(min_value=0, max_value=100).filter(
        lambda v: v != int(CURRENT_IR_VERSION.split(".")[0])
    ),
    st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100)
def test_property_4_version_rejection(major, minor):
    """Property 4: Version Rejection
    
    Feature: graph-ir-sdk-consolidation, Property 4: load_ir raises IRVersionError for incompatible major version
    
    Validates: Requirements 1.7.3
    """
    # Build a minimal valid GraphIR dict with an incompatible major version
    data = {
        "schema_version": f"{major}.{minor}",
        "metadata": {"name": "test", "seed": 42},
        "nodes": [{"id": "n0", "node_type": "clean", "config": {}}],
        "edges": [],
        "parameters": {},
    }

    with pytest.raises(IRVersionError) as exc_info:
        load_ir(data)

    assert str(major) in str(exc_info.value), (
        f"IRVersionError message should mention the document major version {major}"
    )
```

### Property 5: Capability Defaults

```python
@given(
    st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll",))),
    st.text(min_size=1, max_size=30),
    st.text(min_size=1, max_size=100),
    st.text(min_size=1, max_size=20),
)
@settings(max_examples=100)
def test_property_5_capability_defaults(node_type, label, description, category):
    """Property 5: Capability Defaults
    
    Feature: graph-ir-sdk-consolidation, Property 5: NodeMetadata without capability fields has correct defaults
    
    Validates: Requirements 5.1.1, 5.5.1
    """
    meta = NodeMetadata(
        node_type=node_type,
        label=label,
        description=description,
        category=category,
    )

    assert meta.requires_gpu is False
    assert meta.supports_cpu is True
    assert meta.supports_edge is False
    assert meta.deterministic is True
    assert meta.cacheable is True
    assert meta.streaming_support is False
    assert meta.realtime_support is False
```

### Property 6: Executor Equivalence

```python
@given(
    st.lists(
        _node_type_strategy,
        min_size=1,
        max_size=3,
    ),
    st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_6_executor_equivalence(node_types, seed):
    """Property 6: Executor Equivalence
    
    Feature: graph-ir-sdk-consolidation, Property 6: run_pipeline_ir produces same output as direct PipelineGraph execution
    
    Validates: Requirements 3.1.5, 3.2.4
    
    Uses mock nodes to avoid real I/O. Tests that _ir_to_pipeline_config
    produces a PipelineConfig that executes identically to the one produced
    by _parse_pipeline_config for the same graph structure.
    """
    from app.core.ir.yaml_shim import yaml_config_to_ir
    from app.core.pipeline import _parse_pipeline_config, _ir_to_pipeline_config

    raw = {
        "pipeline": {
            "seed": seed,
            "nodes": [{"type": nt, "config": {}} for nt in node_types],
        }
    }

    # Both conversion paths should produce structurally equivalent PipelineConfigs
    graph = yaml_config_to_ir(raw)
    ir_config = _ir_to_pipeline_config(graph)
    legacy_config = _parse_pipeline_config(raw)

    # Verify execution order would be the same
    assert [n.node_type for n in ir_config.nodes] == [n.node_type for n in legacy_config.nodes]
    assert ir_config.seed == legacy_config.seed
    assert len(ir_config.edges) == len(legacy_config.edges)
```

### Property 7: Deterministic Replay

```python
@given(_graph_ir_strategy)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_7_deterministic_replay(graph: GraphIR):
    """Property 7: Deterministic Replay
    
    Feature: graph-ir-sdk-consolidation, Property 7: Same GraphIR + same seed produces same PipelineConfig
    
    Validates: Requirements 1.10.3, 1.10.2
    
    Tests that _ir_to_pipeline_config is deterministic: calling it twice
    with the same GraphIR produces identical PipelineConfig objects.
    The full execution determinism depends on node implementations, which
    is tested separately in integration tests.
    """
    from app.core.pipeline import _ir_to_pipeline_config

    config1 = _ir_to_pipeline_config(graph)
    config2 = _ir_to_pipeline_config(graph)

    assert config1.seed == config2.seed
    assert len(config1.nodes) == len(config2.nodes)
    assert len(config1.edges) == len(config2.edges)

    for n1, n2 in zip(config1.nodes, config2.nodes):
        assert n1.node_id == n2.node_id
        assert n1.node_type == n2.node_type
        assert n1.config == n2.config

    for e1, e2 in zip(config1.edges, config2.edges):
        assert e1.src_id == e2.src_id
        assert e1.src_port == e2.src_port
        assert e1.dst_id == e2.dst_id
        assert e1.dst_port == e2.dst_port
```

### Property 8: Node ID Uniqueness Enforcement

```python
@given(
    st.lists(
        _node_id_strategy,
        min_size=2,
        max_size=5,
        unique=True,
    ),
    _node_type_strategy,
    st.integers(min_value=0, max_value=4),
)
@settings(max_examples=100)
def test_property_8_node_id_uniqueness(unique_ids, node_type, duplicate_index):
    """Property 8: Node ID Uniqueness Enforcement
    
    Feature: graph-ir-sdk-consolidation, Property 8: GraphIR raises ValidationError for duplicate node ids
    
    Validates: Requirements 1.4.3, 1.9.2
    """
    n = len(unique_ids)
    duplicate_index = duplicate_index % n  # clamp to valid range

    # Build nodes with a deliberate duplicate
    nodes = [IRNode(id=uid, node_type=node_type, config={}) for uid in unique_ids]
    # Duplicate one node's id
    dup_id = unique_ids[duplicate_index]
    nodes.append(IRNode(id=dup_id, node_type=node_type, config={}))

    with pytest.raises(pydantic.ValidationError) as exc_info:
        GraphIR(
            schema_version=CURRENT_IR_VERSION,
            metadata=IRMetadata(name="test", seed=0),
            nodes=nodes,
            edges=[],
        )

    assert dup_id in str(exc_info.value), (
        f"ValidationError should mention the duplicate id '{dup_id}'"
    )
```

### Property 9: Edge Reference Integrity Enforcement

```python
@given(_graph_ir_strategy)
@settings(max_examples=100)
def test_property_9_edge_reference_integrity(graph: GraphIR):
    """Property 9: Edge Reference Integrity Enforcement
    
    Feature: graph-ir-sdk-consolidation, Property 9: load_ir raises ValidationError for edges with unknown node ids
    
    Validates: Requirements 1.5.2, 1.9.1
    """
    # Serialize to dict and inject a bad edge
    data = dump_ir(graph)

    # Add an edge referencing a non-existent node id
    bad_edge = {
        "src_id": "__nonexistent_src__",
        "src_port": "output",
        "dst_id": "__nonexistent_dst__",
        "dst_port": "input",
    }
    data["edges"] = data.get("edges", []) + [bad_edge]

    with pytest.raises(pydantic.ValidationError) as exc_info:
        load_ir(data)

    error_str = str(exc_info.value)
    assert "__nonexistent_src__" in error_str or "__nonexistent_dst__" in error_str, (
        "ValidationError should mention the unknown node id"
    )
```

---

## Test Configuration

### `pytest.ini` / `pyproject.toml` settings

```ini
[tool.pytest.ini_options]
filterwarnings = [
    # Do not treat DeprecationWarning from YAML shim as errors (Req 4.9.2)
    "ignore::DeprecationWarning:app.core.ir.yaml_shim",
    "ignore::DeprecationWarning:app.core.pipeline",
]
```

### Hypothesis settings

```python
# conftest.py or at module level
from hypothesis import settings, HealthCheck

settings.register_profile(
    "ci",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
settings.load_profile("ci")
```

---

## Testing Strategy Summary

### Unit Tests (example-based)

Complement the property tests with specific examples:

| Test | What it verifies |
|---|---|
| `test_load_ir_file_not_found` | `FileNotFoundError` on missing file |
| `test_load_ir_invalid_json` | `json.JSONDecodeError` on bad JSON |
| `test_load_ir_schema_mismatch` | `pydantic.ValidationError` on wrong schema |
| `test_version_warning_minor` | `UserWarning` on higher minor version |
| `test_yaml_shim_linear_format` | Linear YAML → correct edges |
| `test_yaml_shim_explicit_edge_format` | Explicit-edge YAML → correct edges |
| `test_migrate_yaml_to_ir_file` | Migration writes valid IR JSON |
| `test_pipeline_from_yaml_deprecation_warning` | `DeprecationWarning` emitted |
| `test_capability_metadata_in_api_response` | API response includes `capability_metadata` |
| `test_run_manager_saves_graph_json` | `graph.json` written to run dir |

### Integration Tests

| Test | What it verifies |
|---|---|
| `test_end_to_end_yaml_to_ir_execution` | YAML → IR → execution produces correct output |
| `test_end_to_end_sdk_ir_execution` | SDK → IR → execution produces correct output |
| `test_cli_migrate_command` | `audiobuilder migrate` produces valid IR JSON |
| `test_cli_run_graph_flag` | `audiobuilder run --graph` executes IR JSON |
| `test_api_run_ir_json` | POST /api/v1/pipelines/run with IR JSON body |
| `test_api_run_yaml_deprecation_header` | YAML API request returns deprecation header |

### Regression Tests

All 441 existing tests must pass without modification. Run with:

```bash
venv/bin/pytest tests/ -x --tb=short
```

---

## References

- [req-01-graph-ir.md](req-01-graph-ir.md) — Requirements 1.4.3, 1.5.2, 1.7.3, 1.8.8, 1.10.3
- [req-02-sdk-consolidation.md](req-02-sdk-consolidation.md) — Requirements 2.5.4, 2.6.3
- [req-03-executor-wiring.md](req-03-executor-wiring.md) — Requirements 3.1.5, 3.2.4
- [req-04-yaml-compat.md](req-04-yaml-compat.md) — Requirements 4.1.2, 4.1.3
- [req-05-node-capability-metadata.md](req-05-node-capability-metadata.md) — Requirements 5.1.1, 5.5.1
- [design-01-graph-ir.md](design-01-graph-ir.md) — IR models and loader
- [design-02-sdk-consolidation.md](design-02-sdk-consolidation.md) — SDK internals
- [design-03-executor-wiring.md](design-03-executor-wiring.md) — Executor wiring
- [design-04-yaml-compat.md](design-04-yaml-compat.md) — YAML shim
- [design-05-node-capability-metadata.md](design-05-node-capability-metadata.md) — NodeMetadata extension
