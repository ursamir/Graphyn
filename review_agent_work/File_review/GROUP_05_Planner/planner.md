# Functional Review — app/core/planner.py

**Group:** 5 — Planner
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _build
CATEGORY:    Silent Failure
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Instantiate Node objects from NodeSpecs, validate edges, and compute topological order and parallel waves.

WHAT IT ACTUALLY DOES:
At line ~148, `self._nodes[spec.node_id] = node` unconditionally overwrites any existing entry. If two `NodeSpec` entries share the same `node_id`, the first node is silently discarded and replaced by the second. All edges that referenced the first node now point to the second node's instance.

THE BUG / RISK:
Duplicate node IDs cause silent data corruption: the wrong node instance is wired into the graph. No exception is raised, no warning is logged. The pipeline runs with a structurally incorrect DAG.

EVIDENCE:
```python
# ~line 148
self._nodes[spec.node_id] = node   # silent overwrite if node_id already exists
```

REPRODUCTION SCENARIO:
```python
config = PipelineConfig(
    seed=0,
    nodes=[
        NodeSpec("n1", "TypeA", {}),
        NodeSpec("n1", "TypeB", {}),   # duplicate ID
    ],
    edges=[EdgeSpec("n1", "output", "n1", "input")],
)
g = PipelineGraph(config)
# g._nodes["n1"] is TypeB instance; TypeA instance is gone
```

IMPACT:
Silent wrong result — the pipeline executes with the wrong node wired in. Data loss of the first node. No crash, no warning.

FIX DIRECTION:
Add a duplicate-ID check before insertion:
```python
if spec.node_id in self._nodes:
    raise PipelineGraphError(
        f"Duplicate node ID '{spec.node_id}' in pipeline config"
    )
self._nodes[spec.node_id] = node
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _build
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Instantiate Node objects from NodeSpecs using the node registry.

WHAT IT ACTUALLY DOES:
At line ~145, `node_registry.get_class(spec.node_type)` is called. If the registry returns `None` for an unknown node type, the next line `node_class(config=..., seed=..., observer=...)` raises `TypeError: 'NoneType' object is not callable`. The error message contains no information about which node type was missing or which pipeline node caused the failure.

THE BUG / RISK:
An unknown `node_type` produces a cryptic `TypeError` instead of a `PipelineGraphError` with a meaningful message. Callers catching `PipelineGraphError` will not catch this, breaking the error contract.

EVIDENCE:
```python
# ~lines 144-150
node_class = node_registry.get_class(spec.node_type)
# no None-check here
node = node_class(config=node_config, seed=node_seed, observer=self._observer)
```

REPRODUCTION SCENARIO:
```python
config = PipelineConfig(seed=0, nodes=[NodeSpec("n1", "UnregisteredType", {})], edges=[])
PipelineGraph(config)
# raises: TypeError: 'NoneType' object is not callable
```

IMPACT:
Crash with an uninformative error. Callers expecting `PipelineGraphError` will not catch it, potentially causing unhandled exceptions to propagate to the API layer.

FIX DIRECTION:
```python
node_class = node_registry.get_class(spec.node_type)
if node_class is None:
    raise PipelineGraphError(
        f"Unknown node type '{spec.node_type}' for node '{spec.node_id}'"
    )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _build
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Instantiate nodes with their configs, seeding each node deterministically.

WHAT IT ACTUALLY DOES:
At line ~148, `json.dumps(spec.config, sort_keys=True)` is called to produce a stable hash input. If `spec.config` contains any non-JSON-serializable value (e.g. a `datetime`, `bytes`, a custom object, or a `numpy` array), this raises a bare `TypeError` with no context about which node or config key caused the failure.

THE BUG / RISK:
Non-serializable config values produce a cryptic `TypeError` that does not identify the offending node or field. The error is not wrapped in `PipelineGraphError`, breaking the error contract for callers.

EVIDENCE:
```python
# ~line 148
json.dumps(spec.config, sort_keys=True)   # raises TypeError on non-serializable values
```

REPRODUCTION SCENARIO:
```python
import datetime
config = PipelineConfig(
    seed=0,
    nodes=[NodeSpec("n1", "SomeType", {"ts": datetime.datetime.now()})],
    edges=[],
)
PipelineGraph(config)
# raises: TypeError: Object of type datetime is not JSON serializable
```

IMPACT:
Crash with an uninformative error. The caller cannot determine which node or config field is at fault.

FIX DIRECTION:
```python
try:
    config_str = json.dumps(spec.config, sort_keys=True)
except TypeError as exc:
    raise PipelineGraphError(
        f"Node '{spec.node_id}' config is not JSON-serializable: {exc}"
    ) from exc
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _parse_pipeline_config
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Parse a raw YAML dict into a PipelineConfig, supporting both explicit-edge and legacy linear formats.

WHAT IT ACTUALLY DOES:
At line ~75, `n["type"]` is accessed with a plain dict key lookup. If a node entry in the YAML is missing the `"type"` key, a raw `KeyError: 'type'` is raised with no context about which node index or pipeline caused the failure. Similarly, at lines ~87-90, `e["from"]` and `e["to"]` are accessed without guards — a missing key raises a raw `KeyError`.

THE BUG / RISK:
Malformed YAML input produces bare `KeyError` exceptions with no diagnostic context. The caller cannot determine which node or edge is malformed without inspecting the raw traceback.

EVIDENCE:
```python
# ~line 75
node_type=n["type"],          # KeyError if "type" missing

# ~lines 87-90
src_id=e["from"][0],          # KeyError if "from" missing
src_port=e["from"][1],
dst_id=e["to"][0],
dst_port=e["to"][1],
```

REPRODUCTION SCENARIO:
```python
raw = {"pipeline": {"nodes": [{"id": "n1", "config": {}}]}}  # missing "type"
_parse_pipeline_config(raw)
# raises: KeyError: 'type'
```

IMPACT:
Crash with an uninformative error. API or CLI callers receive a 500-level error with no actionable message for the user.

FIX DIRECTION:
Wrap the loop body in a try/except or use `.get()` with explicit validation:
```python
node_type = n.get("type")
if not node_type:
    raise ValueError(f"Node at index {i} is missing required field 'type'")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _parse_pipeline_config
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Parse edge definitions from the raw YAML dict, extracting src/dst node IDs and port names.

WHAT IT ACTUALLY DOES:
At lines ~87-90, `e["from"][0]` and `e["from"][1]` use integer indexing on the value of `e["from"]`. If the YAML author writes `from: "node_a"` (a string) instead of `from: ["node_a", "output"]` (a list), then `e["from"][0]` silently returns `"n"` (the first character of `"node_a"`) and `e["from"][1]` returns `"o"`. No error is raised; the pipeline is built with completely wrong node IDs.

THE BUG / RISK:
A string value for `"from"` or `"to"` is silently sliced into characters, producing an invalid but non-crashing `EdgeSpec`. The pipeline will later fail with a confusing "unknown node" error, or — if node IDs happen to be single characters — silently wire the wrong nodes.

EVIDENCE:
```python
# ~lines 87-90
src_id=e["from"][0],    # "node_a"[0] == "n"  ← silent wrong result
src_port=e["from"][1],  # "node_a"[1] == "o"  ← silent wrong result
```

REPRODUCTION SCENARIO:
```python
raw = {"pipeline": {"nodes": [...], "edges": [{"from": "node_a", "to": "node_b"}]}}
cfg = _parse_pipeline_config(raw)
# cfg.edges[0].src_id == "n", cfg.edges[0].src_port == "o"
```

IMPACT:
Silent wrong result — the pipeline is built with garbage edge data. Downstream errors will be confusing and hard to trace back to the YAML parsing step.

FIX DIRECTION:
```python
from_val = e["from"]
if not isinstance(from_val, (list, tuple)) or len(from_val) < 2:
    raise ValueError(f"Edge 'from' must be a 2-element list, got: {from_val!r}")
src_id, src_port = from_val[0], from_val[1]
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _compute_waves
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Compute parallel execution waves (level-based BFS) for the pipeline nodes.

WHAT IT ACTUALLY DOES:
When the pipeline has zero nodes, `self._topo_order` is empty, `level` is an empty dict, and `max(level.values(), default=0)` returns `0`. The function then returns `[waves_dict[0]]`, which is `[[]]` — a list containing one empty wave — instead of an empty list `[]`.

THE BUG / RISK:
A zero-node pipeline produces one spurious empty wave. Callers iterating `execution_waves` and dispatching work per wave will process one empty wave, which is harmless in most executors but semantically incorrect and may cause off-by-one issues in wave-count-sensitive logic.

EVIDENCE:
```python
# ~lines 203-207
max_level = max(level.values(), default=0)   # returns 0 when level is empty
return [waves_dict[i] for i in range(max_level + 1)]
# waves_dict[0] is defaultdict → returns [] → result is [[]]
```

REPRODUCTION SCENARIO:
```python
config = PipelineConfig(seed=0, nodes=[], edges=[])
g = PipelineGraph(config)
assert g.execution_waves == []   # FAILS — actual: [[]]
```

IMPACT:
Incorrect return value for empty pipeline. Likely harmless in practice but violates the contract and can cause subtle bugs in wave-count-sensitive callers.

FIX DIRECTION:
```python
if not level:
    return []
max_level = max(level.values())
return [waves_dict[i] for i in range(max_level + 1)]
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _build
CATEGORY:    Testability
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Build the validated DAG from the PipelineConfig.

WHAT IT ACTUALLY DOES:
`_build` defers three imports to runtime inside the method body (lines ~136-139): `get_registry`, `CompatibilityChecker`, and `PipelineGraphError`. This means unit tests must patch these at the exact internal import path (`app.core.registry_runtime.get_registry`, etc.) rather than at the module level. The singleton `get_registry()` call makes it impossible to inject a mock registry via constructor argument.

THE BUG / RISK:
`PipelineGraph` cannot be instantiated in a unit test without either a fully wired registry or careful `unittest.mock.patch` targeting the deferred import paths. There is no dependency-injection seam for the registry. Tests that forget to patch the right path will silently use the real registry, causing test pollution or import errors.

EVIDENCE:
```python
# ~lines 136-139
def _build(self) -> None:
    from app.core.registry_runtime import get_registry        # deferred singleton
    from app.core.nodes.compat import CompatibilityChecker    # deferred
    from app.core.nodes.errors import PipelineGraphError      # deferred
```

REPRODUCTION SCENARIO:
Any attempt to unit test `PipelineGraph` in isolation without patching `app.core.registry_runtime.get_registry` will call the real registry, which may be empty or raise import errors in a test environment.

IMPACT:
Test hostile — unit tests require non-obvious patching. Increases risk of test pollution and false passes/failures.

FIX DIRECTION:
Accept an optional `registry` parameter in `__init__` for injection:
```python
def __init__(self, config, observer=None, registry=None):
    self._registry = registry  # injected in tests; real registry fetched in _build if None
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _build
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate all edges via CompatibilityChecker, raising PipelineGraphError on invalid connections.

WHAT IT ACTUALLY DOES:
`CompatibilityChecker.check_connection` (imported from `app.core.nodes.compat`) may raise its own exception type (not necessarily `PipelineGraphError`). The `_build` method does not catch or re-wrap these exceptions. Callers of `PipelineGraph.__init__` who catch only `PipelineGraphError` will miss compatibility errors, which propagate as unhandled exceptions.

THE BUG / RISK:
The public error contract of `PipelineGraph` is broken: callers expecting a single `PipelineGraphError` exception type for all build failures must also know to catch whatever `CompatibilityChecker` raises. This is an undocumented, implicit dependency on the compat module's exception hierarchy.

EVIDENCE:
```python
# ~lines 155-160
CompatibilityChecker.check_connection(src_node, edge.src_port, dst_node, edge.dst_port)
# no try/except — compat errors propagate unwrapped
```

REPRODUCTION SCENARIO:
Any edge connecting incompatible port types will raise the compat module's own exception, not `PipelineGraphError`, surprising callers who only catch `PipelineGraphError`.

IMPACT:
Unhandled exceptions at the API/orchestrator layer; inconsistent error handling contract.

FIX DIRECTION:
```python
try:
    CompatibilityChecker.check_connection(src_node, edge.src_port, dst_node, edge.dst_port)
except PipelineGraphError:
    raise
except Exception as exc:
    raise PipelineGraphError(f"Incompatible edge {edge.src_id}.{edge.src_port} → "
                             f"{edge.dst_id}.{edge.dst_port}: {exc}") from exc
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/core/planner.py
FUNCTION:    _ir_to_pipeline_config
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a GraphIR to a PipelineConfig. Pure — no side effects, no I/O.

WHAT IT ACTUALLY DOES:
Accesses `graph.metadata.seed` at line ~112 without guarding against `graph.metadata` being `None`. If the IR was constructed without metadata (or with `metadata=None`), this raises `AttributeError: 'NoneType' object has no attribute 'seed'` with no context.

THE BUG / RISK:
A malformed or partially-constructed `GraphIR` object causes an uninformative `AttributeError` rather than a clear validation error. The docstring claims the function is "pure" but does not document that it can raise on malformed input.

EVIDENCE:
```python
# ~line 112
return PipelineConfig(seed=graph.metadata.seed, ...)
# AttributeError if graph.metadata is None
```

REPRODUCTION SCENARIO:
```python
class FakeGraph:
    nodes = []
    edges = []
    metadata = None
_ir_to_pipeline_config(FakeGraph())
# AttributeError: 'NoneType' object has no attribute 'seed'
```

IMPACT:
Uninformative crash on malformed IR input. Low severity because the IR schema should enforce metadata presence, but the function provides no defensive guard.

FIX DIRECTION:
```python
seed = getattr(graph.metadata, "seed", 0) if graph.metadata else 0
```
Or raise explicitly:
```python
if graph.metadata is None:
    raise ValueError("GraphIR is missing metadata — cannot extract seed")
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_build` silently overwrites the first node when two NodeSpecs share the same `node_id`, producing a structurally corrupt DAG with no error or warning. |
