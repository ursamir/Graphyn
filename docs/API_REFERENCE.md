# API Reference

All endpoints are under `/api/v1/`. The old root-path endpoints (`/schemas`, `/runs`, `/validate`, `/run-stream`, etc.) no longer exist and return 404.

**Base URL:** `http://localhost:8001` (default)  
**Auth:** Bearer token via `GRAPHYN_API_TOKEN`. When set, include `Authorization: Bearer <token>`. Fail-closed when `GRAPHYN_AUTH_REQUIRED=1` or `GRAPHYN_ENV=production|staging` (empty token rejected). Local development may leave the token unset.

---

## Nodes — `/api/v1/nodes` and `/api/v1/types`

### `GET /api/v1/nodes`

List all registered nodes, optionally filtered by category.

**Query params:**
- `category` (optional) — filter by category string (e.g. `"Preprocessing"`, `"Augmentation"`)
- `limit` (optional, default **50**, max 500) — page size
- `offset` (optional, default 0) — page start
- `envelope` (optional) — default on (`{ items, total, limit, offset, next_offset }`); pass `0` for a bare array (still limited by `limit`)

Isolated plugin nodes (`runtime = "isolated"`) are never imported in the host process. Their `label`, `description`, `category`, `tags`, and capability flags are read from the entry point's `metadata = NodeMetadata(...)` literal using the AST. So `trainer`, `model_builder`, `evaluator`, and `dataset_builder` list as `ML`, `edge_optimizer` as `Export`, and `realtime_inference` as `Inference`, the same categories as in-process nodes. Values that are not literals fall back to the manifest (`description`, `tags`, `version`) and then to category `plugin`.

**Response (default):** paginated envelope. Clients that need the full catalog (Editor) must request `limit=500` and/or follow `next_offset` until null.

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

Validate and run live in `app/api/routers/pipelines.py`. Template and marketplace routes live in `app/api/routers/pipeline_templates.py` and register on the same router.

### `POST /api/v1/pipelines/validate`

Validate a pipeline without executing it. Accepts IR JSON (`schema_version` present)
or legacy `{"yaml": "..."}`. IR paths run `validate_graph_ir()` (registry, configs, ports, cycles).

**Response (valid):** HTTP **200**
```json
{"valid": true, "node_count": 3}
```

**Response (invalid IR or YAML):** HTTP **422**
```json
{"valid": false, "error": "…"}
```

YAML success responses also include `X-Deprecation-Warning`.

---

### `POST /api/v1/pipelines/run`

Execute a pipeline and stream NDJSON log events as they occur.

Creates a `RunManager` before the stream starts. Response headers include
**`X-Run-Id`**. The first NDJSON line is `{"type":"run_started","run_id":"…"}`.
Subsequent structured events (including `pipeline_start` / `done`) carry the same
`run_id` so Observe deep-links work during streaming.

**Request body:** Graph IR JSON (preferred) or `{"yaml": "…"}`.

**Response:** `Content-Type: application/x-ndjson` — one JSON object per line.

Runs never create or overwrite saved project pipelines. The executed graph is stored only as `runs/<run_id>/graph.json`. Saving to `datasets/output/<project>/pipelines/` happens only through `PUT /api/v1/projects/{name}/pipelines/{pipeline}`.

**503 `draining`:** the only 503 this route (and `/run-async`) returns. It means the control plane is shutting down. Body: `{"error": {"code": "draining", "retryable": true, …}}` with a `Retry-After: 30` header. Retry after the API restarts. There is no concurrency 503: runs beyond the 4-thread stream executor queue (`pending`) instead of being refused.

#### Streaming Protocol

Each line is a JSON object. Two types of objects are interleaved:

**Plain log entries:**
```json
{"time": "2024-01-01T00:00:00+00:00", "level": "INFO", "message": "[0] input — starting"}
```

**Structured events:**
```json
{"type": "run_started", "run_id": "…"}
{"type": "pipeline_start", "total_nodes": 5, "run_id": "…", "timestamp": "2024-01-01T00:00:00+00:00"}
{"type": "node_start", "node_type": "dataset_ingest", "node_index": 0, "total_nodes": 5, "run_id": "…", "timestamp": "..."}
{"type": "node_end", "node_type": "audio_quality_gate", "node_index": 3, "duration_s": 0.123, "output_count": 206, "output_counts": {"output": 206, "rejected": 13}, "rejected_count": 13, "run_id": "…", "timestamp": "..."}
{"type": "node_error", "node_type": "audio_conditioner", "node_index": 1, "node_id": "audio_conditioner_1", "error": "...", "error_message": "...", "error_type": "ValueError", "run_id": "…", "timestamp": "..."}
{"type": "pipeline_summary", "run_id": "…", "timestamp": "..."}
{"type": "done", "run_id": "…", "duration_s": 1.23, "timestamp": "2024-01-01T00:00:01+00:00"}
{"type": "error", "run_id": "…", "timestamp": "...", "error_type": "ValueError", "error": "...", "message": "...", "already_reported": true, "node_id": "audio_conditioner_1", "node_type": "audio_conditioner"}
```

`node_end.output_count` is the item count of the node's primary `output` port (sum over all ports only when the node has no `output` port); side ports such as a quality gate's `rejected` are not added. `output_counts` gives every port's count and `rejected_count` is present when the node has a `rejected` port.

**Error field.** `error` is the canonical error text on `node_error` and the terminal `error` event (`error_message` / `message` are kept for older clients). When the run failed because a node failed, that failure was already streamed as `node_error`; the terminal `error` event then carries `already_reported: true` plus `node_id` / `node_type`. Render the error once (from `node_error`) and treat that terminal event only as end-of-stream. Without `already_reported` (backend / planner errors), the terminal event is the only report.

The stream starts with `run_started` (and `X-Run-Id`). It **always** ends with either `{"type": "done", "run_id": "…"}` (success — synthesized if the backend emitted none) or `{"type": "error", "run_id": "…"}` (failure), then closes. Back-pressure: at most 512 events are buffered per stream; when a slow client lets the buffer fill, the **oldest non-terminal** events are dropped (the terminal event is never dropped) and the execution thread never blocks. A disconnected client stops buffering; the run itself continues and is visible via `GET /runs/{run_id}`. The `run.start` audit actor is `X-Actor` (default `api`).

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

List available pipeline templates with card summaries for the console.

**Response:** array of objects (always includes `name`; other fields when Graph IR is readable):
```json
[
  {
    "name": "basic-wakeword",
    "title": "Basic wakeword",
    "description": "…",
    "difficulty": null,
    "required_plugins": ["audio"],
    "inputs": ["workspace/datasets/input/…"],
    "outputs": ["dataset_export"],
    "tags": ["audio", "example"],
    "node_count": 4,
    "node_types": ["dataset_ingest", "…"]
  }
]
```

`title` is the display name to show on cards. It comes from `metadata.title` when set (the IR loader ignores that key, so it is safe on any graph). Otherwise the id is humanized, and synced numbered examples (`ex-NN-<slug>`) get an `(example NN)` suffix so they never collide with a same-named starter, for example `Call analytics (example 22)` vs `Call analytics (local Whisper + heuristic extract)`. `GET /pipelines/examples` items use the same rule. Workspace copies in `configs/templates/` synced before a source graph gained `metadata.title` fall back to the repo source's title. The source is found from the copy's `metadata.source_example`, or else `examples/templates/<name>.graph.json`. Re-running `POST /pipelines/templates/sync-examples` also refreshes the copy.

---

### `GET /api/v1/pipelines/templates/{name}`

Get template content. IR-native templates return `graph`. Legacy node types (`input`, `clean`, `export`, …) are migrated to current PluginPackage types before the response.

**Query params:**
- `version` (optional) — fetch a specific template version.

**Response:**
```json
{"name": "basic-wakeword", "graph": {"schema_version": "1.2", "nodes": [], "edges": []}}
```

**Errors:** `400` if name contains invalid characters. `404` if not found. `422` if IR cannot be migrated/validated.

---

### `POST /api/v1/pipelines/templates`

Save a new pipeline template.

**Request body:**
```json
{
  "name": "my-template",
  "yaml": "{\"schema_version\":\"1.2\",\"metadata\":{...},\"nodes\":[...],\"edges\":[...],\"parameters\":{}}",
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

### `GET /api/v1/artifacts`

List artifact records (newest first). Optional filters: `run_id`, `node_type`, `artifact_type`.

**Query params:** `limit` (default 100, max 1000), `offset` (default 0).

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
    {"time": "2024-01-01T00:00:00+00:00", "level": "INFO", "message": "Pipeline starting — 5 nodes"},
    {"type": "node_error", "node_id": "audio_conditioner_1", "error": "Sample rate should be over 0", "error_message": "…"}
  ],
  "is_latest": false,
  "artifacts_dir": "workspace/artifacts/<slug>/runs/a1b2c3d4",
  "node_order": [
    {"node_id": "dataset_ingest_0", "node_type": "dataset_ingest", "label": null, "index": 0, "wave": 0, "status": "completed"},
    {"node_id": "audio_conditioner_1", "node_type": "audio_conditioner", "label": null, "index": 1, "wave": 1, "status": "failed"},
    {"node_id": "segmenter_2", "node_type": "segmenter", "label": null, "index": 2, "wave": 2, "status": "not_run"}
  ]
}
```

`node_order` lists every node in the run's `graph.json` in execution order (wave-major, matching the planner), including nodes that never ran. `status` comes from `meta.node_stats`, or is `"not_run"` when the node has no stats row. It is computed without the node registry, so it also works when a node's plugin is no longer installed. It is `[]` when `graph.json` is missing. Every `node_error` / `error` log entry has an `error` field. Older logs that only had `error_message` / `message` are filled in when read.

**Errors:** `400` invalid run_id. `404` not found.

---

### `GET /api/v1/runs/{run_id}/graph`

Return the Graph IR JSON stored in the run journal (`workspace/runs/{run_id}/graph.json`) — same path artifact replay uses. Powers UI “Open in Builder” from Runs / Trace / Artifacts.

**Response:** Graph IR object (`nodes`, `edges`, `metadata`, …).

**Errors:** `400` invalid run_id. `404` run or `graph.json` missing. `422` unreadable/invalid `graph.json`.

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

1. Files under the run journal directory (`graph.json`, `meta.json`, logs, …)
2. `ArtifactRecord`s for that run, expanded via `ArtifactTypeHandler.list_files(data_dir)` (or a shallow listing of that artifact `data/` when the handler returns `None`)

Path side-effects (exporters, model dumps, webhook/LLM folders, …) appear only when the node called `Node.publish_files` and the run registered a platform `file_tree` artifact. Core does **not** walk graph `output_dir` trees or parse domain inventories such as `labels.csv`.

Pipeline graphs should write under `workspace/artifacts/<name>/` or other jailed write keys, not into `examples/`.

**Response:**
```json
[
  {
    "name": "model.keras",
    "path": "artifacts/speech-commands/runs/<run_id>/model.keras",
    "size": 128,
    "kind": "file",
    "node_id": "trainer_0"
  }
]
```

`node_id` comes from the `ArtifactRecord`. Journal files (`meta.json` / `logs.json` / `graph.json`) omit `node_id`. Typed artifacts expose inventories through their serializers (`audio_samples` → WAV + `manifest.json`; `dataset_artifact` → `.npy` + `manifest.json`; `file_tree` → published paths from `inventory.json`). A run-local `outputs_index.json` caches ArtifactRecord refs (schema v2) and is rebuilt from the ArtifactStore when missing.

**Project folders.** Listing never includes ProjectManager metadata (`project.json`, `spec.md`, `pipelines/`, …) even when a `file_tree` root sits under `datasets/output/<project>/`.

**Cap priority.** Candidates from journal + artifact inventories are filled into a 400-entry cap in this order: (1) run journal files; (2) key files — models (`.tflite`, `.keras`, `.onnx`, …) and small summaries; (3) everything else. Steps 2 and 3 are shared round-robin across nodes. `truncated_by_node.total` uses each handler's `FileListing.total` (not a filesystem recount).

**Truncation (opt-in, backwards compatible).** The default response stays a bare array, capped at 400 entries. The header `X-Graphyn-Outputs-Truncated: true|false` says whether anything was capped or summarized.

| Query | Response |
|---|---|
| *(none)* | `[ {name, path, size, kind, node_id?}, … ]` (unchanged) |
| `?with_meta=1` | `{ "items": [...], "truncated": bool, "max_items": 400, "truncated_by_node": { "<node_id>": {"shown": 9, "total": 201} }, "inputs_by_node": { … } }`. `shown` counts that node's file entries in `items`. `total` is the handler inventory total (`FileListing.total`). Only truncated nodes appear in `truncated_by_node`. |
| `?node_id=<id>&limit=200&offset=0` | `{ "node_id", "items", "total", "offset", "limit", "has_more" }`. Pages every inventored file for that node (`limit` 1–1000). |

**Ordering.** Inventories and the capped list use natural order (digit runs compare numerically). `node_id` paging and `truncated_by_node.total` share the same ArtifactStore inventories.
---

### `GET /api/v1/runs/{run_id}/outputs/zip`

Zip of the listed files as an attachment.

---

### `POST /api/v1/runs/{run_id}/promote`

Point `workspace/artifacts/<slug>/<alias>` at this run’s artifact tree.

**Body (optional):**
```json
{ "alias": "latest" }
```

`alias` defaults to `latest`. Allowed form: lowercase letter, then letters/digits/hyphens (`staging`, `prod`, …). Audits as `run.promote` (actor from `X-Actor` or `api`).

**Response:** `{ "slug", "run_id", "alias", "path", "latest" }` (`latest` mirrors `path` for backward compatibility).

**Errors:** `404` missing run (or its artifact run dir vanished before the alias was published), `409` no slug/artifacts, `422` invalid alias.

---

### Run control — `POST /api/v1/runs/{run_id}/pause|resume|cancel`

Runtime control for **active** runs in this API process (same registry as MCP `pause_run` / `resume_run` / `cancel_run`). Cooperative: pause/cancel take effect after the current node finishes.

| Method | Path | Effect |
|---|---|---|
| POST | `/api/v1/runs/{run_id}/pause` | Pause after current node |
| POST | `/api/v1/runs/{run_id}/resume` | Resume a paused run |
| POST | `/api/v1/runs/{run_id}/cancel` | Cancel after current node |

**Errors:** `400` invalid `run_id`. `404` detail `run_not_found` vs `run_not_active`. `503` `run_active_on_another_worker` when distributed and the run is owned elsewhere.

---

### `DELETE /api/v1/runs/{run_id}`

Delete a finished run journal and its workspace artifacts. Not allowed while status is `running` or `paused`.

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

## Secrets — `/api/v1/secrets`

Local named secret store (values never returned in list/get responses). Writes require Bearer auth when `GRAPHYN_API_TOKEN` is set.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/v1/secrets` | — | `{ "names": ["OPENAI_API_KEY", ...] }` |
| POST | `/api/v1/secrets` | `{ "name", "value" }` | `{ "ok": true, "name" }` |
| PUT | `/api/v1/secrets/{name}` | `{ "value" }` | `{ "ok": true, "name" }` |
| DELETE | `/api/v1/secrets/{name}` | — | `{ "ok": true, "name" }` or `404` |

Audited as `secret.set` / `secret.delete` when audit is enabled.

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
  "backend": "local_python",
  "backend_mode": "local",
  "worker_count": 0,
  "registry_ready": true,
  "registry_init_error": null,
  "node_type_count": 15,
  "catalog": {
    "bundled_plugins": 14,
    "bundled_node_types": 14,
    "installed_plugins": 14,
    "enabled_plugins": 14,
    "registered_node_types": 15,
    "partial_catalog": false,
    "warnings": [],
    "plugin_package_dir": "/app/PluginPackage"
  },
  "checks": {"runs_dir_exists": true, "cache_dir_exists": true}
}
```

`catalog` is **informational only** and never changes `ready` / `status`. `partial_catalog: true` (with human-readable `warnings`) means fewer plugins are installed and enabled than the bundled `PluginPackage/*/*/plugin.toml` manifests (after `GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST`), or the registry has fewer node types than those manifests declare. Graphs that use the missing node types fail validation. The section is cached for 30s.

`status` is `starting` while plugins load, `ready` when the registry initialized cleanly, or `failed` when `registry_init_error` is set.

This endpoint always recomputes. The PERS-020 guard on critical list GETs (`/runs`, `/artifacts`, `/projects`, `/models`, `/plugins`) reuses a snapshot cached for `GRAPHYN_READINESS_CACHE_S` seconds (default `5`, `0` disables). `checks.store_corrupt` inspects only known index locations (`artifacts/*.corrupt`, `artifacts/{by_run,by_name,_registry}/*.corrupt`, `artifacts/*/*.json.corrupt`, `plugins/*.json.corrupt`, `registry.json.corrupt`) — never a recursive workspace walk.

`backend_mode` is `local` (Mode A) or `distributed` (Mode B). The console header chip uses this field.

`GET /api/v1/system/health`, `/readiness`, and `/auth-status` are **public** (no Bearer) so the UI can show Mode / Auth honesty before Settings is filled. All other `/api/v1/*` routes still require the token when `GRAPHYN_API_TOKEN` is set.

---

### `GET /api/v1/system/auth-status`

Auth honesty for the console (no secrets). Reports whether Bearer auth is required and whether `GRAPHYN_API_TOKEN` is configured.

**Response:**
```json
{
  "auth_required": false,
  "token_configured": true,
  "env": "development",
  "ok": true
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

Cleanup respects `older_than_days` cutoff for runs and cache directories. Omitted `delete_cache` defaults to false. A second call while one cleanup is still running returns `409`. Directory sizes are not pre-scanned; `bytes_freed` counts file unlinks, and removed directories report `0` bytes.

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

**Response:** `url` is `scheme://host/***` when the saved URL has a path (the path is often the secret). `url_configured` is true when a URL is stored. `events` lists subscriptions; an empty list means every event.

---

### `PUT /api/v1/system/webhooks`

Save webhook configuration.

**Request body:**
```json
{"url": "https://example.com/hooks/secret", "events": ["pipeline_complete"], "keep_url": false}
```

`keep_url: true` (or a body `url` equal to the redacted preview) keeps the URL already stored and updates `events` only. A blank `url` with `keep_url` false clears the webhook. Sending a redacted preview that does not match the stored URL returns **422**.

**Response:**
```json
{"ok": true, "url": "https://example.com/webhook", "events": ["pipeline_complete"]}
```

Invalid or SSRF-blocked URLs return **422** with a `detail` string (not 500).

---

### `POST /api/v1/system/webhooks/test`

Fire a test event to the configured webhook URL and wait for the HTTP result. The test is sent even when `events` does not list `test`.

**Response:**
```json
{"ok": true, "url": "https://example.com/***"}
```

Returns `{"ok": false, "reason": "..."}` when no URL is set or delivery fails. The reason does not include the secret path.

Terminal run statuses fire `pipeline_complete` / `pipeline_failed` / `pipeline_cancelled` via `app.core.runs.run_notify` when configured. All three events carry the same fields (`run_id`, `status`, optional `graph_name`, `project`, `error`) and go to webhooks, optional SMTP, and in-app notifications. In-app notifications use `level`: `error` for failed, `warning` for cancelled, and `info` otherwise. A webhook with an explicit `events` list must include `pipeline_cancelled` to receive it. Before this change, cancelled runs fired no event.

---

### `GET /api/v1/system/schedules`

List interval schedules that run project pipelines while the API process is up.

**Query:** `?project=<name>` returns only that project's schedules.

**Response:** `{ "schedules": [ { "id", "name", "project", "pipeline", "interval_minutes", "enabled", "next_run_at", "last_run_id", "last_error", "last_error_at"?, "orphaned", "disabled_reason", "orphaned_at", … } ] }`

`orphaned` (bool), `disabled_reason`, and `orphaned_at` are always present (`false` / `null` when unset). The same shape is returned by `POST /system/schedules` and `POST /system/schedules/{id}/enable`. `next_run_at` is `null` while a schedule is disabled or orphaned, because a disabled schedule never fires. Enabling it recomputes `next_run_at` as now + `interval_minutes`. A manual `…/run` on a disabled schedule does not re-arm it.

**Orphans and permanent errors.** Deleting a project (`DELETE /projects/{name}`) disables every schedule for it. The schedule is kept, not deleted, with `orphaned: true`, `orphaned_at`, and `disabled_reason: "Project deleted: <name>"`. If a tick (or `…/run`) fails with a permanent error (`Project not found: …` or `Pipeline '…' not found`), the schedule is also auto-disabled. It records `last_error`, `last_error_at`, `disabled_reason`, and `orphaned: true` when the project is gone. Other start errors (a missing published env version, a busy backend) only set `last_error`, and the schedule retries on the next tick. Re-enabling clears `orphaned` / `disabled_reason`. The next tick disables it again if the target is still missing.

### `POST /api/v1/system/schedules`

Create a schedule. Body: `{ "name", "project", "pipeline", "interval_minutes", "enabled", "env" }`. `env` is `draft`, `staging`, or `prod` (default `prod` when omitted). Draft runs the saved pipeline. Staging and prod require a published version.

### `POST /api/v1/system/schedules/{id}/env`

Body: `{ "env": "draft"|"staging"|"prod" }`. Clears `last_error`.

### `POST /api/v1/system/schedules/tick`

Fire due schedules now (also runs on a 60s background ticker).

### `POST /api/v1/system/schedules/{id}/run` · `…/enable` · `DELETE …/{id}`

Run immediately, toggle enabled, or delete. Mutations audit with actor from `X-Actor` when present.

---

## Ingest — `/api/v1/ingest`

### `POST /api/v1/ingest/url`

Each URL is validated with `validate_http_egress_url` before the job starts (same policy as workflow HTTP nodes). Invalid destinations return **422**.

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

Full project lifecycle management. See `app/api/routers/projects.py` for the complete endpoint list. Key operations include create, get, update, delete, clone, list versions, manage taxonomy, contract, spec, annotations, quality reports, and snapshots. `POST /projects` returns `409` when the name already exists.

### Project pipelines (versions)

Graph IR assets owned by a project live at
`workspace/datasets/output/{project}/pipelines/{name}.graph.json` (**draft** head).
Versions: `pipelines/{name}/versions/vN.graph.json`. Envs: `pipelines/{name}/environments.json`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/projects/{name}/pipelines` | List + `environments` + `version_count` |
| GET | `/api/v1/projects/{name}/pipelines/{pipeline}` | Draft IR (`?env=staging\|prod` resolves pointer) |
| PUT | `/api/v1/projects/{name}/pipelines/{pipeline}` | Save draft (secret fail-closed, stamp project) |
| DELETE | `/api/v1/projects/{name}/pipelines/{pipeline}` | Delete draft file |
| GET | `.../versions` | Published snapshots |
| GET | `.../environments` | draft / staging / prod / pending_prod |
| POST | `.../publish` | `{ message?, set_env?: staging\|prod }` |
| POST | `.../promote` | `{ to_env, version?, from_env?, approve? }` — prod needs `approve: true` |
| POST | `.../rollback` | `{ version }` → copy onto draft |

**Errors:** `404` if project/pipeline missing; `422` for invalid name, IR, or inline secrets.

### Model registry (lite)

`workspace/artifacts/_registry/models.json` — name → stages (`staging`/`prod`/`latest`) with source `run_id` + artifact slug. Prod uses request/approve. **The console does not manage model prod approval** — use `POST /api/v1/models/{name}/request-prod` and `POST /api/v1/models/{name}/approve-prod` (API-only).

| Method | Path |
|---|---|
| GET | `/api/v1/models` |
| GET | `/api/v1/models/{name}` |
| POST | `/api/v1/models` — `{ name, run_id, slug, stage? }` |
| POST | `/api/v1/models/{name}/request-prod` |
| POST | `/api/v1/models/{name}/approve-prod` |

Promoting a run to `staging` in the Runs UI also auto-registers a model row when a slug is returned.


### Validate secret policy

`POST /api/v1/pipelines/validate` (IR) and MCP `validate_graph` fail closed when node
`config` contains non-empty secret-shaped keys (`api_key`, `token`, `password`,
`hmac_secret`, `*_secret`, …). Use the Secrets store or `*_env` fields instead.

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

**Security:** When `GRAPHYN_PLUGIN_ALLOWED_SOURCES` is set, remote sources that do not structurally match any listed base URL (host + path-segment boundary) are rejected with HTTP 502.

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


## Trace & Audit — `/api/v1/trace`, `/api/v1/audit`

Accountability / backtrack surface (Pillar A).

### `GET /api/v1/trace`

Unified Trace payload for an artifact and/or run.

**Query:**
- `artifact_id` (optional)
- `run_id` (optional)
- `node_id` (optional focus)

At least one of `artifact_id` / `run_id` is required.

**Also:** `GET /api/v1/trace/artifact/{id}` and `GET /api/v1/trace/run/{id}`.

**Response (partial OK):** `subject`, `run`, `graph`, `node`, `artifact`, `lineage`, `chain` (ordered steps), `warnings`.

- **Artifact-focused** (`artifact_id`): backtrack artifact → node → run → graph → worker; `lineage.inputs` / `tree` from ProvenanceStore.
- **Run-focused** (`run_id` only): Prefers `meta.node_stats` (else ArtifactStore) to build executed **node** steps in `chain`; `lineage.nodes` / `lineage.artifacts` / `lineage.artifact_count` / `lineage.provenance_count` for the Run → Lineage panel.

Reuses ProvenanceStore, ArtifactStore, and run `meta.json` (including `distributed_node_workers`).

### `GET /api/v1/audit`

Newest-first append-only audit events from `{project}/audit/events.jsonl`.

**Query:** `limit` (default 100, max 1000).

Seed hooks: template save, async run start, worker register.


## Experiments — `/api/v1/experiments`

MLflow-shaped experiment board (Pillar B). Aggregates from `{project}/runs/*/experiment.json` when present; otherwise run `meta.json` + `metrics.json` (run dir or artifacts). Corrupt files are skipped. Does not require the `mlflow` package.

### `GET /api/v1/experiments`

List of experiment blocks:

```json
[
  {
    "experiment_name": "default",
    "runs": [
      {
        "run_id": "...",
        "status": "completed",
        "created_at": "...",
        "graph_name": "...",
        "parameters": {},
        "metrics": {"accuracy": 0.9},
        "tags": []
      }
    ]
  }
]
```

### `GET /api/v1/experiments/{name}`

One experiment block (`404` if no runs under that name).

### `GET /api/v1/experiments/compare`

**Query:** `run_ids` — comma-separated run ids.

**Response:** `run_ids`, `missing_run_ids`, `param_keys`, `metric_keys` (preferred metrics first), `runs` (aligned rows for a comparison table).


## Distributed Workers — `/api/v1/workers`, `/api/v1/jobs`, `/api/v1/artifacts/blob`

Control-plane surfaces for `GRAPHYN_BACKEND=distributed`. See [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md).

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/workers/register` | Register / refresh a worker |
| POST | `/api/v1/workers/{id}/heartbeat` | Heartbeat + resource snapshot; **503** when lease renew fails |
| GET | `/api/v1/workers` | List workers |
| DELETE | `/api/v1/workers/{id}` | Deregister |
| POST | `/api/v1/jobs/claim` | Claim next eligible job |
| POST | `/api/v1/jobs/{id}/complete` | Report job result (lease-fenced) |
| POST | `/api/v1/jobs/{id}/events` | Append job log events |
| POST | `/api/v1/jobs/{id}/cancel` | Cancel a job |
| GET | `/api/v1/jobs/{id}` | Get job status |
| POST | `/api/v1/artifacts/blob` | Upload artifact blob |
| GET | `/api/v1/artifacts/blob/{key}` | Download artifact blob |

Durable registry/queue: `workspace/distributed/*.json` (or Redis when `GRAPHYN_REDIS_URL` is set). Orthogonal to `run_control` active-run registry.

---

## Proposals — `/api/v1/proposals`

Agentic Builder proposals (Pillar C). Store under `{project}/proposals/`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/proposals` | Create proposal (`summary`, `graph`, optional `actor` / `base_graph` / `base_graph_hash` / `kind` / `context`) |
| GET | `/api/v1/proposals` | List proposals (`?status=pending\|accepted\|rejected`) |
| GET | `/api/v1/proposals/{id}` | Get one proposal |
| POST | `/api/v1/proposals/{id}/accept` | Accept → audit; UI loads graph into Builder |
| POST | `/api/v1/proposals/{id}/reject` | Reject (optional reason) |

**Optional structured context.** `kind` is a lowercase id matching `^[a-z][a-z0-9_.-]{0,63}$`, for example `"explain_failure"`. `context` is a JSON object of at most 16 KiB, for example `{"run_id": "…", "node_id": "audio_conditioner_1", "error": "Sample rate should be over 0"}`. Both are stored as given and returned by create, get, and list. Both are `null` when omitted. An invalid `kind` / `context` returns `400`.

MCP equivalents: `propose_graph`, `list_proposals`, `get_proposal`.

---

## Static File Serving

| Mount | Filesystem | Example URL |
|---|---|---|
| `/files/` | `workspace/datasets/output/` | `/files/my-project/v1/train/speech/abc123.wav` |
| `/input-files/` | `workspace/datasets/input/` | `/input-files/speech/sample.wav` |
| `/run-files/` | `workspace/runs/` | `/run-files/a1b2c3d4/checkpoints/node_clean_1/0.wav` |
