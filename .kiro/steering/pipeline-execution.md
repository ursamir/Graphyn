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
# Canonical entry point — all interfaces use get_backend().execute()
from app.core.runtime_backend import get_backend
result = get_backend().execute(graph, logger=None, use_cache=True, checkpoint=False,
    streaming=False, parallel=False, observer=None, run_manager=None,
    max_workers=None, resume_run_id=None, include_nodes=None,
    exclude_nodes=None, input_overrides=None, event_driven=False)

# Direct orchestrator access (internal / backward compat only)
# Synchronous — MUST NOT be called from an async context.
result = run_pipeline_ir(graph, ...)

# Async-native (Phase 3) — awaitable from existing event loops
result = await run_pipeline_ir_async(graph, ...)
```

**`RuntimeBackend` is the canonical execution entry point.** All interfaces (SDK, API, MCP, CLI) call `get_backend().execute()`. `run_pipeline_ir` is an implementation detail of `LocalPythonBackend` — new code must not import it directly. Custom backends can be registered via `register_backend(id, BackendClass)`.

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

**Resumability** (`resume_run_id="<id>"`): loads `resume_state.json` from prior run, skips completed nodes, loads checkpoint outputs. `ResumeError` (from `app.core.errors`) raised for missing/malformed state.

**Partial execution** (`include_nodes=[...]` or `exclude_nodes=[...]`): mutually exclusive. Boundary nodes source inputs from `input_overrides` → `find_latest_checkpoint` → `None`.

**Conditional branching** (`IREdge.condition`): evaluated via `evaluate_condition(expr, src_outputs)` in `app/core/conditions.py`. False condition → `None` on dst port; required port receiving `None` → `node_skip(reason="condition_false")`. Allowed: comparisons, boolean ops, `len()`, subscript on `output`. Disallowed: imports, arbitrary function calls.

**Event-driven** (`event_driven=True`): binds nodes with `event_trigger` to `EventSource` instances (`app/core/events.py`). Runs indefinitely until cancelled. Sources: `FileWatcherSource`, `TimerSource`, `QueueSource`.

- `FileWatcherSource` passes `stop_event` to `watchfiles.awatch` and sets it in `close()` — prevents segfault on process exit from the Rust watcher thread.
- Cancellation: a `_cancel_watcher` task polls `run.is_cancelled` every 0.2s and calls `src.close()` on all sources, which unblocks `_handle_source` loops. Always call `run_manager.cancel()` to stop event-driven pipelines; do not rely on `thread.join()` alone.

**Runtime control**: `RunManager.pause()` / `resume()` / `cancel()` — checked between nodes. Active runs tracked in `_ACTIVE_RUNS` registry.

**Unified `run_id`**: `run_pipeline_ir_async` uses `run.run_id` (the full 32-char UUID4 hex from `RunManager`) as the single `run_id` passed to every `NodeExecutor`. Observer callbacks (`on_node_start`, `on_node_end`, `on_node_error`) and `meta.json` both carry the same value — they are always correlated.

## `PipelineCache`

```python
# Canonical key computation — use compute_key() to avoid duplication
key = cache.compute_key(node_type, config_dict, inputs)   # preferred
# or manually:
key = cache.key(node_type, config_dict, cache.input_hash(samples))
cached = cache.load(key)   # None = miss; never call has() first (TOCTOU)
cache.save(key, outputs)
```

Key: `SHA-256(node_type + sorted_json(config) + combined_input_hash)`. Location: `workspace/cache/{sha256}/`. `compute_key()` is the single canonical implementation shared by both sequential and parallel executors — never duplicate the hashing logic.

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

| File | Responsibility | BC |
|---|---|---|
| `orchestrator.py` | Main async entry point — coordinates all execution modes | BC5 |
| `planner.py` | DAG builder, topological sort, wave planner | BC4 |
| `node_executor.py` | Drives a single node through its lifecycle with retry | BC5 |
| `checkpoint.py` | Checkpoint read/write for resumable execution | BC6 |
| `executor.py` | Parallel wave executor using `asyncio.gather` + `ThreadPoolExecutor` | BC5 |
| `registry_runtime.py` | Registry singleton accessor + `resolve_capability()` | BC3 |

**Capability resolution** lives in `registry_runtime.resolve_capability(ir_node, registry)` — NOT in `orchestrator._resolve_capability`. The orchestrator keeps a backward-compat alias. All new callers (CLI, MCP handlers, executor) import from `registry_runtime` directly.

**RULE 1 enforcement:** `checkpoint.py` and `pipeline_cache.py` do NOT import `app.models` at module level. AudioSample detection uses `get_serializer_registry().infer_type()` — no duck-typing, no domain knowledge in platform infrastructure. This keeps the platform core domain-agnostic at import time.

## Open Issues in This Area

> All previously listed issues in this area have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.