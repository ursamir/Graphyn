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
get_backend().execute(graph)   → canonical entry point (SDK/API/CLI/MCP)
    │
    ├── LocalPythonBackend (default)
    │     └── orchestrator.run_pipeline_ir_async(graph, ...)
    └── DistributedBackend (GRAPHYN_BACKEND=distributed)
          └── wave scheduler + workers (see DISTRIBUTED_EXECUTION.md)
              │
              ▼  (local path)
    _ir_to_pipeline_config()   → PipelineConfig (nodes + edges)
              │
              ▼
    PipelineGraph()            → instantiates nodes, validates edges, topological sort
              │
              ▼
    NodeExecutor per node      → setup → process → teardown
              │
    ├── PipelineCache          → skip re-execution on cache hit
    ├── PipelineLogger         → emit structured events
    ├── RunManager (run_journal.py) → persist meta.json, graph.json, logs.json
    └── checkpoint.py          → per-node checkpoint read/write
```

---

## Graph IR (`app/core/ir/`)

The canonical pipeline representation. All interfaces produce and consume `GraphIR` objects. YAML is a deprecated serialization format.

```python
from app.core.ir import GraphIR, IRNode, IREdge, IRMetadata, IRCapabilityMetadata
from app.core.ir import load_ir, dump_ir, load_ir_from_file, dump_ir_to_file
from app.core.ir import CURRENT_IR_VERSION  # "1.2"

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

### `IRPlacement` (IR 1.2)

Optional per-node placement on `IRNode.placement` for distributed execution:

```python
class IRPlacement(BaseModel):  # frozen=True
    mode: str = "auto"          # auto | local | worker
    worker: str | None = None   # pin to worker id when mode=worker
    tags: list[str] = []        # e.g. ["gpu"]
    require_gpu: bool = False
    min_vram_mib: int | None = None
    pool: str | None = None
```

Omitted / `None` → auto from capability. Loader accepts `1.0`/`1.1` graphs (`placement=None`). See [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md).

### Artifact refs (distributed)

Remote nodes exchange ports as `artifact://` URIs / `input_refs` / `output_refs` rather than rematerializing the full graph locally. Blob bytes live under `workspace/artifacts/distributed_blobs/` (HTTP put/get via control API).

### IR JSON format

```json
{
  "schema_version": "1.2",
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

**File:** `app/core/execution/planner.py`

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
    condition: str | None = None  # optional condition expression

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
from app.core.execution.runtime_backend import get_backend
result = get_backend().execute(graph, logger=None, use_cache=True, checkpoint=False,
    streaming=False, parallel=False, observer=None, run_manager=None,
    max_workers=None, resume_run_id=None, include_nodes=None,
    exclude_nodes=None, input_overrides=None, event_driven=False)

# Direct orchestrator access (internal / backward compat only)
from app.core.execution.orchestrator import run_pipeline_ir
result = run_pipeline_ir(graph, ...)
```

`RuntimeBackend` is the canonical execution entry point. `LocalPythonBackend` (the default) delegates to `orchestrator.run_pipeline_ir_async`. `DistributedBackend` (`GRAPHYN_BACKEND=distributed`) runs a wave scheduler with local `NodeExecutor` and remote jobs. Custom backends can be registered via `register_backend(id, BackendClass)`.

`run_pipeline()` is a **deprecated shim** — it reads raw YAML, emits `DeprecationWarning`, then calls `run_pipeline_ir`. Use `get_backend().execute()` for all new code.

The legacy `app/core/pipeline.py` re-export shim was **removed** (2026-09-16). Import from `app.core.execution.planner`, `app.core.execution.orchestrator`, or use `get_backend().execute()` directly. YAML execution: `app.core.ir.yaml_shim.run_pipeline_from_yaml` (deprecated).

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

**File:** `app/core/execution/planner.py`

```python
graph = PipelineGraph(config, observer=None)
graph.execution_order    # list[str] — node IDs in topological order
graph.execution_waves    # list[list[str]] — parallel wave groups
graph.get_node(node_id)  # → Node instance
```

### Build steps

1. **Instantiate nodes** — for each `NodeSpec`, calls `registry.get_class(node_type)` and constructs the node with `node_seed = stable_hash(seed, node_type, index, config_str) % 2**32`. Config is included in the seed so two pipelines with the same seed and node types but different configs produce distinct node seeds.
2. **Validate edges** — calls `CompatibilityChecker.check_connection()` for each edge. Raises `PipelineGraphError` if a node ID is unknown or types are incompatible.
3. **Topological sort** — Kahn's algorithm. Raises `PipelineGraphError` if a cycle is detected.
4. **Compute waves** — level-based BFS in O(N). Empty pipeline returns `[]`.

---

## `NodeExecutor`

**File:** `app/core/execution/node_executor.py`

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

### Node progress (`app/core/nodes/progress.py`)

`process()` runs inside `progress_context(node_id, node_type, sink)` (bound by `NodeExecutor.set_progress_sink`, which the orchestrator calls for every executor). A node calls `emit_node_progress({"phase": "train", "epoch": 3, "epochs": 30, "loss": 0.41, …})`; the sink turns it into a `node_progress` event (`node_id`, `node_type`, `ts`, `level`, human `message` such as `Trainer · epoch 3/30 · loss 0.41 · val_acc 0.78`, plus the payload) and hands it to `PipelineLogger.node_progress` → run journal + NDJSON queue. The orchestrator sink also mirrors the latest event per node into `meta.json` `node_progress` and flushes `logs.json` (tmp + replace) at most every 5 s. Throttle: ≤ 2 events/s per node (`final: true` / `pct >= 100` always pass). Outside a run the call is a no-op and never raises.

Events carry `node_label` (logger `node_labels`, also mirrored into `meta.node_progress`). Isolated plugin workers have no context: `run_isolated_node` captures `current_progress_sink()` in the calling thread, sets `GRAPHYN_PROGRESS_MARKER=1` for the worker, and drains the worker's stdout/stderr with reader threads; stderr lines `@@GRAPHYN_PROGRESS@@ <json>` are parsed live and forwarded (and removed from the captured stderr). Without a sink the old `communicate()` path is used unchanged.

Ingest nodes: `node_end` events of `*ingest*` node types also carry `dataset: {source_path, resolved_path, source_type, clip_count, fallback_used}` (`app/core/runs/run_dataset.py`).

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

## Run lifecycle

**Files:** `app/core/execution/orchestrator.py`, `app/core/runs/run_journal.py` (`RunManager`), `app/core/runs/run_status.py`, `app/core/distributed/backend.py`

**Statuses** (`meta.json` `status`): `pending` → `running` ⇄ `paused` → `succeeded` | `failed` | `cancelled`.

- **Terminal guarantee.** Once the `RunManager` exists, every exit path of `run_pipeline_ir_async` (success, exception, `asyncio.CancelledError`, bad partial-run ids) leaves the run terminal, tears down every executor that was set up, and deregisters the run — no `running` ghosts. Partial-run ids (`include_nodes` / `exclude_nodes`) are validated *before* the run is registered.
- **Compare-and-set status writes.** `mark_running` / `pause` / `resume` / `save_metadata` (succeeded) / `mark_failed` / `mark_cancelled` go through `RunManager._transition_status` under the meta lock and the `run_status` transition matrix. The **first terminal status wins**: a late `mark_failed` never overwrites `succeeded`/`cancelled`, `save_metadata` on a cancelled run merges the fields but keeps `cancelled` (and emits no success notification). These methods return `bool` (True = written).
- **Durable cancel marker.** `RunManager.cancel()` (and the API offline cancel of a queued run in another process) writes `runs/<run_id>/cancel_requested` via `write_cancel_marker()`. The marker is never rewritten, so it cannot be lost to a racing `meta.json` write; while it exists every transition except `cancel` is refused. `is_cancelled` checks the in-process event plus (throttled to one probe / 0.5 s) the marker / durable `status: cancelled`; `poll_cancelled()` is the unthrottled check used at node boundaries. A run cancelled while queued is never started.
- **Mode A cancel wiring.** The orchestrator installs `NodeExecutor.set_cancel_check` on every executor (terminates isolated plugin subprocesses, interrupts retry back-off). In-process `process()` still cannot be interrupted mid-call (`docs/KNOWN_ISSUES.md` DIST-CANCEL-1).
- **Event-driven runs.** The first failure or cancel closes every event source and cancels idle handler tasks; a later cancel never overwrites `failed`.

### Logical vs materialized graph

Before execution the graph is **run-scoped** (`_scope_graph_to_run` → `workspace_paths.scope_outputs_to_run`: output paths are rewritten under `workspace/artifacts/<slug>/runs/<run_id>/`). **No node writes at the run root:** a write sink (`output_path` / `output_dir` / `export_dir` / `dest_dir`) that scopes to `…/runs/<run_id>` (e.g. default plugin paths such as `workspace/artifacts/evaluation`) becomes `…/runs/<run_id>/<node_id>`, and other config strings pointing into it (`model_path` …) follow. Explicit sub-paths are kept (`…/runs/<id>/tflite`, so `latest/tflite/model.tflite` consumers stay valid); nodes that still share an identical sink get `/{node_id}` appended. Net effect: every writer has its own folder — parallel branches never share `model.tflite` / `labels.txt`. Run-level metrics fall back to a node folder's `metrics.json` (`read_metrics_tree`, evaluator-preferred). The logical graph is stored as `runs/<id>/graph.logical.json` (replay source). Because that materialized graph embeds the run id, its hash changes on every run. Therefore:

| Key | Derived from |
|---|---|
| `meta.json` `graph_hash` / `RunManager._graph_hash` (resume validation, checkpoint index, provenance) | **logical** graph — `_logical_graph_hash(graph)` = SHA-256 of `dump_ir(graph)` before scoping |
| `meta.json` `materialized_graph_hash` | the executed graph (`graph.json`), only when it differs |
| Node seeds | `planner.derive_node_seed(graph_seed, node_type, index, logical_config)` — `PipelineGraph(..., seed_configs=logical_configs)` |
| Cache keys | logical node config |
| Node execution config | materialized (run-scoped) config |

`RunManager.save_graph_ir(graph_dict, *, logical_hash=None)` writes `graph.json` (materialized) and sets `graph_hash` to `logical_hash` when given. Custom run managers without the keyword still work (falls back to the materialized hash). **Mode B:** `DistributedBackend` applies the same contract — scopes outputs to the run, saves the logical hash, derives per-node seeds with `derive_node_seed` (identical to Mode A; `NodeJob.seed` carries it) and keys the cache off the logical config.

### Run audit record (`app/core/runs/audit_record.py`)

- **Run start** (`orchestrator.capture_run_start`, also Mode B): writes `graph.logical.json` and meta `node_implementations` / `plugin_version` / `plugin_code_hashes` (plugin name + version from the runtime registry / installed manifest / PluginStore, sha256 of the plugin source tree cached by stat signature), `environment_info`, `external_inputs` + `dataset_versions` (content hashes of every external path node configs read; `audit_hashing.hash_path`, per-file cache keyed by (path, mtime_ns, size), `manifest` mode for huge trees), `pipeline_ref` / `pipeline_source` (declared or content-hash match against the project's saved draft / versions), `node_labels` (`run_summary.node_labels`, installed on the logger so `node_*` events carry `node_label`). Interfaces stamp `actor` / `trigger` (+ declared `lineage` → meta `lineage_request`) first (`graph_prepare.persist_run_identity`). `environment_info` = `run_environment(impls)`: host env (container / image / git via env → `BUILD_INFO.json` → `.git`) plus `plugin_environments` (per isolated-plugin venv library versions + freeze hash, cached per venv + site-packages mtime). External inputs are named (`node_label · key`, code-string path literals as `source:<key>`) and exclude write-sink keys, the graph's output locations and the run's own scope.
- **Terminal transition** (`RunManager.save_metadata` / `mark_failed` / `mark_cancelled`, first one only): `seal_run_record` writes `prove.json` (schema 2.0: + `lineage` (source run + registered models declared or read as inputs, with model hash), `input_artifact_hashes` (consumed, never own outputs), `outputs` per-node folder hashes, `outputs_manifest.json` sidecar, `cache` provenance, status / error) and appends `{seq, run_id, record_hash, prev}` to `workspace/audit/chains/<project>.jsonl` (file-locked); `record_hash` = sha256 of the canonical record (which includes `previous_record_hash`). Then audit `run.finish` / `run.fail` / `run.cancel` with the run's actor.
- **Failures** record the real exception: `mark_failed(..., error_type=, error_traceback=)`; isolated plugin workers write a structured `error.json` (`IsolatedNodeError`: `error_type`, `error_message`, `traceback_text`; stderr fallback takes the last traceback block and filters absl/TF noise).
- **Cache provenance:** `PipelineCache.save(key, outputs, source={run_id, node_id, saved_at})` stores the producing run in the entry manifest; a hit records `cache_key` + `cache_source_run_id` in `node_stats`.
- `verify_run` / `GET /runs/{id}/verify`, `run_replay.start_replay` / `POST /runs/{id}/replay` and `run_archive` (`DELETE` = archive) are described in `docs/API_REFERENCE.md`.

---

## `PipelineCache`

**File:** `app/core/execution/pipeline_cache.py`

Caches node outputs under `workspace/cache/{sha256}/`. Domain-agnostic — uses `ArtifactSerializerRegistry.infer_type()` to detect serializable output types; no domain model imports.

```python
cache = PipelineCache()

# Canonical key computation (shared by sequential and parallel executors)
key = cache.compute_key(
    node_type, config_dict, inputs,
    node_seed=node.seed, node_version=registry.get_metadata(node_type).version,
)

# Load — treat None as a miss; never call has() first (TOCTOU hazard)
cached = cache.load(key)   # returns outputs dict or None

# Save (source = audit provenance; hits report cache_source_run_id)
cache.save(key, outputs, source={"run_id": run_id, "node_id": node_id})
cache.source_of(key)   # {"run_id", "node_id", "saved_at"} | None

# Clear all
stats = cache.clear()  # {"entries_deleted": N, "bytes_freed": N}
```

### Cache key

`SHA-256(node_type + sorted_json(config) + combined_input_hash)` (plus node seed and node version) where `combined_input_hash` is `SHA-256` of all per-port input hashes concatenated (preserves port identity). Input values are digested by full content (Pydantic models field-by-field, ndarrays by dtype/shape/bytes, containers recursively); a value with no stable content representation makes the node uncacheable for that call (it re-executes). The orchestrator and the distributed backend key the cache off the **logical** node config (pre run-scoping), so run-scoped output paths do not defeat the cache.

**Run-local hits** (`app/core/execution/cache_rescope.py`). A cached output may embed the recording run's paths (`…/artifacts/<slug>/runs/<old_id>/…`, e.g. `model_builder`'s compiled `.keras`). On a hit, every such path string (dicts / lists / tuples / `Path` / pydantic fields) is rewritten to the current run id and the referenced file/dir is copied into the current run's artifact dir. If that is impossible — the source was deleted, the path is inside free text, or one string names several runs — the hit is discarded and the node re-executes. Sequential, parallel and distributed paths all apply this.

**Non-cacheable nodes never hit.** `cacheable` (plugin `NodeMetadata`, incl. isolated stubs whose metadata is read from the plugin's `NodeMetadata(...)` literal, merged with IR overrides via `resolve_capability`) is checked **before** `cache.load`, so an entry written while a node was wrongly cacheable is never served; such nodes also never save.

### Cache format

```
workspace/cache/{sha256}/
├── manifest.json         # commit marker, always written:
│                         #   all_ports, json_ports, cached_ports, port_types,
│                         #   source {run_id, node_id, saved_at}
├── outputs.json          # JSON-serializable ports (plain values / model_dump)
└── port_{name}/          # ports with an ArtifactSerializerRegistry handler
    ├── 0.wav … N.wav
    └── manifest.json
```

Entries are **all-or-nothing**: if any output port cannot be serialized nothing is written (logged; mark the node `cacheable=False` to silence), and `load()` returns a hit only when every port in `all_ports` is restored. Entries are assembled in a staging dir and renamed into place; manifests without the full port inventory are misses.

---

## Checkpoints

**File:** `app/core/runs/checkpoint.py`

When `checkpoint=True`, after each node executes, `_write_checkpoint()` writes the node's serializable output ports to:

```
workspace/runs/{run_id}/checkpoints/node_{node_id}/
├── port_{name}/
│   ├── 0.wav … N.wav
│   └── manifest.json
└── manifest.json    # {"checkpointed_ports": [...], "port_types": {...}}
```

All I/O is delegated to `ArtifactSerializerRegistry` handlers — no domain-model knowledge in `checkpoint.py`. Ports with no registered handler are skipped with a warning (they re-execute on resume).

A per-node O(1) index (`runs/checkpoints/node_{id}/latest_run`) is maintained for fast checkpoint lookup. Falls back to O(N) full-run-directory scan if the index is absent or stale.

Checkpoints are accessible via `GET /api/v1/runs/{run_id}/checkpoints` and via the MCP `inspect_run` tool.

## Run Directory Structure

```
workspace/runs/{run_id}/
├── meta.json           # Run metadata (status, timing, node_stats, actor, trigger, node_labels, …)
├── logs.json           # NDJSON event log (node events carry node_label)
├── graph.json          # materialized (run-scoped) GraphIR JSON (always written)
├── graph.logical.json  # logical graph (graph_hash source; replay input)
├── prove.json          # sealed audit record (schema 2.0) — every terminal run
├── outputs_manifest.json  # per-file output hashes (verify diffs)
├── .archived           # present when the run is archived (DELETE default)
├── resume_state.json   # written when checkpoint=True
└── checkpoints/        # Per-node checkpoints (when checkpoint=True)
    └── node_{id}/
        ├── port_{name}/
        │   ├── *.wav
        │   └── manifest.json
        └── manifest.json
```

`graph.json` is written by `RunManager.save_graph_ir()` immediately after execution starts. `resume_state.json` tracks completed node IDs and the graph hash — used to validate that the graph has not changed before resuming.

---

## `validate_pipeline()`

**File:** `app/core/execution/validation.py`

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

### `validate_graph_ir_result(graph, registry)` — Graph IR findings

Returns `{valid, errors, warnings}`; each finding has a stable `code` (see `docs/REQUIREMENTS_SPEC.md` VAL table). Codes emitted today: `VAL-DUP-ID`, `VAL-EMPTY`, `VAL-UNK-TYPE`, `VAL-CONFIG`, `VAL-MISS-NODE`, `VAL-MISS-PORT`, `VAL-TYPE`, `VAL-CYCLE`, `VAL-UNREACH`, plus:

| Code | Severity | Meaning |
|---|---|---|
| `VAL-COND` | error | Edge `condition` fails length (≤500), syntax or AST-whitelist check (`conditions.validate_condition_syntax`, no evaluation) |
| `VAL-CARDINALITY` | error / warning | Several edges into a `cardinality="single"` input port (runtime would keep only the last value). **Warning** instead of error when the fan-in looks like a merge of mutually exclusive branches (an edge carries a condition, or a source descends from a node routing through >1 distinct output ports) |
| `VAL-UNCONNECTED-INPUT` | warning | Required input port with no incoming edge — warning only, since source nodes are commonly fed via runtime `input_overrides` (templates, SDK `Pipeline.run`) |

Condition semantics at runtime (`app/core/execution/conditions.py`): `*` and `%` are **numeric-only** (no `"a" * 10**9` string/list repetition, no printf-style `%` formatting) and integer products are capped (`_MAX_INT_BITS`); violations raise `ConditionEvaluationError`.

---

## `stable_hash()`

**File:** `app/core/utils/hash.py`

Deterministic hash used for node seeds and export file IDs. Takes any number of arguments, converts them to strings, and returns a stable integer hash. The same inputs always produce the same output across Python runs.
