---
inclusion: fileMatch
fileMatchPattern: "app/core/orchestrator.py,app/core/planner.py,app/core/node_executor.py,app/core/checkpoint.py,app/core/executor.py,app/core/pipeline.py,app/core/validation.py,app/core/pipeline_cache.py,app/core/ir/**,app/core/conditions.py,app/core/events.py"
---

# Pipeline Execution

## Graph IR (`app/core/ir/`)

```python
from app.core.ir import GraphIR, IRNode, IREdge, IRMetadata, IRCapabilityMetadata
from app.core.ir import load_ir, dump_ir, load_ir_from_file, dump_ir_to_file
from app.core.ir import CURRENT_IR_VERSION  # "1.1"
```

**Schema versions:** `"1.0"` and `"1.1"` both accepted. `"1.0"` docs load as `"1.1"` with Phase 3 fields defaulting to `None`.

| Version | Changes |
|---|---|
| `"1.0"` | Initial schema (Phase 1/2) |
| `"1.1"` | `IREdge.condition` (optional str), `IRNode.event_trigger` (optional dict) |

**Key models:**
```python
IRNode(id, node_type, config={}, label=None, capability_metadata=None, event_trigger=None)
IREdge(src_id, src_port, dst_id, dst_port, condition=None)
IRCapabilityMetadata(requires_gpu=False, supports_cpu=True, supports_edge=False,
    deterministic=True, cacheable=True, streaming_support=False, realtime_support=False,
    memory_requirements=None, dependency_requirements=[], batch_support=False)
```

**Two-step capability resolution:** (1) `IRNode.capability_metadata` if non-null; (2) `NodeMetadata` from registry.

## Execution Entry Points

```python
# Synchronous (primary public API) — MUST NOT be called from an async context.
# If a running event loop is detected, raises RuntimeError directing the caller
# to use `await run_pipeline_ir_async(...)` instead (G2-01).
result = run_pipeline_ir(graph, logger=None, use_cache=True, checkpoint=False,
    streaming=False, parallel=False, observer=None, run_manager=None,
    max_workers=None, resume_run_id=None, include_nodes=None,
    exclude_nodes=None, input_overrides=None, event_driven=False)

# Async-native (Phase 3) — awaitable from existing event loops
result = await run_pipeline_ir_async(graph, ..., event_loop=None)
```

All new parameters default to `False`/`None` — existing call sites unchanged.

## `PipelineGraph`

```python
graph = PipelineGraph(config, observer=None)
graph.execution_order   # list[str] — topo-sorted (flattened waves)
graph.execution_waves   # list[list[str]] — parallel waves (cached at build time)
graph.get_node(node_id) # → Node instance
```

Wave 0 = source nodes; each subsequent wave = nodes whose predecessors are all in earlier waves.

## Phase 3 Runtime Modes

**Parallel** (`parallel=True`): `ParallelExecutor` (`app/core/executor.py`) runs each wave with `asyncio.gather` + `ThreadPoolExecutor`. Emits `wave_start`/`wave_end` events. Respects `cacheable=False`.

**Resumability** (`resume_run_id="<id>"`): loads `resume_state.json` from prior run, skips completed nodes, loads checkpoint outputs. `ResumeError` (from `app.core.nodes.errors`) raised for missing/malformed state.

**Partial execution** (`include_nodes=[...]` or `exclude_nodes=[...]`): mutually exclusive. Boundary nodes source inputs from `input_overrides` → `find_latest_checkpoint` → `None`.

**Conditional branching** (`IREdge.condition`): evaluated via `evaluate_condition(expr, src_outputs)` in `app/core/conditions.py`. False condition → `None` on dst port; required port receiving `None` → `node_skip(reason="condition_false")`. Allowed: comparisons, boolean ops, `len()`, subscript on `output`. Disallowed: imports, arbitrary function calls.

**Event-driven** (`event_driven=True`): binds nodes with `event_trigger` to `EventSource` instances (`app/core/events.py`). Runs indefinitely until cancelled. Sources: `FileWatcherSource`, `TimerSource`, `QueueSource`.

- `FileWatcherSource` passes `stop_event` to `watchfiles.awatch` and sets it in `close()` — prevents segfault on process exit from the Rust watcher thread.
- Cancellation: a `_cancel_watcher` task polls `run.is_cancelled` every 0.2s and calls `src.close()` on all sources, which unblocks `_handle_source` loops. Always call `run_manager.cancel()` to stop event-driven pipelines; do not rely on `thread.join()` alone.

**Runtime control**: `RunManager.pause()` / `resume()` / `cancel()` — checked between nodes. Active runs tracked in `_ACTIVE_RUNS` registry.

**Unified `run_id`**: `run_pipeline_ir_async` uses `run.run_id` (the 16-char hex string from `RunManager`) as the single `run_id` passed to every `NodeExecutor`. Observer callbacks (`on_node_start`, `on_node_end`, `on_node_error`) and `meta.json` both carry the same value — they are always correlated.

## `PipelineCache`

```python
key = cache.key(node_type, config_dict, cache.input_hash(samples))
if cache.has(key): samples = cache.load(key)
cache.save(key, samples)
```

Key: `SHA-256(node_type + sorted_json(config) + input_hash)`. Location: `workspace/cache/{sha256}/`. Only caches list-valued outputs.

## Run Directory Structure

```
workspace/runs/{run_id}/
├── meta.json           # status, timing, node_stats; gains resume/partial fields
├── logs.json           # NDJSON event log
├── graph.json          # GraphIR JSON (always written)
├── resume_state.json   # when checkpoint=True
└── checkpoints/node_{id}/*.wav + manifest.json
```

## Phase 4 Artifact Lineage

`Pipeline.run()` returns an `ArtifactCollection` (not a plain dict). The sequential and parallel executors both call `run_manager.register_artifact()` after each node completes, wiring the full provenance chain.

```python
result = pipeline.run(use_cache=False)
result.run_id                          # str — run ID
result.artifacts                       # list[ArtifactRecord] — one per node output port
result.get_by_type("audio_samples")    # filter by artifact_type
result.lineage(artifact_id)            # full upstream provenance tree (dict)

from app.core.artifact_store import ArtifactStore
store = ArtifactStore()
store.list(run_id=result.run_id)       # query by run
store.get(artifact_id)                 # fetch single record
```

**Artifact type inference** (`_infer_artifact_type` in `artifact_store.py`, imported by `pipeline.py` and `executor.py`):
- `list` of objects with `.data` + `.sample_rate` → `"audio_samples"`
- object with `.X_train` (DatasetArtifact) → `"generic"`
- `numpy.ndarray` → `"feature_array"`
- everything else → `"generic"`

**Pass-through deduplication**: if a node outputs the same content as its input (same content hash → same `artifact_id`), provenance is not re-written — the upstream record is preserved. This prevents false cycle detection in `ProvenanceStore.get_lineage()`.

**Deduplication with run stamping**: `ArtifactStore.register()` returns a copy of the existing record stamped with the current `run_id`/`node_id`/`node_type`, so `store.list(run_id=...)` always finds artifacts for the current run even when data is identical to a prior run.

**Numpy serialization**: `ArtifactStore._serialize_json()` and `_compute_content_hash()` use `model_dump()` (not `mode="json"`) + a `_numpy_default` JSON encoder to handle `numpy.ndarray` fields in Pydantic models with `arbitrary_types_allowed=True`.

## Pipeline Module Structure

`pipeline.py` is a re-export shim. The real implementations are:

| File | Responsibility |
|---|---|
| `orchestrator.py` | Main async entry point — coordinates all execution modes |
| `planner.py` | DAG builder, topological sort, wave planner |
| `node_executor.py` | Drives a single node through its lifecycle with retry |
| `checkpoint.py` | Checkpoint read/write for resumable execution (audio-domain only — ARCH-3) |
| `executor.py` | Parallel wave executor using `asyncio.gather` + `ThreadPoolExecutor` |

## Open Issues in This Area

> See `docs/MASTER_ISSUE_REGISTRY.md` for full details and fixes.

| ID | Severity | Summary |
|---|---|---|
| NEW-4 | High | Parallel executor silently ignores all edge conditions |
| NEW-5 | High | `node_stats` list mutated concurrently without a lock |
| SA-O1 | High | `node_outputs` compound read-modify-write not GIL-safe |
| SA-O2 | High | `deregister_active_run` not called on event-driven exception path |
| SA-O7 | High | Resume does not validate graph hash |
| SA-O4 | Medium | Excluded node passthrough overwrites multi-port outputs |
| SA-C2 | Medium | Non-audio nodes silently not checkpointed |
| NEW-6 | Medium | `input_hash` loses port identity for multi-port nodes |
| SA-C1 | Medium | Checkpoint path traversal guard follows symlinks |
| SA-P1 | Low | Legacy YAML parser silently drops edge `condition` field |
| SA-P2 | Low | `_compute_waves` is O(N²) for deep linear pipelines |