# Backend Core Services

Supporting services used by the API routers and pipeline executor.

**See also:** [ARCHITECTURE.md](./ARCHITECTURE.md) | [DOMAIN_SERVICES.md](./DOMAIN_SERVICES.md) | [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md)

---

## Table of Contents

1. [RunJournal (RunManager)](#1-runjournal-runmanager)
2. [RunControl](#2-runcontrol)
3. [PipelineLogger](#3-pipelinelogger)
4. [ArtifactSerializerRegistry](#4-artifactserializerregistry)
5. [ArtifactStore](#5-artifactstore)
6. [ProvenanceStore](#6-provenancestore)
7. [PipelineCache](#7-pipelinecache)
8. [WebhookService](#8-webhookservice)
9. [stable_hash()](#9-stable_hash)

---

## 1. RunJournal (RunManager)

**File:** `app/core/run_journal.py`  
**Class:** `RunManager`

Manages filesystem persistence for a single pipeline run. Creates the run directory on construction and writes an initial `meta.json` so the run appears in history even if the pipeline fails before completion.

```python
from app.core.run_journal import RunManager

run = RunManager()
run.run_id      # full 32-char UUID4 hex, e.g. "a1b2c3d4e5f6..."
run.base_path   # "workspace/runs/{run_id}"
```

### Methods

| Method | Description |
|---|---|
| `save_graph_ir(graph_data)` | Write `graph.json` atomically (tmp+rename). Computes and stores `self._graph_hash`. |
| `save_config(yaml_str)` | Write `config.yaml` to the run directory. |
| `save_logs(logs)` | Write `logs.json` (list of log entry dicts). |
| `save_metadata(metadata)` | Merge caller metadata with run bookkeeping fields; write `meta.json` with `status: "completed"`. |
| `mark_failed(error)` | Update `meta.json` with `status: "failed"` and `error` field. Thread-safe. |
| `mark_cancelled()` | Update `meta.json` with `status: "cancelled"`. Thread-safe. |
| `pause()` | Clear pause event; write `status: "paused"` to `meta.json`. |
| `resume()` | Set pause event; write `status: "running"` to `meta.json`. |
| `cancel()` | Set cancel event; unblock if paused. |
| `wait_if_paused()` | Block until pause event is set (called by executor between nodes). |
| `is_paused` | `bool` property. |
| `is_cancelled` | `bool` property. |
| `init_resume_state(graph_hash)` | Write `resume_state.json` with empty `completed_nodes` list. |
| `update_resume_state(node_id)` | Append `node_id` to `completed_nodes` in `resume_state.json`. Warns if file missing. |
| `load_resume_state(run_id)` | Load `resume_state.json` from a prior run. Raises `ResumeError` on failure. |
| `find_latest_checkpoint(node_id)` | Delegates to `checkpoint._find_latest_checkpoint()`. Returns outputs dict or `None`. |
| `register_artifact(node_id, node_type, artifact_type, data, metadata=None, input_artifact_ids=None, name=None)` | Store artifact via `ArtifactStore`, record lineage via `ProvenanceStore`. Returns `ArtifactRecord`. |
| `artifacts` | Thread-safe snapshot of registered `ArtifactRecord` list. |
| `get_provenance_summary()` | Returns `{"run_id", "graph_hash", "artifacts", "provenance_records"}`. |
| `compute_graph_hash(graph_ir)` | Static method. SHA-256 of `dump_ir(graph_ir)` JSON. |

### `meta.json` structure

Written immediately on construction (`status: "running"`), updated on completion or failure:

```json
{
  "run_id": "a1b2c3d4e5f6...",
  "created_at": "2026-05-28T12:00:00+00:00",
  "status": "completed",
  "duration_s": 1.234,
  "num_nodes": 5,
  "node_stats": [
    {"node_id": "cond_0", "node_type": "AudioConditionerNode", "node_index": 0, "duration_s": 0.1}
  ]
}
```

All timestamps are UTC-aware ISO 8601 strings. All writes are atomic (tmp+rename on POSIX). All meta.json updates are protected by `_meta_lock` to prevent concurrent write loss.

### Run directory layout

```
workspace/runs/{run_id}/
├── meta.json           # run metadata (status, timing, node stats)
├── logs.json           # all log entries
├── graph.json          # GraphIR JSON (always written)
├── resume_state.json   # written when checkpoint=True
└── checkpoints/        # only when checkpoint=True
    └── node_{node_id}/
        ├── port_{name}/
        │   ├── *.wav
        │   └── manifest.json
        └── manifest.json
```

---

## 2. RunControl

**File:** `app/core/run_control.py`

Active run registry. Maps `run_id → RunManager` for pause/resume/cancel signal delivery. Separate from `RunJournal` — this module owns the in-memory (or Redis-backed) registry of currently executing runs; `RunJournal` owns filesystem persistence.

`app/core/run_manager.py` is a **re-export shim** for backward compatibility. New code should import `RunManager` from `run_journal` and control functions from `run_control` directly.

### Public API

```python
from app.core.run_control import (
    register_active_run,
    get_active_run,
    deregister_active_run,
    is_active_on_another_worker,
)

register_active_run(run)          # called by orchestrator at execution start
run = get_active_run(run_id)      # returns RunManager or None
deregister_active_run(run_id)     # called in finally block after execution
on_another = is_active_on_another_worker(run_id)  # True only in Redis mode
```

| Function | Description |
|---|---|
| `register_active_run(run)` | Store `RunManager` in in-process dict. In Redis mode, also writes `graphyn:active_run:{run_id}` with 24h TTL. |
| `get_active_run(run_id)` | Return `RunManager` from in-process dict, or `None`. In Redis mode, logs a debug note if the run is active on another worker. |
| `deregister_active_run(run_id)` | Remove from in-process dict and Redis. Called in `finally` block. |
| `is_active_on_another_worker(run_id)` | Returns `True` if run is in Redis but not in this process. Always `False` in single-worker mode. |

### Scalability

When `GRAPHYN_REDIS_URL` is set, run registrations are stored in Redis so any worker can distinguish "run is on another worker" (return 503) from "run does not exist" (return 404). The `RunManager` object itself is always in the in-process dict — control signals cannot be routed cross-process from here.

In single-worker mode (default), the in-process dict is used — identical behavior to a simple dict.

---

## 3. PipelineLogger

**File:** `app/core/logger.py`

Structured event logger for pipeline execution. Emits both plain-text log entries and typed JSON events.

```python
from queue import Queue
queue = Queue()
logger = PipelineLogger(queue=queue)   # queue is optional; used for streaming
```

When a `queue` is provided, every event is put onto the queue via `put_nowait()` (non-blocking) for streaming to API consumers. A full queue drops the event rather than blocking execution.

### Methods

| Method | Emits |
|---|---|
| `pipeline_start(total_nodes, partial, included_nodes)` | `{"type": "pipeline_start", "total_nodes": N, ...}` |
| `node_start(node_type, index, total_nodes)` | `{"type": "node_start", "node_type": "...", "node_index": N, ...}` |
| `node_end(node_type, index, duration, output_count)` | `{"type": "node_end", "duration": 0.123, "output_count": 42, ...}` |
| `node_error(node_type, index, error)` | `{"type": "node_error", "error_message": "...", "error_type": "ValueError", ...}` |
| `node_skip(node_id, node_type, reason)` | `{"type": "node_skip", "reason": "resumed_from_checkpoint" \| "excluded_from_partial_execution" \| "condition_false", ...}` |
| `wave_start(wave_idx, wave)` | `{"type": "wave_start", "wave_index": N, "node_ids": [...], ...}` |
| `wave_end(wave_idx, wave, duration)` | `{"type": "wave_end", ...}` |
| `pipeline_cancelled(run_id, completed, remaining)` | `{"type": "pipeline_cancelled", ...}` |
| `event_received(source_type, node_id, payload_keys)` | `{"type": "event_received", ...}` |
| `pipeline_done(run_id, duration)` | `{"type": "done", "run_id": "...", "duration_s": 0.123, ...}` — MCP terminal event |
| `pipeline_error(message)` | `{"type": "error", "message": "...", ...}` — MCP terminal event |
| `info(msg)` | Plain log at INFO level |
| `error(msg)` | Plain log at ERROR level |

All entries are appended to `logger.logs`. After the run, `run.save_logs(logger.logs)` persists them to `logs.json`.

---

## 4. ArtifactSerializerRegistry

**File:** `app/core/artifact_serializer.py`

Pluggable serializer registry that decouples platform storage infrastructure from domain-specific serialization logic. Platform code calls the registry; domain code registers handlers at startup.

```python
# Domain registration — call once at each entry point startup
from app.models.audio_artifact_serializer import register_audio_serializer
register_audio_serializer()

# Registry access (used internally by artifact_store, pipeline_cache, checkpoint)
from app.core.artifact_serializer import get_serializer_registry
registry = get_serializer_registry()
handler = registry.get("audio_samples")   # None if not registered
```

### `ArtifactTypeHandler` ABC

Implement to add a new serializable type:

| Method | Description |
|---|---|
| `serialize(data, dest_dir)` | Write data to `dest_dir` (guaranteed to exist). Raise on failure. |
| `deserialize(src_dir) → Any \| None` | Read data from `src_dir`. Return `None` on miss (cache/checkpoint miss). |
| `compute_content_hash_input(data) → str` | Stable string for SHA-256 deduplication. Must be deterministic across process restarts. |
| `infer_type(value) → str \| None` | Return artifact_type string if value matches; `None` otherwise. |

### `ArtifactSerializerRegistry` methods

| Method | Description |
|---|---|
| `register(artifact_type, handler)` | Register handler. Thread-safe. Replaces existing handler for same type. |
| `get(artifact_type) → handler \| None` | Return handler or `None`. |
| `infer_type(value) → str \| None` | Ask each handler in registration order. Returns first non-None result. Primitives fast-path to `None`. |
| `registered_types() → list[str]` | Sorted list of registered type strings. |

### Fail-open design

If no handler is registered for a type:
- `artifact_store` falls back to JSON serialization
- `pipeline_cache` and `checkpoint` log a warning and treat it as a miss (node re-executes)

The platform works without any domain handlers installed — it just cannot serialize domain-specific types.

**See also:** [DOMAIN_SERVICES.md — AudioSampleHandler](./DOMAIN_SERVICES.md#4-audiosamplehandler)

---

## 5. ArtifactStore

**File:** `app/core/artifact_store.py`

Content-addressed artifact storage under `workspace/artifacts/`.

```python
from app.core.artifact_store import ArtifactStore

store = ArtifactStore()
record = store.register(
    run_id="...", node_id="...", node_type="...",
    artifact_type="audio_samples", data=samples,
    metadata={"port": "output"}, name=None,
)
# record.artifact_id, record.content_hash, record.data_path

records = store.list(run_id="...", limit=200)
record = store.get(artifact_id="...")
data = store.load(artifact_id="...")
```

### Storage layout

```
workspace/artifacts/{artifact_id}/
├── record.json    # ArtifactRecord (id, run_id, node_id, type, content_hash, ...)
└── data/
    ├── manifest.json   # for registered types (e.g. audio_samples)
    └── *.wav           # or data.json for unregistered types
```

`workspace/artifacts/index.json` — flat index for fast listing and deduplication by `content_hash`.

---

## 6. ProvenanceStore

**File:** `app/core/provenance.py`

Lineage tracking for artifacts.

```python
from app.core.provenance import ProvenanceStore

store = ProvenanceStore()
store.record(
    artifact_id="...", run_id="...", node_id="...", node_type="...",
    graph_hash="...", input_artifact_ids=["..."],
)
lineage = store.get_lineage(artifact_id="...")  # recursive tree dict
records = store.find_by_run(run_id="...")
```

### Storage layout

```
workspace/provenance/{artifact_id}.json   # ProvenanceRecord
workspace/provenance/by_run/{run_id}.json # list of artifact_ids for this run
```

`get_lineage()` never raises — missing records produce error nodes in the tree.

---

## 7. PipelineCache

**File:** `app/core/pipeline_cache.py`

See [PIPELINE_EXECUTION.md — PipelineCache](./PIPELINE_EXECUTION.md#pipelinecache) for full details.

---

## 8. WebhookService

**File:** `app/core/webhook.py`

Manages webhook configuration and outbound notifications.

```python
from app.core.webhook import WebhookService

svc = WebhookService()
config = svc.load()                          # {"url": "...", "events": [...]}
svc.save(url="https://...", events=["..."])  # writes workspace/webhooks.json
svc.notify("pipeline_complete", {"run_id": "..."})  # fires HTTP POST
```

Webhook config is stored in `workspace/webhooks.json`. DNS is resolved once per notification; the connection is made directly to the resolved IP with the original `Host` header (DNS rebinding fix).

---

## 9. stable_hash()

**File:** `app/core/utils/hash.py`

Deterministic hash function used for node seeds and export file IDs.

```python
from app.core.utils.hash import stable_hash

# Node seed
node_seed = stable_hash(pipeline_seed, node_type, node_index, config_str) % 2**32

# Export file ID
file_id = stable_hash(path, len(data), label, start, end, augmented, augmentation_id)
```

Returns a stable integer. The same inputs always produce the same output across Python runs (unlike Python's built-in `hash()` which is randomized per process). Non-serializable objects raise `TypeError` — they are not silently converted to memory-address strings.
