# Pipeline Execution

This document covers the Graph IR, the DAG executor, and how a pipeline is built and executed node by node.

---

## Overview

```
IR JSON file  (or YAML — deprecated)
    │
    ▼
load_ir() / yaml_shim          → GraphIR object
    │
    ▼
_ir_to_pipeline_config()       → PipelineConfig (nodes + edges)
    │
    ▼
PipelineGraph()                → instantiates nodes, validates edges, topological sort
    │
    ▼
run_pipeline_ir()              → executes nodes in topo order via NodeExecutor
    │
    ├── PipelineCache          → skip re-execution on cache hit
    ├── PipelineLogger         → emit structured events
    └── RunManager             → persist meta.json, graph.json, logs.json
```

---

## Graph IR (`app/core/ir/`)

The canonical pipeline representation. All interfaces produce and consume `GraphIR` objects. YAML is a deprecated serialization format.

```python
from app.core.ir import GraphIR, IRNode, IREdge, IRMetadata, IRCapabilityMetadata
from app.core.ir import load_ir, dump_ir, load_ir_from_file, dump_ir_to_file
from app.core.ir import CURRENT_IR_VERSION  # "1.0"

# Load from dict (e.g. from API request body)
graph = load_ir(graph_dict)

# Load from file
graph = load_ir_from_file("pipeline.graph.json")

# Serialize
data = dump_ir(graph)           # → dict
dump_ir_to_file(graph, path)    # → writes .graph.json
```

### `IRCapabilityMetadata` (Phase 1)

Per-instance capability override on `IRNode`. When set, takes precedence over the node class's `NodeMetadata` capability fields for that specific graph instance.

```python
class IRCapabilityMetadata(BaseModel):  # frozen=True
    requires_gpu: bool = False
    supports_cpu: bool = True
    supports_edge: bool = False
    deterministic: bool = True
    cacheable: bool = True
    streaming_support: bool = False
    realtime_support: bool = False
```

**Two-step capability resolution** (used by `run_pipeline_ir` and MCP `get_graph_capability_summary`):
1. If `IRNode.capability_metadata` is non-null → use those values
2. Otherwise → use the corresponding fields from `NodeMetadata` in the registry

### IR JSON format

```json
{
  "schema_version": "1.1",
  "metadata": {"name": "my-pipeline", "seed": 42, "description": ""},
  "nodes": [
    {"id": "cond_0",    "node_type": "audio_conditioner", "config": {"sample_rate": 16000}},
    {"id": "seg_0",     "node_type": "segmenter",         "config": {"mode": "vad"}}
  ],
  "edges": [
    {"src_id": "cond_0", "src_port": "output", "dst_id": "seg_0", "dst_port": "input"}
  ]
}
```

**YAML is deprecated.** Use `yaml_shim.yaml_config_to_ir(raw)` to convert old YAML dicts to `GraphIR`.
Migration: `graphyn migrate --config pipeline.yaml` → `pipeline.graph.json`.

---

## Data Structures

**File:** `app/core/pipeline.py`

```python
@dataclass
class NodeSpec:
    node_id: str       # unique within pipeline, e.g. "cond_0"
    node_type: str     # registry key, e.g. "audio_conditioner"
    config: dict[str, Any]

@dataclass
class EdgeSpec:
    src_id: str        # source node ID
    src_port: str      # output port name on source
    dst_id: str        # destination node ID
    dst_port: str      # input port name on destination

@dataclass
class PipelineConfig:
    seed: int
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
```

---

## Primary Execution Entry Point

```python
# Canonical — all interfaces use this
from app.core.runtime_backend import get_backend
result = get_backend().execute(graph, logger=None, use_cache=True, checkpoint=False,
    streaming=False, parallel=False, observer=None, run_manager=None,
    max_workers=None, resume_run_id=None, include_nodes=None,
    exclude_nodes=None, input_overrides=None, event_driven=False)

# Direct orchestrator access (internal / backward compat only)
from app.core.pipeline import run_pipeline_ir
result = run_pipeline_ir(graph, ...)
```

`RuntimeBackend` is the canonical execution entry point. `LocalPythonBackend` (the default) delegates to `run_pipeline_ir`. Custom backends can be registered via `register_backend(id, BackendClass)`. All interfaces (SDK, API, MCP, CLI) call `get_backend().execute()`.

`run_pipeline(config_path)` is a **deprecated shim** — it reads the raw YAML for `save_config()`, then calls `load_yaml_with_deprecation(config_path)` (emitting a `DeprecationWarning` about YAML format), then calls `run_pipeline_ir`. Emits two `DeprecationWarning`s total.

```yaml
pipeline:
  seed: 42
  nodes:
    - type: dataset_ingest
      config:
        path: workspace/datasets/input/speech
    - type: audio_conditioner
      config:
        sample_rate: 16000
    - type: segmenter
      config:
        mode: vad
    - type: feature_frontend
      config:
        feature_type: mfcc
    - type: dataset_builder
      config:
        split_ratios: {train: 0.8, val: 0.1, test: 0.1}
```

### DAG Format (explicit edges)

Use `id` on each node and an `edges` list for non-linear topologies. Each edge specifies `from: [node_id, port_name]` and `to: [node_id, port_name]`.

```yaml
pipeline:
  seed: 42
  nodes:
    - id: ingest_0
      type: dataset_ingest
      config:
        path: workspace/datasets/input/speech
    - id: cond_0
      type: audio_conditioner
      config:
        sample_rate: 16000
    - id: aug_0
      type: augmentation_pipeline
      config:
        augmentations:
          - {type: gain, apply_prob: 0.5, gain_db: [-3.0, 3.0]}
        copies_per_sample: 2
    - id: feat_0
      type: feature_frontend
      config:
        feature_type: mfcc
    - id: ds_0
      type: dataset_builder
      config:
        split_ratios: {train: 0.8, val: 0.1, test: 0.1}
  edges:
    - from: [ingest_0, output]
      to:   [cond_0, input]
    - from: [cond_0, output]
      to:   [aug_0, input]
    - from: [aug_0, output]
      to:   [feat_0, input]
    - from: [feat_0, output]
      to:   [ds_0, input]
```

If `id` is omitted in the DAG format, node IDs are auto-generated as `{type}_{index}` (e.g. `clean_1`).

---

## `_parse_pipeline_config(raw: dict) → PipelineConfig`

Parses a raw YAML dict into a `PipelineConfig`:

1. Reads `pipeline.seed` (default `0`)
2. Reads `pipeline.nodes` — assigns `node_id` from `n.get("id")` or `f"{type}_{i}"`
3. If `pipeline.edges` is present → parses explicit edges
4. Otherwise → auto-chains: `EdgeSpec(nodes[i].node_id, "output", nodes[i+1].node_id, "input")` for each consecutive pair

---

## `PipelineGraph`

```python
graph = PipelineGraph(config, observer=None)
graph.execution_order   # list[str] — node IDs in topological order
graph.get_node(node_id) # → Node instance
```

### Build steps

1. **Instantiate nodes** — for each `NodeSpec`, calls `registry.get_class(node_type)` and constructs the node with `node_seed = stable_hash(seed, node_type, index) % 2**32`.
2. **Validate edges** — calls `CompatibilityChecker.check_connection()` for each edge. Raises `PipelineGraphError` if a node ID is unknown or types are incompatible.
3. **Topological sort** — Kahn's algorithm. Raises `PipelineGraphError` if a cycle is detected.

---

## `NodeExecutor`

```python
executor = NodeExecutor(node, run_id="run-abc")
executor.setup()
outputs = executor.execute({"input": data})
executor.teardown()
```

### `execute(inputs)` sequence

For each attempt (up to `retry_policy.max_attempts`):
1. Sleep `policy.wait_before_attempt(attempt - 1)` (skipped for attempt 0)
2. `node.on_start()` → observer `on_node_start`
3. `node.process(inputs)` → `outputs`
4. `node.on_end()` → observer `on_node_end`

On exception in steps 2–3:
- `node.on_error(exc)` → observer `on_node_error`
- Continue to next attempt

After all attempts exhausted:
- `node.on_error(last_exc)` → observer `on_node_error`
- `self.teardown()`
- Re-raise `last_exc`

### `execute_stream(inputs)` sequence

Calls `node.process_stream(inputs)` (async generator). Default implementation wraps `process()` as a single-item generator.

---

## `run_pipeline()`

```python
def run_pipeline(
    config_path: str,
    logger: PipelineLogger | None = None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    observer: NodeObserver | None = None,
    run_manager: RunManager | None = None,
) -> dict[str, Any]:
```

**Returns:** The outputs dict of the final node in topological order.

### Execution steps

1. Load and parse YAML from `config_path`
2. Create `PipelineLogger` if not provided
3. Create `RunManager` if not provided (writes initial `meta.json` with `status: "running"`)
4. Call `_parse_pipeline_config()` → `PipelineConfig`
5. Build `PipelineGraph` (instantiates nodes, validates edges, topological sort)
6. Create `PipelineCache` if `use_cache=True`
7. Call `logger.pipeline_start(total_nodes)`
8. Call `executor.setup()` for all nodes
9. For each node in topological order:
   a. Assemble `inputs` dict from upstream `node_outputs`
   b. Fill unconnected optional ports with `None`
   c. Check cache (if `use_cache=True` and input is a list)
   d. Execute via `executor.execute()` (or `execute_stream()` if `streaming=True`)
   e. Save to cache if applicable
   f. Write checkpoint if `checkpoint=True`
   g. Call `logger.node_end()`
10. Call `executor.teardown()` for all nodes
11. Call `logger.summary()`
12. Call `run.save_logs()` and `run.save_metadata()`
13. Return `node_outputs[last_node_id]`

### Input assembly

For each incoming edge `(src_id, src_port, dst_port)`:
- If `dst_port.cardinality == "multi"`: append to `inputs[dst_port]` list
- Otherwise: `inputs[dst_port] = upstream_outputs[src_id][src_port]`

Unconnected optional ports receive `None`.

---

## `PipelineCache`

**File:** `app/core/pipeline_cache.py`

Caches node outputs under `workspace/cache/{sha256}/`. Domain-agnostic — uses `ArtifactSerializerRegistry.infer_type()` to detect serializable output types; no domain model imports.

```python
cache = PipelineCache()

# Canonical key computation (preferred — shared by sequential and parallel executors)
key = cache.compute_key(node_type, config_dict, inputs)

# Or manually:
key = cache.key(node_type, config_dict, cache.input_hash(value))

# Load — treat None as a miss; never call has() first (TOCTOU hazard)
cached = cache.load(key)   # returns outputs dict or None

# Save
cache.save(key, outputs)

# Clear all
stats = cache.clear()  # {"entries_deleted": N, "bytes_freed": N}
```

### Cache key

`SHA-256(node_type + sorted_json(config) + combined_input_hash)` where `combined_input_hash` is `SHA-256` of all per-port input hashes concatenated (preserves port identity).

### Cache format

```
workspace/cache/{sha256}/
├── outputs.json          # generic JSON-serializable outputs
# or for AudioSample outputs:
├── port_{name}/
│   ├── 0.wav … N.wav
│   └── manifest.json
└── manifest.json         # lists cached_ports
```

---

## Checkpoints

When `checkpoint=True`, after each node executes, `_write_checkpoint()` writes the node's list-valued output to:

```
workspace/runs/{run_id}/checkpoints/node_{node_id}/
├── 0.wav
├── 1.wav
├── ...
└── manifest.json
```

Checkpoints are accessible via `GET /api/v1/runs/{run_id}/checkpoints` and via the MCP `inspect_run` tool.

## Run Directory Structure

```
workspace/runs/{run_id}/
├── meta.json        # Run metadata (status, timing, node_stats)
├── logs.json        # NDJSON event log
├── graph.json       # GraphIR JSON (always written — Phase 1)
├── config.yaml      # YAML config (only when run via deprecated YAML path)
└── checkpoints/     # Per-node checkpoints (when checkpoint=True)
    └── node_{id}/
        ├── *.wav
        └── manifest.json
```

`graph.json` is written by `RunManager.save_graph_ir()` immediately after execution starts. It is the canonical record of what graph was executed and is exposed by the MCP `inspect_run` tool.

---

## `validate_pipeline()`

**File:** `app/core/validation.py`

```python
def validate_pipeline(config: Any, registry: Any) -> list[dict]:
```

Validates a raw YAML dict. Returns a list of validated node dicts on success. Raises `ValueError` on failure.

### Checks performed

1. `config` is a dict with a `"pipeline"` key
2. `pipeline` is a dict with an integer `seed`
3. `pipeline.nodes` is a non-empty list
4. Each node has a string `type` and an optional dict `config`
5. Each `node_type` exists in the registry (`registry.get_class(node_type)`)
6. Each node config validates against `NodeClass.Config.model_validate(config)`
7. If `pipeline.edges` is present → `_validate_dag_edges()` checks edge node IDs, port names, and type compatibility
8. Otherwise → `_validate_connections()` checks consecutive node port compatibility

**No audio-specific constraints.** Any valid node sequence is accepted.

### `_validate_dag_edges(nodes, edges, registry)`

For each edge:
- Source and destination node IDs must exist
- Source output port must exist on the source node class
- Destination input port must exist on the destination node class
- `CompatibilityChecker.are_compatible(src_data_type, dst_data_type)` must be `True`

### `_validate_connections(nodes, registry)`

For consecutive node pairs in a linear pipeline:
- Checks `CompatibilityChecker.check_connection(src, "output", dst, "input")`
- Failures are silently ignored (best-effort; hard errors come from `PipelineGraph`)

---

## `stable_hash()`

**File:** `app/core/utils/hash.py`

Deterministic hash used for node seeds and export file IDs. Takes any number of arguments, converts them to strings, and returns a stable integer hash. The same inputs always produce the same output across Python runs.
