# Design 04 — Serialisation, Pipeline DAG Executor, and Correctness Properties

← [Back to design.md](design.md) | ← [Back to requirements](req-04-serialisation.md)

---

## 1. Round-Trip Serialisation of `NodeMetadata`

`NodeRegistry.to_json()` and `NodeRegistry.from_json()` are defined in `design-02-registration.md § 3`. The key design decision is that `data_type` fields in port dicts are stored as fully-qualified name strings (not Python type objects), making the JSON fully portable.

### Serialisation flow

```
NodeMetadata (in-memory)
    │
    │  m.model_dump(mode="json")
    ▼
{
  "node_type": "clean",
  "label": "Clean",
  "input_ports": {
    "input": {
      "name": "input",
      "data_type": "app.models.audio_sample.AudioSample",  ← fqn string
      "cardinality": "single",
      "required": true,
      "description": ""
    }
  },
  ...
}
    │
    │  json.dumps(...)
    ▼
JSON string (API response / file)
    │
    │  json.loads(...)  +  NodeMetadata.model_validate(item)
    ▼
NodeMetadata (reconstructed)
```

The `data_type` field in the reconstructed metadata remains a string. To get the Python type back, callers use `registry.type_catalogue.resolve(data_type_string)`.

---

## 2. Config Schema Export

```python
# Already on NodeRegistry (design-02-registration.md § 3):

def get_config_schema(self, node_type: str) -> dict[str, Any]:
    node_class = self.get_class(node_type)
    return node_class.Config.model_json_schema()

def get_port_schema(self, node_type: str) -> dict[str, Any]:
    node_class = self.get_class(node_type)
    return node_class.port_schemas()
```

### Example output for `CleanNode`

```json
// get_config_schema("clean")
{
  "type": "object",
  "title": "CleanConfig",
  "properties": {
    "sample_rate": {
      "type": "integer",
      "default": 16000,
      "title": "Sample Rate"
    }
  }
}

// get_port_schema("clean")
{
  "inputs": {
    "input": {
      "type": "array",
      "items": {
        "$defs": { "AudioSample": { ... } },
        "$ref": "#/$defs/AudioSample"
      }
    }
  },
  "outputs": {
    "output": {
      "type": "array",
      "items": { "$ref": "#/$defs/AudioSample" }
    }
  }
}
```

---

## 3. Pipeline DAG Executor (`pipeline.py` Redesign)

The current `pipeline.py` uses a linear list. The redesign introduces `PipelineGraph` (a DAG) and `NodeExecutor` (per-node lifecycle driver, defined in design-03).

### 3.1 Data Structures

```python
# app/core/pipeline.py
from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
import yaml
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from app.core.nodes import registry as node_registry
from app.core.nodes.base import Node
from app.core.nodes.compat import CompatibilityChecker
from app.core.nodes.errors import PipelineGraphError
from app.core.nodes.observers import NodeObserver
from app.core.nodes.retry import RetryPolicy
from app.core.utils.hash import stable_hash

log = logging.getLogger(__name__)


@dataclass
class NodeSpec:
    """Specification for one node in a pipeline config."""
    node_id: str          # unique within the pipeline (e.g. "clean_0")
    node_type: str        # registry key (e.g. "clean")
    config: dict[str, Any]


@dataclass
class EdgeSpec:
    """A directed edge connecting one node's output port to another's input port."""
    src_id: str
    src_port: str
    dst_id: str
    dst_port: str


@dataclass
class PipelineConfig:
    """Parsed, validated pipeline configuration."""
    seed: int
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
```

### 3.2 `PipelineGraph` — Build and Validate

```python
class PipelineGraph:
    """Builds a validated DAG from a PipelineConfig.

    Responsibilities:
      - Instantiate Node objects from NodeSpecs
      - Validate all edges via CompatibilityChecker
      - Compute topological execution order (Kahn's algorithm)
      - Detect cycles
    """

    def __init__(
        self,
        config: PipelineConfig,
        observer: NodeObserver | None = None,
    ) -> None:
        self._config = config
        self._observer = observer
        self._nodes: dict[str, Node] = {}
        self._edges: list[EdgeSpec] = list(config.edges)
        self._topo_order: list[str] = []

        self._build()

    def _build(self) -> None:
        seed = self._config.seed

        # 1. Instantiate nodes
        for i, spec in enumerate(self._config.nodes):
            node_class = node_registry.get_class(spec.node_type)
            node_seed = stable_hash(seed, spec.node_type, i) % (2 ** 32)
            node_config = copy.deepcopy(spec.config)
            node = node_class(
                config=node_config,
                seed=node_seed,
                observer=self._observer,
            )
            self._nodes[spec.node_id] = node

        # 2. Validate edges
        for edge in self._edges:
            src_node = self._nodes.get(edge.src_id)
            dst_node = self._nodes.get(edge.dst_id)
            if src_node is None:
                raise PipelineGraphError(
                    f"Edge references unknown source node '{edge.src_id}'"
                )
            if dst_node is None:
                raise PipelineGraphError(
                    f"Edge references unknown destination node '{edge.dst_id}'"
                )
            CompatibilityChecker.check_connection(
                src_node, edge.src_port, dst_node, edge.dst_port
            )

        # 3. Topological sort (Kahn's algorithm)
        self._topo_order = self._topological_sort()

    def _topological_sort(self) -> list[str]:
        """Return node IDs in topological execution order.

        Raises PipelineGraphError if a cycle is detected.
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self._nodes}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for edge in self._edges:
            adjacency[edge.src_id].append(edge.dst_id)
            in_degree[edge.dst_id] += 1

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for successor in adjacency[nid]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(order) != len(self._nodes):
            raise PipelineGraphError(
                "Pipeline contains a cycle — topological sort failed. "
                f"Nodes not reached: {set(self._nodes) - set(order)}"
            )

        return order

    def get_node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    @property
    def execution_order(self) -> list[str]:
        return list(self._topo_order)
```

### 3.3 `run_pipeline` — DAG Execution

```python
def run_pipeline(
    config_path: str,
    logger: Any = None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    observer: NodeObserver | None = None,
) -> dict[str, Any]:
    """Execute a pipeline from a YAML config file.

    Returns the outputs dict of the final node in topological order.
    """
    from app.core.logger import PipelineLogger
    from app.core.run_manager import RunManager
    from app.core.pipeline_cache import PipelineCache

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if logger is None:
        logger = PipelineLogger()

    run = RunManager()
    run.save_config(yaml.dump(raw, sort_keys=False))

    pipeline_cfg = _parse_pipeline_config(raw)
    graph = PipelineGraph(pipeline_cfg, observer=observer)

    run_id = str(uuid.uuid4())
    cache = PipelineCache() if use_cache else None
    start_time = time.time()

    # Setup all nodes
    executors: dict[str, "NodeExecutor"] = {}
    for node_id in graph.execution_order:
        from app.core.pipeline import NodeExecutor
        exec_ = NodeExecutor(graph.get_node(node_id), run_id=run_id)
        exec_.setup()
        executors[node_id] = exec_

    # Build edge lookup: dst_id → list[(src_id, src_port, dst_port)]
    incoming: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in pipeline_cfg.edges:
        incoming[edge.dst_id].append((edge.src_id, edge.src_port, edge.dst_port))

    # Execution
    node_outputs: dict[str, dict[str, Any]] = {}  # node_id → outputs dict

    for node_id in graph.execution_order:
        node = graph.get_node(node_id)
        exec_ = executors[node_id]

        # Assemble inputs from upstream outputs
        inputs: dict[str, Any] = {}
        for src_id, src_port, dst_port in incoming[node_id]:
            upstream_outputs = node_outputs[src_id]
            value = upstream_outputs.get(src_port)
            port = node.input_ports.get(dst_port)
            if port and port.cardinality == "multi":
                inputs.setdefault(dst_port, [])
                inputs[dst_port].append(value)
            else:
                inputs[dst_port] = value

        # Fill unconnected optional ports with None
        for port_name, port in node.input_ports.items():
            if port_name not in inputs and not port.required:
                inputs[port_name] = None

        try:
            if streaming and node.is_streaming:
                # Streaming execution — collect into list for now
                # (full streaming pipeline is handled by run_pipeline_stream)
                outputs = asyncio.run(_collect_stream(exec_, inputs))
            else:
                outputs = exec_.execute(inputs)
        except Exception as exc:
            logger.node_error(node_id, 0, exc)
            run.save_logs(logger.logs)
            run.mark_failed(str(exc))
            raise

        node_outputs[node_id] = outputs

        if checkpoint:
            _write_checkpoint(run.base_path, node_id, outputs)

    # Teardown all nodes
    for exec_ in executors.values():
        exec_.teardown()

    total_duration = time.time() - start_time
    run.save_logs(logger.logs)
    run.save_metadata({"duration_s": round(total_duration, 4)})

    # Return outputs of the last node in topo order
    last_id = graph.execution_order[-1]
    return node_outputs[last_id]


async def _collect_stream(
    executor: "NodeExecutor",
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Collect all items from a streaming node into lists."""
    collected: dict[str, list] = {}
    async for item in executor.execute_stream(inputs):
        for k, v in item.items():
            collected.setdefault(k, []).append(v)
    return collected
```

### 3.4 YAML Pipeline Config Format (Updated)

The new format supports explicit edge declarations for multi-port topologies. For backward compatibility, a linear list of nodes without explicit edges is auto-converted to a chain of SISO edges.

```yaml
# New explicit DAG format
pipeline:
  seed: 42
  nodes:
    - id: input_0
      type: input
      config:
        path: workspace/datasets/input/speech

    - id: clean_0
      type: clean
      config:
        sample_rate: 16000

    - id: augment_0
      type: augment
      config:
        gain_db: [-6, 6]
        copies_per_sample: 2

    - id: split_0
      type: split
      config:
        train: 0.8
        val: 0.1

    - id: export_0
      type: export
      config:
        output: workspace/datasets/output
        project: my_project
        version: v1

  edges:
    - from: [input_0, output]
      to:   [clean_0, input]
    - from: [clean_0, output]
      to:   [augment_0, input]
    - from: [augment_0, output]
      to:   [split_0, input]
    - from: [split_0, output]
      to:   [export_0, input]
```

```yaml
# Legacy linear format (auto-converted — backward compatible)
pipeline:
  seed: 42
  nodes:
    - type: input
      config: { path: workspace/datasets/input/speech }
    - type: clean
      config: { sample_rate: 16000 }
    - type: export
      config: { output: workspace/datasets/output, project: p, version: v1 }
  # No 'edges' key → auto-chain: node[i].output → node[i+1].input
```

### 3.5 `_parse_pipeline_config` — Config Parser

```python
def _parse_pipeline_config(raw: dict) -> PipelineConfig:
    """Parse a raw YAML dict into a PipelineConfig.

    Supports both the new explicit-edge format and the legacy linear format.
    """
    pipeline = raw.get("pipeline", {})
    seed = pipeline.get("seed", 0)
    raw_nodes = pipeline.get("nodes", [])

    nodes: list[NodeSpec] = []
    for i, n in enumerate(raw_nodes):
        node_id = n.get("id") or f"{n['type']}_{i}"
        nodes.append(NodeSpec(
            node_id=node_id,
            node_type=n["type"],
            config=n.get("config", {}),
        ))

    raw_edges = pipeline.get("edges")
    if raw_edges:
        # Explicit edge format
        edges = [
            EdgeSpec(
                src_id=e["from"][0],
                src_port=e["from"][1],
                dst_id=e["to"][0],
                dst_port=e["to"][1],
            )
            for e in raw_edges
        ]
    else:
        # Legacy linear format: auto-chain output → input
        edges = [
            EdgeSpec(
                src_id=nodes[i].node_id,
                src_port="output",
                dst_id=nodes[i + 1].node_id,
                dst_port="input",
            )
            for i in range(len(nodes) - 1)
        ]

    return PipelineConfig(seed=seed, nodes=nodes, edges=edges)
```

### 3.6 `validation.py` Update

The existing `validate_pipeline` function is updated to use `CompatibilityChecker` instead of string comparison:

```python
# app/core/validation.py  (updated _validate_connections)
from app.core.nodes.compat import CompatibilityChecker
from app.core.nodes import registry as node_registry

def _validate_connections(nodes: list[dict], registry: Any) -> None:
    """Validate port-to-port type compatibility using CompatibilityChecker."""
    # Build temporary node instances for type checking only
    node_instances = {}
    for i, node_cfg in enumerate(nodes):
        node_type = node_cfg["type"]
        node_class = node_registry.get_class(node_type)
        # Use a minimal config for type-check-only instantiation
        try:
            instance = node_class.__new__(node_class)
            node_instances[i] = instance
        except Exception:
            continue

    for i in range(1, len(nodes)):
        src_node = node_instances.get(i - 1)
        dst_node = node_instances.get(i)
        if src_node is None or dst_node is None:
            continue
        CompatibilityChecker.check_connection(
            src_node, "output", dst_node, "input"
        )
```

---

## 4. Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

These properties are implemented using [Hypothesis](https://hypothesis.readthedocs.io/) (Python property-based testing library). Each test runs a minimum of 100 iterations.

Tag format: `Feature: enhanced-node-system, Property {N}: {property_text}`

---

### Property 1: `are_compatible` is reflexive for non-`None` types

*For any* non-`None` Python type `T` (plain class or generic alias), `CompatibilityChecker.are_compatible(T, T)` SHALL return `True`.

**Validates: Requirements R2.10**

```python
# Feature: enhanced-node-system, Property 1: are_compatible is reflexive
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.compat import CompatibilityChecker

_PLAIN_TYPES = st.sampled_from([int, str, float, bool, bytes, list, dict])

@given(_PLAIN_TYPES)
@settings(max_examples=100)
def test_are_compatible_reflexive(t):
    assert CompatibilityChecker.are_compatible(t, t) is True
```

---

### Property 2: `are_compatible` respects `issubclass` for plain classes

*For any* two plain (non-generic) Python classes `A` and `B`, `are_compatible(A, B)` SHALL return `True` if and only if `issubclass(A, B)` is `True`.

**Validates: Requirements R2.10**

```python
# Feature: enhanced-node-system, Property 2: are_compatible respects issubclass
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.compat import CompatibilityChecker

_CLASS_PAIRS = st.sampled_from([
    (bool, int),    # bool is subclass of int → True
    (int, bool),    # int is NOT subclass of bool → False
    (int, str),     # → False
    (str, str),     # → True
    (float, int),   # → False
    (int, float),   # → False
])

@given(_CLASS_PAIRS)
@settings(max_examples=100)
def test_are_compatible_matches_issubclass(pair):
    A, B = pair
    expected = issubclass(A, B)
    assert CompatibilityChecker.are_compatible(A, B) == expected
```

---

### Property 3: `TypeCatalogue` round-trip — `resolve(fqn(T)) is T`

*For any* `PortDataType` subclass `T`, registering it in a fresh `TypeCatalogue` and then calling `resolve(fqn(T))` SHALL return the exact same type object (`is` identity, not just equality).

**Validates: Requirements R13A.3**

```python
# Feature: enhanced-node-system, Property 3: TypeCatalogue round-trip
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.catalogue import TypeCatalogue, _fqn
from app.core.nodes.ports import PortDataType

def _make_port_type(name: str) -> type:
    """Dynamically create a PortDataType subclass with the given name."""
    return type(name, (PortDataType,), {"__module__": "test_module"})

_TYPE_NAMES = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
    min_size=3, max_size=20
).map(lambda s: s.capitalize())

@given(_TYPE_NAMES)
@settings(max_examples=100)
def test_type_catalogue_round_trip(name):
    catalogue = TypeCatalogue()
    T = _make_port_type(name)
    catalogue.register(T)
    resolved = catalogue.resolve(_fqn(T))
    assert resolved is T
```

---

### Property 4: Registry completeness — every registered node is retrievable

*For any* `Node` subclass registered in `NodeRegistry`, calling `get_class(node_type)` SHALL return the exact class, and `get_metadata(node_type)` SHALL return a `NodeMetadata` with the matching `node_type`.

**Validates: Requirements R3.2, R4.4**

```python
# Feature: enhanced-node-system, Property 4: registry completeness
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.registry import NodeRegistry
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.nodes.base import Node

_NODE_TYPES = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_",
    min_size=3, max_size=20
)

@given(_NODE_TYPES)
@settings(max_examples=100)
def test_registry_completeness(node_type):
    reg = NodeRegistry()
    meta = NodeMetadata(
        node_type=node_type,
        label="Test",
        description="Test node.",
        category="Test",
    )
    # Create a minimal Node subclass
    cls = type(f"TestNode_{node_type}", (Node,), {
        "node_type": node_type,
        "metadata": meta,
        "input_ports": {},
        "output_ports": {},
    })
    reg.register(node_type, cls, meta)

    assert reg.get_class(node_type) is cls
    assert reg.get_metadata(node_type).node_type == node_type
```

---

### Property 5: SISO wrapper equivalence

*For any* SISO node and any input value `x`, calling `node.process({"input": x})["output"]` SHALL produce the same result as calling the original unwrapped `process(node, x)` directly.

**Validates: Requirements R2B.6**

```python
# Feature: enhanced-node-system, Property 5: SISO wrapper equivalence
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.base import Node
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

def _make_siso_node(transform):
    """Create a SISO Node subclass whose process applies transform."""
    meta = NodeMetadata(
        node_type="test_siso",
        label="Test SISO",
        description="Test.",
        category="Test",
    )
    cls = type("TestSISONode", (Node,), {
        "node_type": "test_siso",
        "metadata": meta,
        "input_ports": {"input": InputPort(name="input", data_type=list)},
        "output_ports": {"output": OutputPort(name="output", data_type=list)},
        "process": lambda self, data: transform(data),
    })
    return cls()

@given(st.lists(st.integers(), max_size=20))
@settings(max_examples=100)
def test_siso_wrapper_equivalence(data):
    transform = lambda x: [v * 2 for v in x]
    node = _make_siso_node(transform)

    # Call via multi-port convention (what the pipeline uses)
    wrapped_result = node.process({"input": data})["output"]

    # Call the original transform directly
    direct_result = transform(data)

    assert wrapped_result == direct_result
```

---

### Property 6: Retry backoff formula

*For any* `RetryPolicy` with `backoff_seconds >= 0` and `backoff_multiplier >= 1.0`, the wait before retry attempt `i` (0-indexed) SHALL equal `backoff_seconds * (backoff_multiplier ** i)`.

**Validates: Requirements R6.3**

```python
# Feature: enhanced-node-system, Property 6: retry backoff formula
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.retry import RetryPolicy
import math

@given(
    backoff_seconds=st.floats(min_value=0.0, max_value=60.0, allow_nan=False),
    backoff_multiplier=st.floats(min_value=1.0, max_value=10.0, allow_nan=False),
    max_attempts=st.integers(min_value=1, max_value=10),
    attempt_index=st.integers(min_value=0, max_value=9),
)
@settings(max_examples=200)
def test_retry_backoff_formula(
    backoff_seconds, backoff_multiplier, max_attempts, attempt_index
):
    policy = RetryPolicy(
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        backoff_multiplier=backoff_multiplier,
    )
    expected = backoff_seconds * (backoff_multiplier ** attempt_index)
    actual = policy.wait_before_attempt(attempt_index)
    assert math.isclose(actual, expected, rel_tol=1e-9)
```

---

### Property 7: `NodeMetadata` serialisation round-trip

*For any* `NodeMetadata` instance `m`, `NodeMetadata.model_validate(m.model_dump(mode="json"))` SHALL produce an object equal to `m`.

**Validates: Requirements R11.2**

```python
# Feature: enhanced-node-system, Property 7: NodeMetadata round-trip
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.metadata import NodeMetadata

_NONEMPTY_STR = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=1, max_size=30,
).map(str.strip).filter(bool)

_METADATA = st.builds(
    NodeMetadata,
    node_type=_NONEMPTY_STR,
    label=_NONEMPTY_STR,
    description=_NONEMPTY_STR,
    category=_NONEMPTY_STR,
    version=st.just("1.0.0"),
    tags=st.lists(st.text(min_size=1, max_size=10), max_size=5),
)

@given(_METADATA)
@settings(max_examples=100)
def test_node_metadata_round_trip(m):
    dumped = m.model_dump(mode="json")
    restored = NodeMetadata.model_validate(dumped)
    assert restored == m
```

---

### Property 8: Config schema idempotence

*For any* registered node type `t`, calling `registry.get_config_schema(t)` twice SHALL return structurally equal dicts.

**Validates: Requirements R12.3**

```python
# Feature: enhanced-node-system, Property 8: config schema idempotence
from app.core.nodes import registry

def test_config_schema_idempotence():
    """For every registered node type, get_config_schema is idempotent."""
    for node_type in registry._classes:
        schema_1 = registry.get_config_schema(node_type)
        schema_2 = registry.get_config_schema(node_type)
        assert schema_1 == schema_2, (
            f"get_config_schema('{node_type}') returned different results "
            f"on consecutive calls"
        )
```

> Note: This is an example-based test (not randomised) because the set of registered node types is finite and deterministic. It exhaustively covers all registered types.

---

## 5. Testing Strategy

### Unit Tests (example-based)

Focus on specific behaviors and error conditions:

- `NodeConfig` dict coercion: pass valid dict → config instance; pass invalid dict → `ValidationError`
- `CompatibilityChecker.check_connection`: valid connection → no raise; invalid type → `NodeTypeError`; missing port → `NodeTypeError`
- `AutoDiscovery` error handling: duplicate `node_type` → `DuplicateNodeTypeError`; missing metadata → `NodeMetadataError`
- `NodeRegistry.from_json`: invalid JSON → `ValueError`; invalid schema → `ValidationError`
- `NodeExecutor` lifecycle ordering: mock hooks, verify `setup → on_start → process → on_end → teardown` sequence
- `NodeExecutor` retry: mock `process` to fail N times then succeed; verify retry count and final success
- `PipelineGraph` cycle detection: construct a cyclic graph → `PipelineGraphError`
- SISO `input_type` / `output_type` properties: SISO node → returns correct type; non-SISO → `AttributeError`
- `TypeCatalogue.register` with non-`PortDataType` → `TypeError`
- `NodeRegistry.find_compatible_nodes`: verify correct direction filtering

### Property Tests (Hypothesis)

See Properties 1–8 above. Each runs ≥ 100 iterations.

### Integration Tests

- Full pipeline execution: load a YAML config, run `run_pipeline`, verify output structure
- Legacy linear format backward compatibility: existing YAML configs run without modification
- Plugin discovery: place a node file in `plugins/`, verify it appears in registry after import
- `AudioSample` Pydantic migration: verify existing `AudioSample(path=..., ...)` construction still works

### Migration Regression Tests

For each migrated audio node:
- Construct with the same dict config that was previously accepted
- Run `process` with a fixed `AudioSample` list and fixed seed
- Assert output is byte-for-byte identical to pre-migration baseline (deterministic nodes)
- Assert output distribution matches for stochastic nodes (same seed → same RNG sequence)
