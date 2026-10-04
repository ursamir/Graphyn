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
{"type": "node_progress", "node_id": "trainer_0", "node_type": "trainer", "ts": "...", "timestamp": "...", "level": "INFO", "message": "Trainer · epoch 3/30 · loss 0.41 · val_acc 0.78", "phase": "train", "epoch": 3, "epochs": 30, "loss": 0.41, "accuracy": 0.82, "val_loss": 0.5, "val_accuracy": 0.78, "pct": 10, "run_id": "…"}
```

**`node_progress`** — live progress a node reports via `app.core.nodes.progress.emit_node_progress(payload)` (in-process: context variable bound by the node executor; isolated plugin workers: `@@GRAPHYN_PROGRESS@@ <json>` stderr lines parsed live by the isolated executor). The payload keys are passed through (`phase`, `epoch`/`epochs`, `done`/`total`, `loss`, `accuracy`, `val_loss`, `val_accuracy`, `pct`, …) and the host adds `node_id`, `node_type`, `ts`/`timestamp`, `level` and a human `message` (a plugin-supplied `message` is kept as `detail`). At most 2 events/s per node; `final: true` or `pct >= 100` always gets through. The same events land in the run journal (`GET /runs/{id}` `logs`; `logs.json` is flushed at most every 5 s while a node reports progress, the journal keeps ≤ 500 progress rows per node then every 10th), and the latest event per node is mirrored into `meta.json` `node_progress` (`GET /runs/{id}/status`).

**Ingest `node_end`** — for `*ingest*` node types the `node_end` event also carries `dataset: {source_path, resolved_path, source_type, clip_count, fallback_used}` (`fallback_used: true` when the configured path was missing/empty and bundled example data was substituted; `null` when unknown).


`node_end.output_count` is the item count of the node's primary `output` port (sum over all ports only when the node has no `output` port); side ports such as a quality gate's `rejected` are not added. `output_counts` gives every port's count and `rejected_count` is present when the node has a `rejected` port.

**Error field.** `error` is the canonical error text on `node_error` and the terminal `error` event (`error_message` / `message` are kept for older clients). When the run failed because a node failed, that failure was already streamed as `node_error`; the terminal `error` event then carries `already_reported: true` plus `node_id` / `node_type`. Render the error once (from `node_error`) and treat that terminal event only as end-of-stream. Without `already_reported` (backend / planner errors), the terminal event is the only report.

The stream starts with `run_started` (and `X-Run-Id`). It **always** ends with either `{"type": "done", "run_id": "…"}` (success — synthesized if the backend emitted none) or `{"type": "error", "run_id": "…"}` (failure), then closes. Back-pressure: at most 512 events are buffered per stream; when a slow client lets the buffer fill, the **oldest non-terminal** events are dropped (the terminal event is never dropped) and the execution thread never blocks. A disconnected client stops buffering; the run itself continues and is visible via `GET /runs/{run_id}`. The `run.start` audit actor is `X-Actor` (default `api`).

All timestamps are UTC-aware ISO 8601 strings ending in `+00:00`.

---

**Audit inputs (both run endpoints; body may be the wrapper `{graph, project?, trigger?, pipeline?, pipeline_env?, pipeline_version?}`):** optional body keys `trigger` (`ui|api|…`, default `api`; the console sends `ui`), `pipeline` (saved pipeline name), `pipeline_env` (`draft|staging|prod`), `pipeline_version` (`vN`). `X-Actor` sets the actor; it is written to `meta.actor` before execution and reused by the sealed record and every `run.*` audit event.

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
    "node_types": ["dataset_ingest", "…"],
    "runnable": true,
    "missing_node_types": [],
    "group": "speech-commands-e2e",
    "phase": 1,
    "step_title": "Prepare the dataset"
  }
]
```

`runnable` is `true` when every node type of the template is registered on this host; `missing_node_types` lists the ones that are not (empty when runnable; with `GRAPHYN_SKIP_PLUGIN_LOAD=1` plugin types show as missing). `group` / `phase` / `step_title` are copied from the graph's `metadata` (multi-step examples such as Example 06 set `metadata.group = "speech-commands-e2e"`, `metadata.phase = 1|2`, `metadata.step_title`); `null` when absent.

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
    ],
    "graph_name": "speech_commands_e2e_train_ml",
    "display_name": "Speech commands E2E · train",
    "summary": {"primary_metric": {"name": "test_accuracy", "value": 0.561}, "paths": ["…"], "best_path_id": "path-a", "dataset": {"…": "…"}},
    "regression": {"metric": "test_accuracy", "best_previous_run_id": "1e4f…", "best_previous_value": 0.867, "delta": -0.306}
  }
]
```

Query: `limit`, `offset`, `project`, `include_archived` (default `false` — archived runs are hidden; with `include_archived=1` their rows carry `archived: true`).

Every list row carries `display_name` and `summary`; **`regression` is omitted on the list** (sibling scans are expensive) and is attached on `GET /runs/{id}` — see [Run results](#run-results--display_name-summary-regression). `graph_name` is unchanged (machine id).

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
  ],
  "display_name": "Speech commands E2E · train",
  "summary": {"…": "see Run results"},
  "regression": null,
  "node_progress": {"trainer_0": {"type": "node_progress", "epoch": 3, "epochs": 30, "message": "Trainer · epoch 3/30 · loss 0.41"}}
}
```

**Run id resolution.** Every `/runs/{run_id}…` endpoint (detail, status, models, graph, outputs, outputs/zip, checkpoints, artifacts, provenance, promote, verify, replay, delete, restore) and `GET /experiments/compare?run_ids=` accept the full id **or a unique prefix of ≥ 8 characters**; responses always carry the full `run_id`. No match → `404 {detail: {code: "run_not_found", message: "No run found with id '<p>'…", run_id}}`; several matches → `409 {detail: {code: "run_id_ambiguous", message, matches: [<id1>, …]}}`; malformed → `400 invalid_run_id`. Shorter prefixes only match exactly. The same resolution (`app/api/run_ids.py` → `app/core/runs/run_resolve.py`) applies to run ids in bodies and queries: `POST /models` and `POST /models/{name}/request-prod` (`run_id` — the registry always stores the FULL id), `POST /projects/{name}/ship/packages` (`run_id`), `GET /trace?run_id=` / `GET /trace/run/{id}` (Run → Lineage / hot spots), `GET /artifacts?run_id=`, `POST /runs/{id}/pause|resume|cancel`, and MCP `inspect_run` / `get_run` / `get_run_outputs` / `register_model` / `request_model_prod`.

**Run-level metrics.** `meta.metrics` on run rows / detail (and experiment rows) is the **best path's** metrics for multi-path runs — the same pick as the results banner (`summary.best_path_id`; primary metric from `PRIMARY_METRICS`, accuracy-like higher-is-better, loss/error-like lower-is-better). Extra fields: `metrics_path: {path_id, label}`, `metrics_by_path: [{path_id, label, metrics, best}]`, and `metrics_first_found` (the finalize-time `metrics.json` of the first node folder, previously returned as `metrics`).

**Audit fields** (see [Run audit record](#run-audit-record--prove-json)): `record` (the sealed `prove.json`, `null` while the run is not terminal), `record_status` (`sealed` | `pending`), `pipeline_drift` (below, `null` for ad-hoc graphs). `meta` carries `actor`, `trigger` (`ui|api|cli|sdk|mcp|schedule|replay|agent|webhook|ship` — run payload `trigger`; unknown values → `api`), `lineage_request` (sanitized payload `lineage`), `node_labels` (`{node_id: "Trainer · Path C (MobileNet · lr 0.002)"}`), `replay_of`, `pipeline_ref`, `pipeline_source`, `external_inputs`, `node_implementations`, `environment_info`, `archived*`, and for failed runs `error` (`"<ExceptionType>: <message>"`), `error_type`, `error_traceback`, `failed_node_id`. `meta.node_stats[]` rows carry `node_label` and, on cache hits, `cache_key` + `cache_source_run_id` (the run that produced the cache entry). Log events `node_start` / `node_end` / `node_error` / `node_progress` / `node_skip` carry `node_label`; `node_error` carries the real `error_type` and `traceback` (isolated plugin workers report the worker exception, not stderr noise).

`pipeline_drift`: `{project, pipeline, env, run_graph_hash, current_hash, drifted, layout_only, checked_at}` — compares the run's logical `graph_hash` with the **current** saved pipeline of the same name/env (prepared like a run: path rewire + project stamp). `drifted: null` when the saved pipeline is gone; `layout_only: true` when only canvas `ui` positions differ.

`display_name`, `summary`, `regression` are also merged into `meta`. `node_progress` is the latest `node_progress` event per node (live while running; `logs` also contains the `node_progress` rows).

`node_order` lists every node in the run's `graph.json` in execution order (wave-major, matching the planner), including nodes that never ran. `status` comes from `meta.node_stats`, or is `"not_run"` when the node has no stats row. It is computed without the node registry, so it also works when a node's plugin is no longer installed. It is `[]` when `graph.json` is missing. Every `node_error` / `error` log entry has an `error` field. Older logs that only had `error_message` / `message` are filled in when read.

**Errors:** `400` invalid run_id. `404` not found.

---

### Run results — `display_name`, `summary`, `regression`

`GET /runs` rows and `GET /runs/{run_id}` (top level and `meta`) carry the user-facing results of a run (`app.core.runs.run_summary`, cached per run by journal file mtimes — terminal runs are immutable):

```json
{
  "display_name": "Speech commands E2E · train",
  "summary": {
    "primary_metric": {"name": "test_accuracy", "value": 0.561},
    "paths": [
      {
        "path_id": "path-a",
        "label": "DS-CNN · 50 epochs",
        "node_ids": ["model_builder_0", "trainer_0", "evaluator_0", "edge_optimizer_0"],
        "metrics": {"test_accuracy": 0.561, "roc_auc": 0.857, "final_val_accuracy": 0.672, "final_accuracy": 0.619, "final_val_loss": 1.17, "final_loss": 1.14},
        "model_artifacts": ["<model rows, see GET /runs/{run_id}/models>"]
      },
      {"path_id": "path-b", "label": "CNN-small · 30 epochs", "…": "…"}
    ],
    "best_path_id": "path-a",
    "dataset": {
      "source_path": "workspace/datasets/input/speech-commands",
      "resolved_path": "workspace/datasets/input/speech-commands",
      "clip_count": 1200,
      "fallback_used": false,
      "from_ingest_node": "dataset_ingest_0"
    }
  },
  "regression": {"metric": "test_accuracy", "best_previous_run_id": "1e4f…", "best_previous_value": 0.867, "delta": -0.306}
}
```

- **Paths** are the fork branches after the last node shared by every sink (each sink's ancestry minus the shared trunk; branches that overlap are merged). A graph with one sink is one path (`path-a`, all nodes). Paths with neither metrics nor models are dropped; `paths` is `[]` for runs without results (e.g. preprocess runs).
- **Metrics** per path merge, in topological order, the trainer history's last epoch (`final_*`), every `metrics.json` in a node's `output_path`/`output_dir`, and numeric `metrics` of the node's output artifact (`outputs_index.json` → `data.json`); evaluator values win. Only numeric scalars are kept.
- **`primary_metric`** — first present of `test_accuracy` > `accuracy` > `val_accuracy` > `f1` (then their `final_*` forms); else the first finite scalar metric name (sorted). Value is from the best path. `best_path_id` prefers **higher** values unless the metric name matches loss/error/MAE/MSE/RMSE/latency/duration (then lower is better).
- **`label`** describes what differs between parallel paths, from the model_builder/trainer configs: `architecture` (`ds_cnn` → `DS-CNN`, `simple_cnn` → `CNN-small`, …), `epochs`, `batch_size`, `learning_rate`, then any other differing scalar key — at most two facts. A single path shows architecture + epochs. Identical/empty labels fall back to `Path A`, `Path B`, ….
- **`dataset`** comes from the ingest node's `node_end.dataset` (older runs: recomputed from its config + `output_count`).
- **`regression`** (detail GET only; list rows omit it) compares the primary metric with the best **older succeeded** run of the same `graph_name` and `project` that reports the same metric, respecting higher/lower-is-better; `null` when there is none.
- **`display_name`** — `metadata.title` when set; else the graph name split into family · phase · rest (`speech_commands_e2e_preprocess_down` → `Speech commands E2E · preprocess · down`). Generic names (`pipeline`) use `metadata.source_example` / `group` / `step_title`, or the bundled example whose node-type set matches, or the node composition. A `dataset_ingest` path that ends in a label folder (`datasets/input/<ds>/<label>`, `datasets/output/<p>/<v>/<split>/<label>`) appends the label (`Speech commands E2E · infer · down`).

---

### `GET /api/v1/runs/{run_id}/models`

Model files a run produced — for results, register and Ship.

```json
{
  "run_id": "2280…",
  "display_name": "Speech commands E2E · train",
  "status": "succeeded",
  "best_path_id": "path-a",
  "primary_metric": {"name": "test_accuracy", "value": 0.561},
  "models": [
    {
      "path": "workspace/artifacts/speech-commands/runs/2280…/trainer_0/model.keras",
      "name": "model.keras",
      "display_name": "DS-CNN (50 epochs)",
      "node_id": "trainer_0",
      "node_type": "trainer",
      "path_id": "path-a",
      "path_label": "DS-CNN · 50 epochs",
      "kind": "trained",
      "format": "keras",
      "size_bytes": 408505,
      "created_at": "2026-10-02T18:56:50+00:00",
      "metrics": {"test_accuracy": 0.561, "roc_auc": 0.857},
      "labels": ["down", "go", "no", "stop", "up", "yes"],
      "labels_source": "labels.txt",
      "suggested_name": "speech-commands-dscnn"
    }
  ]
}
```

- Detected formats: `.keras`/`.h5` → `keras`, SavedModel dirs (contain `saved_model.pb`) → `saved_model`, `.tflite`, `.onnx`, `.pt`/`.pth` → `pt`. `checkpoints/` is skipped.
- A model belongs to the node whose `output_path` contains it, else the first node whose output payload (`model_path`, `artifact_path`, `keras_model_path`, …) references it.
- `kind`: `compiled_untrained` for `model_builder` outputs (and `compiled_*` files), `optimized` for optimizer/quantizer/exporter nodes and `.tflite`, otherwise `trained`.
- `path` is workspace-relative and is accepted as-is by `POST /models` (`model_path`), Ship (`model_path`) and `edge_optimizer`.
- `labels` keep the model's class order: `labels.txt` next to (or inside) the model, else the node's output `labels`, else another node of the same path. `display_name` is the plugin-provided human name when present.
- `suggested_name` — registry-safe slug `<graph family>-<architecture>` (e.g. `speech-commands-dscnn`), distinct per path.
- Sorted by path, node order, kind (`trained`, `optimized`, `compiled_untrained`), format.

**Errors:** `400` invalid run_id. `404` run not found.

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
  "current_node": "ExportNode",
  "node_progress": {"trainer_0": {"type": "node_progress", "node_id": "trainer_0", "epoch": 3, "epochs": 30, "pct": 10, "message": "Trainer · epoch 3/30 · loss 0.41 · val_acc 0.78"}}
}
```

`node_progress` maps `node_id` → latest progress event (`{}` when no node reported progress).

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

Zip of prioritised output files (higher file cap than the UI listing; ArtifactStore inventories are expanded without the UI’s 32-sample preview cap) as an attachment. Members are packed under ``<node_id>/<filename>`` (``run/`` when unattributed) so same basenames from dual Trainers do not collide. Headers: ``X-Graphyn-Outputs-Zip-Truncated: true|false``, ``X-Graphyn-Outputs-Zip-Count`` (members packed). Truncation means the prioritised selection or the 512 MiB zip budget omitted some files — not a guaranteed full dump of every wav when a node has thousands.

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

**Archives** the run by default (soft delete): writes `runs/<id>/.archived` + `meta.archived`, `archived_at`, `archived_by`; the journal, sealed record and artifacts stay. Archived runs are hidden from `GET /runs` (use `?include_archived=1`). Response `{run_id, archived: true, archived_at, archived_by}` (idempotent). Audit `run.archive`.

`?purge=true` hard-deletes the journal and `artifacts/<slug>/runs/<run_id>` (retargeting `latest/`) and requires header **`X-Confirm-Purge: <full run_id>`** — otherwise `428 {detail: {code: "confirm_required", message}}`. Response: the delete payload plus `{purged: true, record_hash}`. Audit `run.purge` with `record_hash` / `graph_hash`. Both modes return `409` while the run is pending / running / paused.

### `POST /api/v1/runs/{run_id}/restore`

Un-archive (`{run_id, archived: false}`); audit `run.restore`.

### Run audit record — `prove.json`

Every terminal run (succeeded / failed / cancelled) seals an immutable `runs/<id>/prove.json` (schema `2.0`, `app/core/runs/audit_record.py`), returned as `record` by `GET /runs/{id}`:

| Field | Content |
|---|---|
| `graph_hash` / `materialized_graph_hash` | logical graph hash (also `graph.logical.json`) / hash of the executed `graph.json`. Note `GET /runs/{id}/graph` returns the materialized graph, whose write paths contain `runs/<run_id>` — compare against saved pipelines with `pipeline_drift` (or ignore those keys) |
| `pipeline_source`, `pipeline_version` | `saved` / `saved_modified` / `adhoc`; `{project, name, env, version, revision_hash, match: declared|content_hash|name_only, label}` (`null` for ad-hoc). Declared via run payload `pipeline` / `pipeline_env` / `pipeline_version`, else inferred by content hash against the project's draft head + published versions |
| `node_implementation_versions` | `node_type → {plugin, version, runtime: isolated|inprocess|builtin, plugin_code_hash (sha256 over the plugin source tree, cached by stat), node_version, source, venv_python?, venv_libraries?, venv_freeze_hash?}`; plus `plugin_version` / `plugin_code_hashes` per plugin |
| `external_inputs` | every external path a node config reads: `{node_id, node_type, node_label, key, label: "<node label> · <key>", path, resolved, kind, content_hash, hash_mode: content|manifest, file_count, total_bytes, dataset: {project, version}|null}`. Path literals inside multi-line code configs (e.g. `python_code` `source` with `"model_path": "workspace/…"`) are recorded with `key: "source:model_path"`. **Never inputs:** write-sink keys (`output_path`, `output_dir`, `out_*`, `*_output_path`, `export_*`, `save_*`, `dest*`, `log_dir`, `cache_dir`, `checkpoint_path`, …; `app.core.runs.audit_record.is_write_key`), anything under one of the graph's output locations (unless that location is a broad root like `workspace/artifacts`), and anything under `runs/<this run id>`. `dataset_versions` = those under `datasets/output/<project>/<vN>` |
| `input_artifact_hashes` | content hashes of registered artifacts this run **consumed** (provenance `input_artifact_ids`) that it did not produce — the run's own output artifacts are never listed |
| `lineage` | `{source_run_id (full id), source_artifact_id, models: [{name, stage, version, run_id, artifact_path, node_id, format, model_hash, hash_mode, match: declared|input_path, requested_version?, resolved?}]}` or `null`. `declared` = run payload `lineage.model` (below); `input_path` = an external input is (inside) a registered model stage's artifact. `model_version` = the first model row when meta has none |
| `outputs`, `outputs_manifest_hash` | per-node output folder hashes (+ `outputs_manifest.json` per-file sidecar used for verify diffs) |
| `cache` | `[{node_id, node_type, cache_key, source_run_id}]` for cache hits |
| `environment` | python, OS, machine, hostname, key host `libraries` (numpy, tensorflow, keras, librosa, torch, onnx, …); `image` (display: `name@digest`, else name, else `"docker container <id12> (image not recorded)"`), `image_name` / `image_tag` / `image_digest` (env `GRAPHYN_IMAGE` / `GRAPHYN_IMAGE_DIGEST`, else `BUILD_INFO.json`), `container_image_digest` (= `image_digest`), `container_id`, `container: {in_container, runtime: docker|podman|kubernetes|…, container_id, signals}` (`/.dockerenv`, `/run/.containerenv`, `KUBERNETES_SERVICE_HOST`, `/proc/1/cgroup` / `/proc/self/cgroup`, `/proc/self/mountinfo` bind mounts on `/etc/hostname|hosts|resolv.conf`, docker short-id `HOSTNAME`); `git_commit` + `git_source` (`env:GRAPHYN_GIT_SHA` → `BUILD_INFO.json` (`/app/BUILD_INFO.json`, repo root, or `GRAPHYN_BUILD_INFO`) → `.git`); `build_info`; `plugin_environments: {plugin → {venv, python, libraries (key libs: tensorflow, keras, numpy, onnx, h5py, protobuf, …), package_count, freeze_hash (sha256 of the sorted name==version list), plugin_version}}` for the isolated plugins the run used (dist-info scan of the venv itself — never the interpreter symlink target; cached per venv path + site-packages mtime); `graphyn_version`, backend |
| `actor`, `trigger`, `replay_of`, `node_labels`, `seed`, `status`, `error*` | identity / linkage |
| `chain`, `previous_record_hash`, `record_hash` | per-project hash chain (`workspace/audit/chains/<project>.jsonl`, `_global` without a project); `record_hash` = sha256 of the canonical record without itself |

**Declaring the shipped model (run payload `lineage`).** `POST /pipelines/run` / `run-async` accept an optional top-level field next to the graph:

```json
{"schema_version": "1.1", "nodes": [...], "edges": [...],
 "project": "kws", "source_run_id": "9650591812ab…", "trigger": "ship",
 "lineage": {"model": {"name": "kws-dscnn", "stage": "staging", "version": "staging"}}}
```

`model.name` is the registered model; `stage` (`staging|prod|latest`) or `version` selects the stage (registry stages are the versions; `stage` wins when both are sent; a `version` that is not a stage name is kept as `requested_version`). Tokens must match `[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}` or the field is ignored. A bare string `"lineage": {"model": "kws-dscnn"}` picks the first of prod / staging / latest. Stored as meta `lineage_request`; sealed as `lineage.models[]` with `match: "declared"` and the model artifact's `model_hash`. Unknown models are recorded with `resolved: false`. Without the field, a registered model is still found when a node reads its artifact path. `trigger: "ship"` labels Ship-wizard package runs.

Directory trees above `GRAPHYN_AUDIT_HASH_MAX_BYTES` (default 512 MiB) or `GRAPHYN_AUDIT_HASH_MAX_FILES` (20000) are hashed in `manifest` mode (relative paths + sizes). Legacy runs keep their 1.0 record.

### `GET /api/v1/runs/{run_id}/verify`

Re-hashes the graph snapshot, the logical graph, external inputs (current content), stored output folders, the outputs manifest, the record hash and its chain position. Response `{run_id, verified_at, status: pass|changed|fail|unsealed, ok, record_hash, checks: [{check, status: pass|fail|changed|missing|skipped, expected, actual, target?, node_id?, details?}]}`. `fail` = tamper / hash mismatch / broken chain; `changed` = inputs or outputs differ now (output rows list `added` / `removed` / `modified` files).

### `POST /api/v1/runs/{run_id}/replay`

Body `{check_inputs?: false, force?: false}`. Starts a new run from the run's **logical** graph (same seed and config, re-scoped to the new run — never writes into the old run's folders). Response `{run_id, replay_of, status: "pending", graph_hash}`. With `check_inputs`, `409 {detail: {code: "inputs_changed", message, changes: [{path, node_id, status, expected, actual}]}}` when an external input hash changed, unless `force`. The new run's meta/record carry `replay_of` and `trigger: "replay"`; audit `run.replay` (+ `run.start`). MCP `replay_run` shares the implementation (`app/core/runs/run_replay.py`) and accepts `check_inputs` / `force` / `actor`.

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

Get one project/version dataset: manifest files plus the sample list.

**Response:** an **object** (not an array):

```json
{
  "project": "my-project",
  "version": "v1",
  "files": [{"name": "a1b2c3d4.wav", "path": "train/speech/a1b2c3d4.wav", "size": 32044, "sha256": "…"}],
  "file_count": 1,
  "content_hash": "64c1…",
  "created_at": "2026-10-02T18:00:00+00:00",
  "samples": [
    {"path": "my-project/v1/train/speech/a1b2c3d4.wav", "split": "train", "label": "speech"}
  ]
}
```

`files` is always a list of `{name, path, size, sha256}` rows (`path` relative to the version dir, `name` its basename). `samples` comes from `labels.csv`, else the `train|val|test/<label>/*.wav` tree.

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
| GET | `.../environments` | `{kind: "pipeline_env", pipeline, draft, staging, prod, pending_prod, updated_at}` |
| POST | `.../publish` | `{ message?, set_env?: staging\|prod }` |
| POST | `.../promote` | `{ to_env, version?, from_env?, approve? }` — prod needs `approve: true` |
| POST | `.../rollback` | `{ version }` → copy onto draft |

**Errors:** `404` if project/pipeline missing; `422` for invalid name, IR, or inline secrets.

**Naming:** pipeline *environments* (draft/staging/prod pointers at Graph IR versions) are not model registry *stages*. Responses that carry them are tagged: pipeline envs `kind: "pipeline_env"` (`.../environments` body and the `environments` object of list rows), model stages `kind: "model_stage"` (`GET /models*` → `stages.*`). Nothing was renamed.

### Model registry (lite)

`workspace/artifacts/_registry/models.json` — name → stages (`staging`/`prod`/`latest`) with source `run_id` + artifact slug. Prod uses request/approve. **The console does not manage model prod approval** — use `POST /api/v1/models/{name}/request-prod` and `POST /api/v1/models/{name}/approve-prod` (API-only).

| Method | Path |
|---|---|
| GET | `/api/v1/models` |
| GET | `/api/v1/models/{name}` |
| POST | `/api/v1/models` — `{ name, run_id, slug?, stage?, description?, model_path?, node_id?, allow_untrained? }` |
| POST | `/api/v1/models/{name}/request-prod` |
| POST | `/api/v1/models/{name}/approve-prod` |

Promoting a run to `staging` in the Runs UI also auto-registers a model row when a slug is returned.

**Register (`POST /models`).** The stage records the run's real model file/dir. Pick it with `model_path` (a `path` from `GET /runs/{run_id}/models`, preferred) or `node_id`; otherwise a node id equal to `name` is used (legacy console behaviour), else the best path's trained model. `slug` may be omitted (derived from the model path). Errors: `422 compiled_untrained` when the chosen artifact is a `model_builder` output (compiled, never trained) — `detail.artifact` is the model row; pass `allow_untrained: true` to register it anyway. `422 model_not_in_run` when `model_path` / `node_id` match no model of the run. Use the model row's `suggested_name` (e.g. `speech-commands-dscnn`) as the default name instead of node ids.

**Read (`GET /models`, `GET /models/{name}`).** Each `stages.<stage>` is enriched at read time:

```json
{
  "kind": "model_stage", "stage": "staging", "run_id": "2280…", "slug": "speech-commands",
  "path": "workspace/artifacts/speech-commands/runs/2280…/trainer_0/model.keras",
  "artifact_path": "workspace/artifacts/speech-commands/runs/2280…/trainer_0/model.keras",
  "alias_path": "workspace/artifacts/speech-commands/staging",
  "format": "keras", "artifact_kind": "trained", "node_id": "trainer_0",
  "path_id": "path-a", "path_label": "DS-CNN · 50 epochs",
  "size_bytes": 408505, "created_at": "…", "exists": true,
  "metrics": {"test_accuracy": 0.561}, "labels": ["down", "go", "no", "stop", "up", "yes"],
  "source_run_id": "2280…", "source_run_display_name": "Speech commands E2E · train",
  "updated_at": "…"
}
```

`path` is the model file/dir itself (do not append `/saved_model`); the alias directory the stage still points at is `alias_path`. Entries written before this change (whose `path` was the alias dir) are resolved at read time — by stored `node_id`, else a node id equal to the model name, else the run's best path — so they also return a real `path`. `pending_prod` is tagged `kind: "model_stage"`, and `request-prod` → `approve-prod` carry the staging artifact into `prod`.


### Ship packages

`/api/v1/projects/{name}/ship/packages` — list / create / get / download / promote / transition. Create and promote need an `Idempotency-Key` header.

**`POST /projects/{name}/ship/packages`** body:

```json
{
  "model_name": "speech-commands-dscnn",
  "model_stage_or_version": "staging",
  "model_path": "workspace/artifacts/speech-commands/runs/2280…/tflite/model.tflite",
  "run_id": "2280…",
  "labels": ["down", "go", "no", "stop", "up", "yes"],
  "target": {"runtime": "tflite", "arch": "arm"},
  "env": "draft",
  "unsigned_allowed": true
}
```

Give a registered `model_name` (+ `model_stage_or_version`, default `staging`; the stage's real artifact is used), and/or a run `model_path` (+ `run_id`) from `GET /runs/{run_id}/models`. One of the two is required (`422`). The model file or SavedModel dir (≤ 256 MB) and `model/labels.txt` are embedded in `package.zip`; `manifest.model_ref` gains `model_path`, `format`, `node_id`, `labels`, and the manifest has `labels` and `warnings`.

`labels` must equal the model's class order (its `labels.txt`, else the run/registry labels). On mismatch: **`422`** with `error.code = "labels_mismatch"` and `detail = {expected: [...model order...], got: [...], labels_source}`. Response `warnings` (also in the manifest): `labels_unverified` (no labels to check against), `compiled_untrained` (model_builder output), `model_not_embedded` (model larger than 256 MB). `404` when the model file / registered model is missing.

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

**Query:** `limit` (default 100, max 1000), `offset` (paging over **all** matching events, not just the newest 1000), `run_id` (events of a run — full id or prefix ≥ 8 — incl. `run.replay` events whose `metadata.replay_of` is that run), `resource_id` (exact or prefix ≥ 8), `action` (exact, or `run.*` prefix), `q` (case-insensitive free text over the event JSON).

**Response:** `{events, limit, offset, total, has_more}`.

Seed hooks: template save, async run start, worker register.

Run lifecycle actions (`resource_type: "run"`, `resource_id` = the **full** run id, `actor` = the run's `meta.actor`, `metadata.project` set when the run has a project): `run.start` (REST / SDK / CLI / MCP / schedule / replay), `run.finish` / `run.fail` (`result: failure`) / `run.cancel` (sealed at the terminal transition, `metadata.record_hash`), `run.archive`, `run.restore`, `run.purge` (`record_hash`), `run.replay` (`metadata.replay_of`), plus `run.promote`.


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

`run_ids` entries may be unique run id prefixes (≥ 8 chars); an ambiguous prefix is a `409 run_id_ambiguous`.


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
