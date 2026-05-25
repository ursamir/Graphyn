---
inclusion: fileMatch
fileMatchPattern: "app/api/routers/**"
---

# API Endpoints — Complete Reference

All routes under `/api/v1/`. Auth: optional Bearer token via `GRAPHYN_API_TOKEN`.

## Nodes (`routers/nodes.py`)

Node responses include a `capability_metadata` object with fields: `requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`, `memory_requirements`, `dependency_requirements`, `batch_support`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/nodes` | List all nodes; `?category=Preprocessing` |
| GET | `/api/v1/nodes/{node_type}` | Metadata for one node |
| GET | `/api/v1/nodes/{node_type}/config-schema` | JSON Schema for node config |
| GET | `/api/v1/nodes/{node_type}/port-schema` | Input/output port descriptors |
| POST | `/api/v1/nodes/{node_type}/validate-config` | Body: `{"config": {...}}` → `{"valid": bool, "errors": {}}` |
| GET | `/api/v1/types` | All registered port data type FQNs |
| GET | `/api/v1/nodes/compatible` | `?output_type=<fqn>&direction=input\|output` |

## Pipelines (`routers/pipelines.py`)

Accepts both **IR JSON** (canonical) and **YAML** (deprecated) formats.
IR JSON is detected by the presence of a `schema_version` field in the request body.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/pipelines/validate` | IR JSON or `{"yaml": "..."}` → `{"valid": bool, "node_count": N}` or `{"valid": bool, "error": "..."}` |
| POST | `/api/v1/pipelines/run` | IR JSON or `{"yaml": "..."}` → NDJSON stream (see below) |
| POST | `/api/v1/pipelines/run-async` | IR JSON or `{"yaml": "..."}` → `{"run_id": "..."}` |
| GET | `/api/v1/pipelines/templates` | List template names |
| GET | `/api/v1/pipelines/templates/{name}` | `{"name": "...", "yaml": "..."}` |
| POST | `/api/v1/pipelines/templates` | `{"name": "...", "yaml": "..."}` → `{"name": "...", "saved": true}` |
| DELETE | `/api/v1/pipelines/templates/{name}` | `{"name": "...", "deleted": true}` |

**IR JSON format** (canonical):
```json
{"schema_version": "1.0", "metadata": {"name": "...", "seed": 42}, "nodes": [...], "edges": [...]}
```

**YAML format** (deprecated — returns `X-Deprecation-Warning` header):
```json
{"yaml": "pipeline:\n  seed: 42\n  nodes: [...]"}
```

## Runs (`routers/runs.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/runs` | All runs, newest first; `?limit=50&offset=0` |
| GET | `/api/v1/runs/{run_id}` | Config YAML + logs |
| GET | `/api/v1/runs/{run_id}/status` | `{"status": "...", "progress_pct": N, "current_node": "..."}` |
| GET | `/api/v1/runs/{run_id}/checkpoints` | List checkpoint node IDs |
| GET | `/api/v1/runs/{run_id}/checkpoints/{node_id}` | `manifest.json` content |
| GET | `/api/v1/runs/{run_id}/checkpoints/{node_id}/samples` | First N samples `?n=10` |
| GET | `/api/v1/runs/{run_id}/artifacts` | List all artifacts for a run (delegates to `ArtifactStore.list(run_id=run_id)`) |
| GET | `/api/v1/runs/{run_id}/provenance` | Provenance summary: `{"run_id", "artifact_count", "artifacts", "provenance_records"}` |

## Run Control (`routers/run_control.py`)

Control active pipeline runs. Returns HTTP 400 with `{"error": "invalid_run_id"}` for invalid `run_id` characters. Returns HTTP 404 with `{"error": "run_not_active", "run_id": "..."}` if the run is not currently active.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/runs/{run_id}/pause` | Pause after current node → `{"run_id": "...", "status": "paused"}` |
| POST | `/api/v1/runs/{run_id}/resume` | Resume from pause → `{"run_id": "...", "status": "running"}` |
| POST | `/api/v1/runs/{run_id}/cancel` | Cancel after current node → `{"run_id": "...", "status": "cancelled"}` |

## Data (`routers/data.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/data/inputs` | Input labels with file counts |
| GET | `/api/v1/data/inputs/{label}` | Audio files for a label |
| POST | `/api/v1/data/inputs/upload` | Multipart `file` field → `{"file_path": "...", "filename": "..."}` |
| GET | `/api/v1/data/outputs` | Output projects and versions |
| GET | `/api/v1/data/outputs/{project}/{version}` | Sample list from `labels.csv` |
| GET | `/api/v1/data/outputs/{project}/{version}/stats` | Split counts + label distribution |
| POST | `/api/v1/data/merge` | `{"sources": [...], "target_project": "...", "target_version": "..."}` |

## System (`routers/system.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/system/health` | `{"status": "ok", "timestamp": "..."}` |
| POST | `/api/v1/system/cleanup` | Delete runs + cache + optionally artifacts — body: `{"older_than_days": 7, "delete_cache": true, "delete_artifacts": false}` |
| GET | `/api/v1/system/projects-registry` | All projects `?q=search&status=...` |
| GET | `/api/v1/system/webhooks` | Current webhook config |
| PUT | `/api/v1/system/webhooks` | Save `{"url": "...", "events": [...]}` |
| POST | `/api/v1/system/webhooks/test` | Fire test event |

## Ingest (`routers/ingest.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/ingest/url` | `{"urls": [...], "label": "..."}` → `{"job_id": "..."}` |
| GET | `/api/v1/ingest/url/{job_id}/stream` | SSE progress stream |
| POST | `/api/v1/ingest/huggingface` | `{"repo_id": "...", "split": "...", "audio_col": "...", "label_col": "..."}` |
| GET | `/api/v1/ingest/huggingface/{job_id}/stream` | SSE progress stream |

## Artifacts (`routers/artifacts.py`)

Artifact ID validation: only alphanumeric, hyphens, and underscores allowed — HTTP 400 otherwise.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/artifacts` | List artifacts; `?run_id=X&node_type=Y&artifact_type=Z` |
| GET | `/api/v1/artifacts/{artifact_id}` | Get one artifact; 404 if not found, 400 if invalid ID |
| GET | `/api/v1/artifacts/{artifact_id}/lineage` | Lineage tree dict (never 404 — error nodes for missing records) |
| POST | `/api/v1/artifacts/{artifact_id}/replay` | Replay original run → `{"run_id": "...", "status": "started"}`; 404 if artifact missing, 422 if graph.json missing |

## Projects (`routers/projects.py`)

Full project lifecycle under `/api/v1/projects/`. Operations: create, get, update, delete, clone, list versions, taxonomy, contract, spec, annotations, quality reports, snapshots, curation decisions. See source for full endpoint list.

## Plugins (`routers/plugins.py`)

Error responses use `{"error": "<ErrorClassName>", "detail": "<message>"}`. Remote installs (git+, http://, https://) run asynchronously via `BackgroundTasks`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/plugins` | List all installed plugins → JSON array of `PluginRecord` |
| POST | `/api/v1/plugins/install` | Body: `{"source": str, "upgrade": bool}` → sync: `{"name", "version", "status": "installed"}` / async: `{"status": "installing", "name": "..."}` |
| GET | `/api/v1/plugins/search` | `?q=<query>` → JSON array of index entries |
| GET | `/api/v1/plugins/{name}` | Full `PluginRecord` for installed plugin; 404 if not found |
| POST | `/api/v1/plugins/{name}/enable` | Enable plugin → `{"name": ..., "enabled": true}`; 404 if not found |
| POST | `/api/v1/plugins/{name}/disable` | Disable plugin → `{"name": ..., "enabled": false}`; 404 if not found |
| DELETE | `/api/v1/plugins/{name}` | Uninstall plugin → `{"name": ..., "status": "uninstalled"}`; 404 if not found |

**Error code mapping:**

| Exception | HTTP Status |
|---|---|
| `PluginNotFoundError` | 404 |
| `PluginAlreadyInstalledError` | 409 |
| `PluginCompatibilityError` | 422 |
| `PluginDependencyError` | 422 |
| `PluginInstallError` | 502 |
| `PluginIndexError` | 502 |

## Streaming Protocol (`POST /api/v1/pipelines/run`)

`Content-Type: application/x-ndjson` — one JSON object per line:

```jsonc
{"type": "pipeline_start", "total_nodes": 5, "timestamp": "2024-01-01T00:00:00+00:00"}
{"type": "node_start", "node_type": "InputNode", "node_index": 0, "total_nodes": 5, "timestamp": "..."}
{"type": "node_end", "node_type": "InputNode", "node_index": 0, "duration": 0.123, "output_count": 42, "timestamp": "..."}
{"type": "node_error", "node_type": "CleanNode", "node_index": 1, "error_message": "...", "error_type": "ValueError", "timestamp": "..."}
{"type": "done", "timestamp": "..."}          // success
{"type": "error", "message": "...", "timestamp": "..."}  // failure
// Plain log entries interleaved:
{"time": "...", "level": "INFO", "message": "[0] InputNode — starting"}
```

All timestamps: UTC ISO 8601 ending in `+00:00`.

## Ingestion SSE Protocol

`Content-Type: text/event-stream` — `data: {...}\n\n`:

```
data: {"type": "progress", "url": "...", "status": "success"|"error", "message": "..."}
data: {"type": "summary", "total_files": 3, "total_duration_seconds": 12.5, "label_distribution": {...}}
```

## Path Safety

- `_safe_child()` used on all path components — prevents traversal
- Template names: `^[A-Za-z0-9_-]+`
- Run IDs: alphanumeric only
- Upload filenames: replaced with timestamped names

## Open Issues in This Area

> All previously listed issues in this area have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.
