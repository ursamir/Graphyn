# Backend Core Services

Supporting services used by the API routers and pipeline executor.

---

## `RunManager`

**File:** `app/core/run_manager.py`

Manages a per-run directory under `workspace/runs/{run_id}/`. Creates the directory and writes an initial `meta.json` on construction.

```python
run = RunManager()
run.run_id      # 8-char hex string, e.g. "a1b2c3d4"
run.base_path   # "workspace/runs/a1b2c3d4"
```

### Methods

| Method | Description |
|---|---|
| `save_config(yaml_str)` | Write `config.yaml` to the run directory |
| `save_logs(logs)` | Write `logs.json` (list of log entry dicts) |
| `save_metadata(metadata)` | Merge caller metadata with run bookkeeping fields and write `meta.json` with `status: "completed"` |
| `mark_failed(error)` | Update `meta.json` with `status: "failed"` and `error` field |
| `save_graph_ir(data)` | Write `graph.json`; also computes and stores `self._graph_hash` (Phase 4) |
| `compute_graph_hash(graph_ir)` | **Phase 4** — static method; returns SHA-256 hex of `dump_ir(graph_ir)` JSON |
| `register_artifact(node_id, node_type, artifact_type, data, metadata=None, input_artifact_ids=None)` | **Phase 4** — stores artifact via `ArtifactStore`, records lineage via `ProvenanceStore`, returns `ArtifactRecord` |
| `get_provenance_summary()` | **Phase 4** — returns `{"run_id", "graph_hash", "artifacts", "provenance_records"}` dict |

### `meta.json` structure

Written immediately on construction (status `"running"`), updated on completion or failure:

```json
{
  "run_id": "a1b2c3d4",
  "created_at": "2024-01-01T00:00:00+00:00",
  "status": "completed",
  "duration_s": 1.234,
  "num_nodes": 5,
  "node_stats": [
    {"node_id": "input_0", "node_type": "InputNode", "node_index": 0, "duration_s": 0.1}
  ]
}
```

All timestamps are UTC-aware ISO 8601 strings (`datetime.now(timezone.utc).isoformat()`), ending in `+00:00`.

### Run directory layout

```
workspace/runs/{run_id}/
├── meta.json       # run metadata (status, timing, node stats)
├── config.yaml     # pipeline YAML that was executed (only when run via YAML path)
├── logs.json       # all log entries
├── graph.json      # GraphIR JSON (always written — Phase 1)
└── checkpoints/    # only when checkpoint=True
    └── node_{node_id}/
        ├── 0.wav
        ├── 1.wav
        └── manifest.json
```

`graph.json` is written by `RunManager.save_graph_ir()` immediately after execution starts. It is the canonical record of what graph was executed and is exposed by the MCP `inspect_run` tool. In Phase 4, `save_graph_ir()` also computes `self._graph_hash` (SHA-256 of the canonical JSON) for use in provenance records.

**Phase 4 artifact storage** lives outside the run directory, under `workspace/artifacts/{artifact_id}/` and `workspace/provenance/`. Use `register_artifact()` to write artifacts and `get_provenance_summary()` to retrieve the full run summary.

---

## `PipelineLogger`

**File:** `app/core/logger.py`

Structured event logger for pipeline execution. Emits both plain-text log entries and typed JSON events.

```python
from queue import Queue
queue = Queue()
logger = PipelineLogger(queue=queue)   # queue is optional; used for streaming
```

When a `queue` is provided, every event is also put onto the queue for streaming to the frontend via `POST /api/v1/pipelines/run`.

### Methods

| Method | Emits |
|---|---|
| `pipeline_start(total_nodes)` | Plain log + `{"type": "pipeline_start", "total_nodes": N, "timestamp": "..."}` |
| `node_start(node_type, index, total_nodes)` | Plain log + `{"type": "node_start", "node_type": "...", "node_index": N, "total_nodes": N, "timestamp": "..."}` |
| `node_end(node_type, index, duration, output_count)` | Plain log + `{"type": "node_end", "node_type": "...", "node_index": N, "duration": 0.123, "output_count": 42, "timestamp": "..."}` |
| `node_error(node_type, index, error)` | Plain log + `{"type": "node_error", "node_type": "...", "node_index": N, "error_message": "...", "error_type": "ValueError", "timestamp": "..."}` |
| `pipeline_done(run_id, duration)` | `{"type": "done", "run_id": "...", "duration_s": 0.123, "timestamp": "..."}` — Phase 2 MCP terminal event |
| `pipeline_error(message)` | `{"type": "error", "message": "...", "timestamp": "..."}` — Phase 2 MCP terminal event |
| `pipeline_summary(stats_dict)` | `{"type": "pipeline_summary", ...stats_dict, "timestamp": "..."}` |
| `summary()` | Plain log only (total duration) |
| `info(msg)` | Plain log at INFO level |
| `error(msg)` | Plain log at ERROR level |

All entries are appended to `logger.logs` (a list). After the run, `run.save_logs(logger.logs)` persists them to `logs.json`.

---

## `IngestionService` and `IngestionJob`

**File:** `app/core/ingestion.py`

Handles background audio ingestion from URLs or HuggingFace datasets.

### `IngestionJob`

```python
class IngestionJob(BaseModel):
    job_id: str
    status: str   # "running" | "completed" | "failed"
    progress: list[dict] = []
```

`IngestionJob` is a Pydantic `BaseModel` (not a dataclass). Jobs are stored in a module-level dict `_jobs`.

### `IngestionService`

```python
svc = IngestionService()

# URL ingestion
job_id = svc.start_url_job(urls=["https://..."], label="speech")

# HuggingFace ingestion
job_id = svc.start_hf_job(
    repo_id="mozilla-foundation/common_voice_11_0",
    split="train",
    audio_col="audio",
    label_col="sentence",
    label_override=None,
)

# Access job
job = svc.get_job(job_id)   # raises KeyError if not found

# Stream progress events
for event in svc.stream_job(job_id):
    print(event)
```

Both `start_url_job` and `start_hf_job` return a `job_id` immediately and run the download in a background daemon thread.

### Progress event types

```json
{"type": "progress", "url": "https://...", "status": "success", "message": "Downloaded to ..."}
{"type": "progress", "url": "https://...", "status": "error", "message": "Download failed: ..."}
{"type": "error", "message": "httpx is not installed"}
{"type": "summary", "total_files": 3, "total_duration_seconds": 12.5, "label_distribution": {"speech": 3}}
```

### URL ingestion details

- Downloads each URL using `httpx` with `follow_redirects=True`, `timeout=60s`
- Validates file extension before downloading (`.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`)
- Saves to `workspace/datasets/input/{label}/{uuid8}_{filename}`
- Validates audio integrity via `soundfile.info()` or `librosa.get_duration()`; corrupted files are deleted
- Filename is sanitized to prevent path traversal
- `label` is sanitized via `_sanitize_label()` before use as a directory name (G3-23)

### HuggingFace ingestion details

- Streams the dataset using `datasets.load_dataset(..., streaming=True)`
- Saves each sample as a WAV file using `soundfile.write()`
- Label is determined by `label_override` → `label_col` → `"default"` (in priority order)
- Both `label_override` and `label_col` values are sanitized via `_sanitize_label()` before use as a directory name (G3-23)
- A `Path.is_relative_to(BASE_INPUT)` boundary check provides defence-in-depth against path traversal
- Saves to `workspace/datasets/input/{label}/{stem}.wav`

---

## `PipelineCache`

**File:** `app/core/pipeline_cache.py`

See [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md#pipelinecache) for full details.

---

## `ArtifactSerializerRegistry`

**File:** `app/core/artifact_serializer.py`

Pluggable serializer registry that decouples platform storage infrastructure from domain-specific serialization logic (ARCH-2 fix). Platform code calls the registry; domain code registers handlers at startup.

```python
# Domain registration — call once at each entry point startup
from app.models.audio_artifact_serializer import register_audio_serializer
register_audio_serializer()

# Registry access (used internally by artifact_store, pipeline_cache, checkpoint)
from app.core.artifact_serializer import get_serializer_registry
registry = get_serializer_registry()
handler = registry.get("audio_samples")   # None if not registered
```

**`ArtifactTypeHandler` ABC** — implement to add a new serializable type:

| Method | Description |
|---|---|
| `serialize(data, dest_dir)` | Write data to dest_dir (guaranteed to exist) |
| `deserialize(src_dir) → Any \| None` | Read data from src_dir; return None on miss |
| `compute_content_hash_input(data) → str` | Stable string for SHA-256 deduplication |
| `infer_type(value) → str \| None` | Return artifact_type string if value matches; None otherwise |

**`AudioSampleHandler`** (`app/models/audio_artifact_serializer.py`) — domain-side implementation for `audio_samples`. Owns WAV I/O (soundfile), manifest.json format, and AudioSample construction. Registered via `register_audio_serializer()`.

**Fail-open design:** if no handler is registered for a type, `artifact_store` falls back to JSON serialization; `pipeline_cache` and `checkpoint` log a warning and treat it as a miss (node re-executes).

---

## `ProjectManager`

**File:** `app/core/project_manager.py`

Manages the full project lifecycle: create, read, update, delete, clone, list versions, manage taxonomy, contract, spec, annotations, quality reports, and snapshots. Projects are stored under `workspace/datasets/output/{project_name}/`.

Used by `app/api/routers/projects.py` and `app/api/routers/system.py`.

---

## `QualityChecker`

**File:** `app/core/quality_checker.py`

Runs quality checks against a dataset version. Checks are defined in the project's `contract.json`. Results are written to `quality_report.json`.

---

## `WebhookService`

**File:** `app/core/webhook.py`

Manages webhook configuration and notifications.

```python
svc = WebhookService()
config = svc.load()                          # {"url": "...", "events": [...]}
svc.save(url="https://...", events=["..."])  # writes workspace/webhooks.json
svc.notify("pipeline_complete", {"run_id": "..."})  # fires HTTP POST
```

Webhook config is stored in `workspace/webhooks.json`.

---

## `stable_hash()`

**File:** `app/core/utils/hash.py`

Deterministic hash function used for:
- Node seeds: `stable_hash(pipeline_seed, node_type, node_index) % 2**32`
- Export file IDs: `stable_hash(path, len(data), label, start, end, augmented, augmentation_id)`
- Split group ordering: `stable_hash(seed, group_key)`

Returns a stable integer. The same inputs always produce the same output across Python runs (unlike Python's built-in `hash()` which is randomized).
