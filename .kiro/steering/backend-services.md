---
inclusion: fileMatch
fileMatchPattern: "app/core/run_journal.py,app/core/run_control.py,app/core/run_manager.py,app/core/logger.py,app/core/artifact_store.py,app/core/provenance.py,app/core/webhook.py,app/core/utils/hash.py,app/domain/**"
---

# Backend Services

## `RunJournal` / `RunManager` (`run_journal.py`, `run_control.py`, `run_manager.py`)

`run_manager.py` is a re-export shim — import from it for backward compat, but the real implementations are:
- **`run_journal.py`** — filesystem persistence for a single run
- **`run_control.py`** — in-process active run registry

```python
from app.core.run_journal import RunManager   # canonical import
# or: from app.core.run_manager import RunManager  # shim — backward compat
run = RunManager()   # creates workspace/runs/{run_id}/, writes initial meta.json
run.run_id           # full 32-char UUID4 hex, e.g. "a1b2c3d4e5f6..."
run.base_path        # "workspace/runs/{run_id}"
```

| Method | Description |
|---|---|
| `save_config(yaml)` | Write `config.yaml` |
| `save_logs(logs)` | Write `logs.json` |
| `save_metadata(meta)` | Merge + write `meta.json` (status: completed) |
| `save_graph_ir(data)` | Write `graph.json`; sets `self._graph_hash` |
| `mark_failed(error)` | Write `meta.json` (status: failed) |
| `mark_cancelled()` | Write `meta.json` (status: cancelled) |
| `init_resume_state(graph_hash)` | Create `resume_state.json` |
| `update_resume_state(node_id)` | Append to `completed_nodes` |
| `load_resume_state(run_id)` | Load prior run's state; raises `ResumeError` |
| `find_latest_checkpoint(node_id)` | Delegates to `checkpoint._find_latest_checkpoint()` — returns `{"output": [...]}` or `None` |
| `pause()` / `resume()` / `cancel()` | Runtime control via `threading.Event` |
| `wait_if_paused()` | Blocks until resumed (called between nodes) |
| `is_paused` / `is_cancelled` | Properties |
| `compute_graph_hash(graph_ir)` | Static method; SHA-256 of `dump_ir(graph_ir)` JSON |
| `register_artifact(node_id, node_type, artifact_type, data, metadata=None, input_artifact_ids=None, name=None)` | Delegates to `ArtifactStore` + `ProvenanceStore`; returns `ArtifactRecord` |
| `get_provenance_summary()` | Returns `{"run_id", "graph_hash", "artifacts", "provenance_records"}` |

**Active run registry** (`run_control.py`): `register_active_run(run)`, `get_active_run(run_id)`, `deregister_active_run(run_id)`.

- **In-process mode** (default, `GRAPHYN_REDIS_URL` unset): module-level dict, process-local. Identical to previous behaviour.
- **Redis mode** (`GRAPHYN_REDIS_URL` set): run registrations are mirrored to Redis key `graphyn:active_run:{run_id}` (24-hour TTL). The `RunManager` object is always kept in the in-process dict for signal delivery within this worker. `get_active_run` checks the in-process dict first; if absent, checks Redis and logs a debug note when the run is active on another worker. Returns `None` in all not-found cases (SCALE-1 fix).

Returns `None` for unknown/completed/wrong-worker runs (ambiguity documented in docstring).

`ResumeError` is defined in `app.core.errors` (platform-level errors module) and re-exported from `app.core.nodes.errors` for backward compatibility.

`resume_state.json` schema: `{"schema_version": "1.0", "run_id": "...", "completed_nodes": [...], "graph_hash": "..."}`.

All timestamps: `datetime.now(timezone.utc).isoformat()`. Never use `datetime.utcnow()`.

## `PipelineLogger` (`logger.py`)

```python
logger = PipelineLogger(queue=Queue())  # queue optional — enables NDJSON streaming
```

| Method | Event type |
|---|---|
| `pipeline_start(total_nodes, partial, included_nodes)` | `pipeline_start` |
| `node_start(node_type, index, total_nodes)` | `node_start` |
| `node_end(node_type, index, duration, output_count)` | `node_end` |
| `node_error(node_type, index, error)` | `node_error` |
| `node_skip(node_id, node_type, reason)` | `node_skip` — reason: `resumed_from_checkpoint`, `excluded_from_partial_execution`, `condition_false` |
| `wave_start(wave_index, node_ids)` | `wave_start` — parallel mode only |
| `wave_end(wave_index, node_ids, duration_s)` | `wave_end` — parallel mode only |
| `event_received(source_type, node_id, payload_keys)` | `event_received` — event-driven mode only |
| `pipeline_paused(run_id)` | `pipeline_paused` |
| `pipeline_resumed(run_id)` | `pipeline_resumed` |
| `pipeline_cancelled(run_id, nodes_completed, nodes_remaining)` | `pipeline_cancelled` |
| `pipeline_done(run_id, duration)` | `done` |
| `pipeline_error(message)` | `error` |

## `IngestionService` (`ingestion.py`)

```python
svc = IngestionService()
job_id = svc.start_url_job(urls=[...], label="speech")
job_id = svc.start_hf_job(repo_id="...", split="train", audio_col="audio", label_col="sentence")
for event in svc.stream_job(job_id): ...
```

Downloads run in background daemon threads. Always use `job.append_progress(event)` — never `job.progress.append()` directly (not thread-safe).

**Label sanitization (G3-23):** All `label` values used as directory names are passed through `_sanitize_label(label)` before constructing `dest_dir`. This strips any character that is not alphanumeric, hyphen, or underscore, and truncates to 64 characters. An empty result falls back to `"default"`. A `Path.is_relative_to()` boundary check in `_run_hf_job` provides defence-in-depth against path traversal.

## Other Services

- `ProjectManager` (`app/domain/project_manager.py`) — full project lifecycle under `workspace/datasets/output/{project}/`
- `QualityChecker` (`app/domain/quality_checker.py`) — runs checks against `contract.json`, writes `quality_report.json`
- `IngestionService` (`app/domain/ingestion.py`) — URL and HuggingFace dataset download jobs. Job store is in-process by default; when `GRAPHYN_REDIS_URL` is set, completed job state is persisted to Redis (`graphyn:ingest_job:{id}` + `graphyn:ingest_events:{id}`, 24-hour TTL) enabling cross-worker streaming (SCALE-2 fix). `get_job()` checks in-process dict first, then falls back to Redis.
- `WebhookService` (`app/core/webhook.py`) — HTTP POST notifications; config at `workspace/webhooks.json`. DNS rebinding SSRF fixed: `_send()` re-validates resolved IP at send time (NEW-12).
- `stable_hash()` (`app/core/utils/hash.py`) — deterministic hash across Python runs; used for node seeds, export file IDs, split group ordering

## `ArtifactStore` (`artifact_store.py`)

Content-addressed, typed artifact registry. Stores `ArtifactRecord` metadata envelopes alongside serialized data on disk.

```python
store = ArtifactStore()          # base_dir defaults to config artifacts_dir().parent / "artifacts"
record = store.register(run_id, node_id, node_type, artifact_type, data)
record = store.get(artifact_id)
records = store.list(run_id=..., node_type=..., artifact_type=...)
versions = store.get_versions(artifact_name)
```

`_get_supported_artifact_types()` — returns a `frozenset[str]` of currently supported artifact type strings, derived dynamically from the `ArtifactSerializerRegistry` plus the built-in `"generic"` fallback. Replaces the old hardcoded `SUPPORTED_ARTIFACT_TYPES` constant.

`_infer_artifact_type(value)` — module-level helper that infers the correct `artifact_type` string from a node output value. Delegates entirely to `ArtifactSerializerRegistry.infer_type()` (domain handlers registered at startup). Falls back to `"generic"` if no handler recognises the value. Contains zero domain-specific heuristics. Import from `app.core.artifact_store`.

**Clean migration:** `SUPPORTED_ARTIFACT_TYPES` constant, `DatasetArtifact` inline import, and all dict-key/duck-typing heuristics (`"feature_array"`, `"train"`/`"val"`/`"test"`, `np.ndarray` check) have been removed from platform infrastructure. All type inference belongs in domain handlers registered via `ArtifactSerializerRegistry` at startup.

## `ArtifactSerializerRegistry` (`artifact_serializer.py`)

Pluggable serializer registry. Platform defines the interface; domain registers handlers at startup.

```python
# Platform interface (app/core/artifact_serializer.py)
from app.core.artifact_serializer import get_serializer_registry, ArtifactTypeHandler

# Domain registration — call once at startup from each entry point
from app.models.audio_artifact_serializer import register_audio_serializer
register_audio_serializer()

# Registry usage (called internally by artifact_store, pipeline_cache, checkpoint)
registry = get_serializer_registry()
handler = registry.get("audio_samples")   # None if not registered
handler.serialize(data, dest_dir)
data = handler.deserialize(src_dir)
artifact_type = registry.infer_type(value)
```

`ArtifactTypeHandler` ABC methods: `serialize(data, dest_dir)`, `deserialize(src_dir) → Any | None`, `compute_content_hash_input(data) → str`, `infer_type(value) → str | None`.

`AudioSampleHandler` (`app/models/audio_artifact_serializer.py`) — domain-side implementation for `audio_samples`. Owns WAV I/O, manifest format, and `AudioSample` duck-typing. Registered at startup via `register_audio_serializer()`.

> All previously listed issues in this area have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.
