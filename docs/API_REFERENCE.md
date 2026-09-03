# API Reference

All endpoints are under `/api/v1/`. The old root-path endpoints (`/schemas`, `/runs`, `/validate`, `/run-stream`, etc.) no longer exist and return 404.

**Base URL:** `http://localhost:8001` (default)  
**Auth:** Optional Bearer token. Set `GRAPHYN_API_TOKEN` env var to enable. When set, include `Authorization: Bearer <token>` on all requests.

---

## Nodes — `/api/v1/nodes` and `/api/v1/types`

### `GET /api/v1/nodes`

List all registered nodes, optionally filtered by category.

**Query params:**
- `category` (optional) — filter by category string (e.g. `"Preprocessing"`, `"Augmentation"`)

**Response:** Array of node objects.

```json
[
  {
    "node_type": "audio_conditioner",
    "label": "Audio Conditioner",
    "description": "Resample, normalize, and condition audio samples.",
    "category": "Preprocessing",
    "version": "1.0.0",
    "tags": [],
    "input_ports": {
      "input": {"name": "input", "data_type": "list[app.models.audio_sample.AudioSample]", ...}
    },
    "output_ports": {
      "output": {"name": "output", "data_type": "list[app.models.audio_sample.AudioSample]", ...}
    },
    "config_schema": { "$defs": {...}, "properties": {...}, "title": "CleanConfig", "type": "object" },
    "capability_metadata": {
      "requires_gpu": false,
      "supports_cpu": true,
      "supports_edge": false,
      "deterministic": true,
      "cacheable": true,
      "streaming_support": false,
      "realtime_support": false
    }
  }
]
```

---

### `GET /api/v1/nodes/{node_type}`

Get metadata for a single node type.

**Path params:** `node_type` — e.g. `clean`, `augment`

**Response:** Single node object (same shape as above).

**Errors:** `404` if node type not found.

---

### `GET /api/v1/nodes/{node_type}/config-schema`

Get the Pydantic-generated JSON Schema for a node's `Config` model.

**Response:** JSON Schema object.

```json
{
  "properties": {
    "sample_rate": {"default": 16000, "title": "Sample Rate", "type": "integer"}
  },
  "title": "CleanConfig",
  "type": "object"
}
```

**Errors:** `404` if node type not found.

---

### `GET /api/v1/nodes/{node_type}/port-schema`

Get the input and output port descriptors for a node.

**Response:**

```json
{
  "inputs": {
    "input": {"type": "array", "items": {"$ref": "#/$defs/AudioSample"}}
  },
  "outputs": {
    "output": {"type": "array", "items": {"$ref": "#/$defs/AudioSample"}}
  }
}
```

**Errors:** `404` if node type not found.

---

### `POST /api/v1/nodes/{node_type}/validate-config`

Validate a config dict against a node's Pydantic `Config` model.

**Request body:**
```json
{"config": {"sample_rate": 16000}}
```

**Response (valid):**
```json
{"valid": true, "errors": {}}
```

**Response (invalid):**
```json
{"valid": false, "errors": {"sample_rate": "Input should be a valid integer"}}
```

**Errors:** `404` if node type not found.

---

### `GET /api/v1/types`

List all registered port data type fully-qualified names.

**Response:**
```json
["app.models.audio_sample.AudioSample"]
```

---

### `GET /api/v1/nodes/compatible`

Find nodes whose ports are compatible with a given port type.

**Query params:**
- `output_type` (required) — fully-qualified type name (from `/api/v1/types`)
- `direction` (optional, default `"input"`) — `"input"` (nodes that consume this type) or `"output"` (nodes that produce this type)

**Response:** Array of `NodeMetadata` objects.

**Errors:** `400` if `output_type` is unknown or `direction` is invalid.

---

## Pipelines — `/api/v1/pipelines`

### `POST /api/v1/pipelines/validate`

Validate a pipeline YAML string without executing it.

**Request body:**
```json
{"yaml": "pipeline:\n  seed: 42\n  nodes:\n    ..."}
```

**Response (valid):**
```json
{"valid": true}
```

**Response (invalid):**
```json
{"valid": false, "error": "Unknown node type 'foo'. Available types: augment, clean, ..."}
```

---

### `POST /api/v1/pipelines/run`

Execute a pipeline and stream NDJSON log events as they occur.

**Request body:**
```json
{"yaml": "pipeline:\n  seed: 42\n  nodes:\n    ..."}
```

**Response:** `Content-Type: application/x-ndjson` — one JSON object per line.

#### Streaming Protocol

Each line is a JSON object. Two types of objects are interleaved:

**Plain log entries:**
```json
{"time": "2024-01-01T00:00:00+00:00", "level": "INFO", "message": "[0] input — starting"}
```

**Structured events:**
```json
{"type": "pipeline_start", "total_nodes": 5, "timestamp": "2024-01-01T00:00:00+00:00"}
{"type": "node_start", "node_type": "dataset_ingest", "node_index": 0, "total_nodes": 5, "timestamp": "..."}
{"type": "node_end", "node_type": "dataset_ingest", "node_index": 0, "duration_s": 0.123, "output_count": 42, "timestamp": "..."}
{"type": "node_error", "node_type": "audio_conditioner", "node_index": 1, "error_message": "...", "error_type": "ValueError", "timestamp": "..."}
{"type": "pipeline_summary", "timestamp": "..."}
{"type": "done", "timestamp": "2024-01-01T00:00:01+00:00"}
{"type": "error", "timestamp": "...", "error_type": "ValueError", "message": "..."}
```

The stream always ends with either `{"type": "done"}` (success) or `{"type": "error"}` (failure), followed by the sentinel that closes the stream.

All timestamps are UTC-aware ISO 8601 strings ending in `+00:00`.

---

### `POST /api/v1/pipelines/run-async`

Start a pipeline run in a background thread and return the `run_id` immediately.

**Request body:**
```json
{"graph": {...}}
```

**Response:**
```json
{"run_id": "a1b2c3d4e5f6..."}
```

`run_id` is a full 32-char UUID4 hex string. Poll `GET /api/v1/runs/{run_id}/status` to check progress. Status is read from `meta.json` on disk — not from an in-memory dict.

---

### `GET /api/v1/pipelines/templates`

List available pipeline template names.

**Response:**
```json
["audio-classification", "audio-quality-check", "basic-wakeword", "podcast-leveling", "speech-recognition"]
```

---

### `GET /api/v1/pipelines/templates/{name}`

Get template content. IR-native templates return `graph`. Legacy node types (`input`, `clean`, `export`, …) are migrated to current PluginPackage types before the response.

**Query params:**
- `version` (optional) — fetch a specific template version.

**Response:**
```json
{"name": "basic-wakeword", "graph": {"schema_version": "1.1", "nodes": [], "edges": []}}
```

**Errors:** `400` if name contains invalid characters. `404` if not found. `422` if IR cannot be migrated/validated.

---

### `POST /api/v1/pipelines/templates`

Save a new pipeline template.

**Request body:**
```json
{
  "name": "my-template",
  "yaml": "{\"schema_version\":\"1.1\",\"metadata\":{...},\"nodes\":[...],\"edges\":[...],\"parameters\":{}}",
  "version": "v1",
  "description": "Initial baseline"
}
```

**Response:**
```json
{"name": "my-template", "version": "v1", "saved": true}
```

**Errors:** `400` invalid name/version, `422` invalid IR JSON payload.

---

### `POST /api/v1/pipelines/templates/sync-examples`

Import Builder-facing example templates into `{project}/configs/templates/`.

**Policy:** one numbered example folder → one template (canonical `pipeline.graph.json`, or `composed.graph.json` / `pipeline_train_ml.graph.json` / …). Per-label CLI shards are not imported. Starter graphs from `examples/templates/` are included. Obsolete `ex-*` shard templates are pruned.

**Query:** `force` (default `true`) — overwrite existing.

**Response:** `{ written, pruned, skipped, errors, count_written, count_pruned, ... }`

### `GET /api/v1/pipelines/examples`

List bundled example Graph IR metadata (id, source, title, description, tags) without copying.

---

### `GET /api/v1/pipelines/templates/{name}/versions`

List available versions for a template. Works for versioned dirs and legacy flat `{name}.graph.json` files (returns `storage: "legacy_flat"`, empty `versions`, HTTP 200 — not 404).

**Response (versioned):**
```json
{"name": "my-template", "latest_version": "v3", "versions": ["v1", "v2", "v3"], "storage": "versioned"}
```

**Response (legacy flat):**
```json
{"name": "audio-quality-check", "latest_version": null, "versions": [], "storage": "legacy_flat"}
```

---

### `DELETE /api/v1/pipelines/templates/{name}`

Delete a named template.

**Query params:**
- `version` (optional) — delete only that version.

**Response:**
```json
{"name": "my-template", "deleted": true}
```

**Errors:** `400` invalid name/version. `404` not found.

---

### `GET /api/v1/artifacts/{artifact_id}/lineage`

Get the upstream lineage tree for a specific artifact.

**Response:** Lineage tree dict. Never raises — returns error nodes for missing provenance records.

```json
{
  "artifact_id": "abc123",
  "node_id": "cond_0",
  "node_type": "AudioConditionerNode",
  "run_id": "...",
  "inputs": [...]
}
```

**Errors:** `404` if artifact not found.

---

## Runs — `/api/v1/runs`

### `GET /api/v1/runs`

List all pipeline runs, newest first.

**Response:** Array of run metadata objects.

```json
[
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
]
```

---

### `GET /api/v1/runs/{run_id}`

Get a run's config YAML and log entries.

**Response:**
```json
{
  "run_id": "a1b2c3d4",
  "meta": {"run_id": "a1b2c3d4", "status": "completed", ...},
  "config_yaml": "pipeline:\n  seed: 42\n  ...",
  "logs": [
    {"time": "2024-01-01T00:00:00+00:00", "level": "INFO", "message": "Pipeline starting — 5 nodes"}
  ]
}
```

**Errors:** `400` invalid run_id. `404` not found.

---

### `GET /api/v1/runs/{run_id}/status`

Get the current status of a run.

**Response:**
```json
{
  "status": "completed",
  "progress_pct": 100.0,
  "current_node": "ExportNode"
}
```

`status` values: `"running"`, `"completed"`, `"failed"`, `"cancelled"`, `"unknown"`

`progress_pct` is `null` when `num_nodes` is absent from `meta.json` (e.g. run failed before metadata was written).

---

### `GET /api/v1/runs/{run_id}/checkpoints`

List checkpoint directory names for a run.

**Response:**
```json
["node_input_0", "node_clean_1", "node_segment_2"]
```

Returns `[]` if no checkpoints exist (pipeline was run without `checkpoint=True`).

---

### `GET /api/v1/runs/{run_id}/checkpoints/{node_id}`

Get the `manifest.json` for a specific checkpoint.

**Response:**
```json
{
  "samples": [
    {
      "filename": "0.wav",
      "label": "speech",
      "path": "/original/path.wav",
      "sample_rate": 16000,
      "metadata": {}
    }
  ]
}
```

**Errors:** `404` if run or checkpoint not found.

---

### `GET /api/v1/runs/{run_id}/checkpoints/{node_id}/samples`

Get the first N sample entries from a checkpoint manifest.

**Query params:** `n` (default `10`, max `100`)

**Response:** Array of sample objects (same as `manifest.samples`).

---

### `GET /api/v1/runs/{run_id}/artifacts`

List all artifacts registered for a specific run. Returns 404 if the run does not exist.

**Response:** Array of `ArtifactRecord` objects (same shape as `GET /api/v1/artifacts`).

---

### `GET /api/v1/runs/{run_id}/outputs`

List downloadable files for a run (auth required). Sources:

1. Files under the run directory
2. Paths on `ArtifactRecord`s for that run
3. Directories from node config `output_dir` / `output_path` / `model_path` / output-like `path` on the stored `graph.json`
4. `workspace/artifacts/` (bind-mounted project artifacts; prefer `<slug>/` then a capped walk of the tree)
5. Legacy `examples/06_speech_commands_e2e/output` when those files exist

Pipeline graphs should write under `workspace/artifacts/<name>/`, not into `examples/`.

**Response:**
```json
[
  {"name": "metrics.json", "path": "artifacts/speech-commands/metrics.json", "size": 128, "kind": "file"}
]
```

---

### `GET /api/v1/runs/{run_id}/outputs/zip`

Zip of the listed files as an attachment.

---

### `GET /api/v1/outputs/file`

Download one file as an attachment. Query: `path`.

Resolved path must sit under `project_dir()`, `graphyn_home()`, or repo `examples/`. `..` is rejected. Allowed types: images, json, csv, markdown, audio (wav/flac/mp3/webm), keras, tflite, onnx, zip (plus SavedModel companions: pb/h5/txt/npy).

**Errors:** `400` traversal or directory, `403` outside jail (e.g. `/etc/passwd`), `404` missing, `415` disallowed type.

---

### `GET /api/v1/runs/{run_id}/provenance`

Return a provenance summary for a run. Returns 404 if the run does not exist.

**Response:**
```json
{
  "run_id": "abc123",
  "artifact_count": 3,
  "artifacts": [...],
  "provenance_records": [...]
}
```

---

### `GET /api/v1/runs/{run_id}/debug-report`

Return a consolidated run-operator debug payload combining status, checkpoint inventory,
artifact/provenance counts, and recent error log entries.

**Response fields include:**
- `status` (same schema as `/runs/{run_id}/status`)
- `checkpoint_count`, `checkpoints`
- `artifact_count`, `provenance_count`
- `error_count`, `recent_errors`
- `paths` (`run_dir`, `meta_json`, `logs_json`, `checkpoints_dir`)

---

## Data — `/api/v1/data`

### `GET /api/v1/data/inputs`

List input dataset labels with file counts.

**Response:**
```json
[
  {"label": "speech", "file_count": 42},
  {"label": "noise", "file_count": 10}
]
```

---

### `GET /api/v1/data/inputs/{label}`

List audio files for a specific input label.

**Response:**
```json
[
  {"path": "speech/file1.wav", "label": "speech"},
  {"path": "speech/file2.mp3", "label": "speech"}
]
```

**Errors:** `404` if label not found.

---

### `POST /api/v1/data/inputs/upload`

Upload an audio file to `workspace/datasets/input/uploads/`.

**Request:** `multipart/form-data` with `file` field.

**Response:**
```json
{"file_path": "/abs/path/to/upload_20240101_120000_000000.wav", "filename": "upload_20240101_120000_000000.wav"}
```

**Errors:** `400` if file extension is not supported (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.webm`, `.flac`).

---

### `GET /api/v1/data/outputs`

List output dataset projects and their versions.

**Response:**
```json
[
  {"project": "my-project", "versions": ["v1", "v2"]}
]
```

---

### `GET /api/v1/data/outputs/{project}/{version}`

Get the sample list for a specific project/version dataset.

**Response:** Array of sample objects from `labels.csv`.

```json
[
  {"path": "my-project/v1/train/speech/a1b2c3d4.wav", "split": "train", "label": "speech"}
]
```

**Errors:** `404` if dataset not found.

---

### `GET /api/v1/data/outputs/{project}/{version}/stats`

Get split counts and per-label distribution for a dataset.

**Response:**
```json
{
  "project": "my-project",
  "version": "v1",
  "total": 100,
  "splits": {
    "train": {"speech": 64, "noise": 16},
    "val": {"speech": 8, "noise": 2},
    "test": {"speech": 8, "noise": 2}
  }
}
```

**Errors:** `404` if dataset or `labels.csv` not found.

---

### `POST /api/v1/data/merge`

Copy audio files from multiple source versions into a target version.

**Request body:**
```json
{
  "sources": [
    {"project": "project-a", "version": "v1"},
    {"project": "project-b", "version": "v2"}
  ],
  "target_project": "merged",
  "target_version": "v1"
}
```

**Response:**
```json
{
  "target": "merged/v1",
  "files_copied": 150,
  "errors": []
}
```

---

## System — `/api/v1/system`

### `GET /api/v1/system/health`

Health check.

**Response:**
```json
{"status": "ok", "timestamp": "2024-01-01T00:00:00+00:00"}
```

---

### `GET /api/v1/system/readiness`

Readiness check with basic filesystem dependency validation.

**Response:**
```json
{
  "status": "ready",
  "timestamp": "2024-01-01T00:00:00+00:00",
  "checks": {"runs_dir_exists": true, "cache_dir_exists": true}
}
```

---

### `GET /api/v1/system/metrics`

In-process API metrics snapshot.

**Response fields include:**
- `requests_total`
- `errors_5xx_total`
- `requests_per_second`
- `latency_s` (`avg`, `p50`, `p95`, `p99`, `sample_size`)
- `by_status`
- `by_route`

---

### `POST /api/v1/system/cleanup`

Delete run directories and cache entries.

**Request body (optional):**
```json
{"older_than_days": 7, "delete_cache": true}
```

Cleanup respects `older_than_days` cutoff for runs and cache directories.

**Response:**
```json
{
  "deleted": 15,
  "runs_deleted": 10,
  "cache_entries_deleted": 5,
  "bytes_freed": 1048576
}
```

---

### `GET /api/v1/system/projects-registry`

List all dataset projects with optional search/filter.

**Query params:**
- `q` (optional) — substring search on project name
- `status` (optional) — filter by project status

**Response:** Array of project objects.

---

### `GET /api/v1/system/webhooks`

Get the current webhook configuration.

**Response:**
```json
{"url": "https://example.com/webhook", "events": ["pipeline_complete", "pipeline_failed"]}
```

---

### `PUT /api/v1/system/webhooks`

Save webhook configuration.

**Request body:**
```json
{"url": "https://example.com/webhook", "events": ["pipeline_complete"]}
```

**Response:**
```json
{"ok": true, "url": "https://example.com/webhook", "events": ["pipeline_complete"]}
```

---

### `POST /api/v1/system/webhooks/test`

Fire a test event to the configured webhook URL.

**Response:**
```json
{"ok": true, "url": "https://example.com/webhook"}
```

Returns `{"ok": false, "reason": "No webhook URL configured"}` if no URL is set.

---

## Ingest — `/api/v1/ingest`

### `POST /api/v1/ingest/url`

Start a background job to download audio files from URLs.

**Request body:**
```json
{
  "urls": ["https://example.com/audio1.wav", "https://example.com/audio2.mp3"],
  "label": "speech"
}
```

**Response:**
```json
{"job_id": "a1b2c3d4e5f6"}
```

Files are saved to `workspace/datasets/input/{label}/`. Supported extensions: `.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`.

---

### `GET /api/v1/ingest/url/{job_id}/stream`

Stream progress events for a URL ingestion job (Server-Sent Events).

**Response:** `Content-Type: text/event-stream`

```
data: {"type": "progress", "url": "https://...", "status": "success", "message": "Downloaded to ..."}

data: {"type": "progress", "url": "https://...", "status": "error", "message": "Download failed: ..."}

data: {"type": "summary", "total_files": 2, "total_duration_seconds": 8.5, "label_distribution": {"speech": 2}}
```

**Errors:** `404` if job not found.

---

### `POST /api/v1/ingest/huggingface`

Start a background job to stream a HuggingFace dataset and save audio samples.

**Request body:**
```json
{
  "repo_id": "mozilla-foundation/common_voice_11_0",
  "split": "train",
  "audio_col": "audio",
  "label_col": "sentence",
  "label_override": null
}
```

**Response:**
```json
{"job_id": "b2c3d4e5f6a1"}
```

---

### `GET /api/v1/ingest/huggingface/{job_id}/stream`

Stream progress events for a HuggingFace ingestion job (same SSE format as URL stream).

**Errors:** `404` if job not found.

---

## Projects — `/api/v1/projects`

Full project lifecycle management. See `app/api/routers/projects.py` for the complete endpoint list. Key operations include create, get, update, delete, clone, list versions, manage taxonomy, contract, spec, annotations, quality reports, and snapshots.

---

## Plugins — `/api/v1/plugins`

Plugin lifecycle management. All operations delegate to `PluginManager`. Error responses use `{"error": "<ErrorClassName>", "detail": "<message>"}`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/plugins` | List all installed plugins → JSON array of `PluginRecord` (+ `runtime`, `dependency_summary`) |
| POST | `/api/v1/plugins/install` | Install a plugin; body: `{"source": str, "upgrade": bool, "expected_sha256": str\|null}` |
| GET | `/api/v1/plugins/search` | Search plugin index; `?q=<query>` → JSON array of index entries |
| POST | `/api/v1/plugins/venvs/gc` | Remove unused isolated plugin venvs → `{"removed": [...]}` |
| GET | `/api/v1/plugins/{name}` | Get full `PluginRecord` for an installed plugin. Surfaces `installing`/`failed`/`installed` states for async installs. |
| GET | `/api/v1/plugins/{name}/dependencies` | Dependency status (required/optional, satisfied, runtime, python) |
| POST | `/api/v1/plugins/{name}/dependencies/install` | Install missing deps; body: `{"include_optional": bool}` |
| POST | `/api/v1/plugins/{name}/enable` | Enable plugin → `{"name": ..., "enabled": true}` |
| POST | `/api/v1/plugins/{name}/disable` | Disable plugin → `{"name": ..., "enabled": false}` |
| DELETE | `/api/v1/plugins/{name}` | Uninstall plugin → `{"name": ..., "status": "uninstalled"}` |

**Install request fields:**
- `source` (required) — local path, `git+<url>`, `https://<url>.zip`, or plain plugin name
- `upgrade` (optional, default `false`) — replace existing installation
- `expected_sha256` (optional) — SHA-256 hex digest of the downloaded archive; verified before extraction for HTTP archive sources (SEC-6 fix)

**Security:** When `GRAPHYN_PLUGIN_ALLOWED_SOURCES` is set, remote sources not matching any listed prefix are rejected with HTTP 502.

**Error code mapping:**

| Exception | HTTP Status |
|---|---|
| `PluginNotFoundError` | 404 |
| `PluginAlreadyInstalledError` | 409 |
| `PluginCompatibilityError` | 422 |
| `PluginDependencyError` | 422 |
| `PluginInstallError` | 502 |
| `PluginIndexError` | 502 |

---

## Static File Serving

| Mount | Filesystem | Example URL |
|---|---|---|
| `/files/` | `workspace/datasets/output/` | `/files/my-project/v1/train/speech/abc123.wav` |
| `/input-files/` | `workspace/datasets/input/` | `/input-files/speech/sample.wav` |
| `/run-files/` | `workspace/runs/` | `/run-files/a1b2c3d4/checkpoints/node_clean_1/0.wav` |
