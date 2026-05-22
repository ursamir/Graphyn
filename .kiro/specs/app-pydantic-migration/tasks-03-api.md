# Tasks 03 — API Redesign

← Back to [tasks.md](tasks.md) | Design: [design-03-api.md](design-03-api.md)

**Requirements covered:** 8, 10, 11, 12, 13

**Prerequisites:** Group 02 (Task 2.5 — `run_pipeline` accepts `run_manager` kwarg), Group 04 (validation uses `registry.get_class()` directly)

**Files changed:**
- `app/api/routers/nodes.py` — NEW ✅
- `app/api/routers/pipelines.py` — NEW ✅
- `app/api/routers/runs.py` — NEW ✅
- `app/api/routers/data.py` — NEW ✅
- `app/api/routers/system.py` — NEW ✅
- `app/api/main.py` — replaced with thin app factory (no legacy redirects) ✅
- `tests/test_migration.py` — new/updated unit tests ✅
- `tests/test_properties.py` — new property tests ✅
- `tests/test_pipeline_integration.py` — new integration tests ✅

---

## Task 3.1 — Create `app/api/routers/nodes.py` — Node Catalogue API

**Requirement:** 8.1–8.7, 11.1–11.8

### Sub-tasks

- [x] 3.1.1 Create `app/api/routers/nodes.py` with `router = APIRouter(prefix="/nodes", tags=["nodes"])`
- [x] 3.1.2 Implement `GET /nodes` with optional `category` filter, returning full metadata + config_schema
- [x] 3.1.3 Implement `GET /nodes/{node_type}` — catch `NodeNotFoundError` → HTTP 404
- [x] 3.1.4 Implement `GET /nodes/{node_type}/config-schema` — catch `NodeNotFoundError` → HTTP 404
- [x] 3.1.5 Implement `GET /nodes/{node_type}/port-schema` — catch `NodeNotFoundError` → HTTP 404
- [x] 3.1.6 Implement `GET /nodes/compatible` — resolve type, validate direction, return compatible nodes
- [x] 3.1.7 Implement `GET /types` — return list of registered port data type names
- [x] 3.1.8 Implement `POST /nodes/{node_type}/validate-config` — return `{"valid": bool, "errors": {}}`
- [x] 3.1.9 Register `GET /nodes/compatible` and `GET /types` BEFORE `GET /nodes/{node_type}`

### Acceptance checks
- `GET /api/v1/nodes` returns a list with all required keys ✅
- `GET /api/v1/nodes/clean` returns metadata for the `clean` node ✅
- `GET /api/v1/nodes/nonexistent` returns HTTP 404 ✅
- `GET /api/v1/nodes/clean/config-schema` returns a JSON Schema dict ✅
- `GET /api/v1/nodes/clean/port-schema` returns port descriptors ✅
- `GET /api/v1/nodes/compatible?output_type=unknown` returns HTTP 400 ✅
- `POST /api/v1/nodes/clean/validate-config` with valid config returns `{"valid": true, "errors": {}}` ✅
- `POST /api/v1/nodes/clean/validate-config` with invalid config returns `{"valid": false, "errors": {...}}` ✅
- Zero occurrences of `registry[` in `nodes.py` ✅

---

## Task 3.2 — Create `app/api/routers/pipelines.py` — Pipeline API

**Requirement:** 10.2, 12.1–12.8, 13.1–13.6

### Sub-tasks

- [x] 3.2.1 Create `app/api/routers/pipelines.py` with `router = APIRouter(prefix="/pipelines", tags=["pipelines"])`
- [x] 3.2.2 Define `PipelinePayload(BaseModel)` with `yaml: str` field
- [x] 3.2.3 Implement `POST /pipelines/validate` — YAML parse + `validate_pipeline`, both linear and DAG formats
- [x] 3.2.4 Implement `POST /pipelines/run` — streaming NDJSON via Queue + daemon thread, UTC timestamps
- [x] 3.2.5 Implement `POST /pipelines/run-async` — single `RunManager()` pre-created, `run_pipeline(..., run_manager=run_mgr)`
- [x] 3.2.6 Implement template endpoints: GET list, GET by name, POST save, DELETE

### Acceptance checks
- `POST /api/v1/pipelines/validate` with valid YAML returns `{"valid": true}` ✅
- `POST /api/v1/pipelines/validate` with invalid YAML returns `{"valid": false, "error": "..."}` ✅
- `POST /api/v1/pipelines/run` streams NDJSON events ending with `{"type": "done"}` ✅
- `POST /api/v1/pipelines/run-async` returns `{"run_id": "<id>"}` matching a directory in `workspace/runs/` ✅
- `GET /api/v1/pipelines/templates` returns a list ✅
- `GET /api/v1/pipelines/templates/nonexistent` returns HTTP 404 ✅
- Zero occurrences of `datetime.utcnow` in `pipelines.py` ✅

---

## Task 3.3 — Create `app/api/routers/runs.py` — Runs API

**Requirement:** 10.2, 12.3–12.4

### Sub-tasks

- [x] 3.3.1 Create `app/api/routers/runs.py` with `router = APIRouter(prefix="/runs", tags=["runs"])`
- [x] 3.3.2 Define `RUNS_ROOT = Path("workspace/runs")` — single source of truth
- [x] 3.3.3 Implement `GET /runs` — list, read meta.json, sort newest first, skip unreadable
- [x] 3.3.4 Implement `GET /runs/{run_id}` — return config + logs + meta; HTTP 404 if missing
- [x] 3.3.5 Implement `GET /runs/{run_id}/status` — return status + progress_pct + current_node
- [x] 3.3.6 Implement `GET /runs/{run_id}/checkpoints` — list checkpoint directory names
- [x] 3.3.7 Implement `GET /runs/{run_id}/checkpoints/{node_id}` — exact then prefix match; HTTP 404
- [x] 3.3.8 Implement `GET /runs/{run_id}/checkpoints/{node_id}/samples` — first n entries

### Acceptance checks
- `GET /api/v1/runs` returns a list (may be empty) ✅
- `GET /api/v1/runs/nonexistent` returns HTTP 404 ✅
- `GET /api/v1/runs/{valid_id}/status` returns `{"status": "..."}` for an existing run ✅
- `RUNS_ROOT` is defined exactly once in the codebase ✅

---

## Task 3.4 — Create `app/api/routers/data.py` — Data API

**Requirement:** 10.2, 10.8

### Sub-tasks

- [x] 3.4.1 Create `app/api/routers/data.py` with `router = APIRouter(prefix="/data", tags=["data"])`
- [x] 3.4.2 Implement `GET /data/inputs` — list labels with file counts
- [x] 3.4.3 Implement `GET /data/inputs/{label}` — list files; HTTP 404 if missing
- [x] 3.4.4 Implement `POST /data/inputs/upload` — UTC-based filename, save to uploads/
- [x] 3.4.5 Implement `GET /data/outputs` — list projects/versions
- [x] 3.4.6 Implement `GET /data/outputs/{project}/{version}` — return sample list; HTTP 404
- [x] 3.4.7 Implement `GET /data/outputs/{project}/{version}/stats` — return split/label counts
- [x] 3.4.8 Implement `POST /data/merge` — copy WAV files from sources to target

### Acceptance checks
- `GET /api/v1/data/inputs` returns a list ✅
- `GET /api/v1/data/inputs/nonexistent` returns HTTP 404 ✅
- `GET /api/v1/data/outputs` returns a list ✅
- `POST /api/v1/data/inputs/upload` saves file with a UTC-based filename ✅
- Zero occurrences of `datetime.utcnow` in `data.py` ✅

---

## Task 3.5 — Create `app/api/routers/system.py` — System API

**Requirement:** 10.2, 10.7

### Sub-tasks

- [x] 3.5.1 Create `app/api/routers/system.py` with `router = APIRouter(prefix="/system", tags=["system"])`
- [x] 3.5.2 Implement `GET /system/health` — return `{"status": "ok", "timestamp": ...}`
- [x] 3.5.3 Implement `POST /system/cleanup` — delete runs + cache, return `{"deleted": count}`
- [x] 3.5.4 Implement `GET /system/projects-registry` — searchable project list with q/status filters
- [x] 3.5.5 Implement webhook endpoints: GET, PUT, POST /test

### Acceptance checks
- `GET /api/v1/system/health` returns `{"status": "ok", ...}` ✅
- `GET /api/v1/system/projects-registry` returns a response (may be empty list) ✅
- `POST /api/v1/system/cleanup` returns `{"deleted": <int>}` ✅

---

## Task 3.6 — Replace `app/api/main.py` with a thin app factory

**Requirement:** 10.1–10.8

### Sub-tasks

- [x] 3.6.1 Inventoried all middleware, static mounts, and auth logic from old `main.py`
- [x] 3.6.2 Deleted all inline endpoint handler functions
- [x] 3.6.3 Old router files (cleanup.py, registry_api.py, merge.py, webhooks.py) kept as-is; their logic superseded by new routers but files preserved for backward compat
- [x] 3.6.4 Wrote new `app/api/main.py`: FastAPI 2.0.0, CORS, auth dep, static mounts, 7 router includes under `/api/v1/`
- [x] 3.6.5 Verified `app/api/main.py` is 67 lines (< 100)
- [x] 3.6.6 Confirmed zero occurrences of `datetime.utcnow` in `app/api/main.py`
- [x] 3.6.7 Confirmed zero inline `@app.get` / `@app.post` handlers in `app/api/main.py`

### Acceptance checks
- `app/api/main.py` is under 100 lines of application code — **67 lines** ✅
- `GET /api/v1/system/health` returns `{"status": "ok", ...}` ✅
- All routers are reachable under `/api/v1/` ✅
- Static mounts (`/files`, `/input-files`, `/run-files`) still work ✅
- No legacy root-path endpoints exist (`/schemas`, `/runs` at root return 404) ✅
- Zero occurrences of `datetime.utcnow` in `main.py` ✅

---

## Task 3.7 — Fix `/run-async` single-RunManager guarantee

**Requirement:** 13.1–13.6

Implemented as part of Task 3.2 (sub-task 3.2.5).

### Verification sub-tasks

- [x] 3.7.1 Confirmed `POST /api/v1/pipelines/run-async` creates exactly ONE `RunManager()` before the thread starts
- [x] 3.7.2 Confirmed the returned `run_id` matches the directory created in `workspace/runs/`
- [x] 3.7.3 Confirmed `run_pipeline` is called with `run_manager=run_mgr` (the pre-created instance)
- [x] 3.7.4 Confirmed `GET /api/v1/runs/{run_id}/status` returns `"completed"` after a successful async run
- [x] 3.7.5 Confirmed `GET /api/v1/runs/{run_id}/status` returns `"failed"` after a failed async run

### Acceptance checks
- `workspace/runs/{run_id}/` directory exists immediately after `POST /api/v1/pipelines/run-async` returns ✅
- `workspace/runs/{run_id}/meta.json` contains `"status": "completed"` after the run finishes ✅
- No orphaned empty run directories are created ✅

---

## Task 3.8 — Write unit tests for Group 03

**Requirement:** 8.1–8.7, 10.1–10.8, 11.1–11.8, 12.1–12.8, 13.1–13.6

### Tests to implement

- [x] 3.8.1 `test_nodes_endpoint_shape`
- [x] 3.8.2 `test_nodes_endpoint_includes_noise`
- [x] 3.8.3 `test_node_detail_404`
- [x] 3.8.4 `test_config_schema_endpoint`
- [x] 3.8.5 `test_port_schema_endpoint`
- [x] 3.8.6 `test_types_endpoint`
- [x] 3.8.7 `test_compatible_nodes_unknown_type`
- [x] 3.8.8 `test_validate_config_valid`
- [x] 3.8.9 `test_validate_config_invalid`
- [x] 3.8.10 `test_health_endpoint`
- [x] 3.8.11 `test_validate_pipeline_endpoint_valid`
- [x] 3.8.12 `test_validate_pipeline_endpoint_invalid_yaml`
- [x] 3.8.13 `test_run_async_single_run_id`
- [x] 3.8.14 `test_main_py_line_count`
- [x] 3.8.15 `test_no_legacy_root_endpoints`
- [x] 3.8.16 `test_no_dict_registry_access_in_routers`

### Acceptance checks
- All tests in `tests/test_migration.py` pass for Group 03 items ✅

---

## Task 3.9 — Write property-based tests: Properties 11, 13

**Requirement:** 11.1, 11.6

### Tests to implement

- [x] 3.9.1 **Property 11 — `/api/v1/nodes` response shape** (`test_property_11_nodes_response_shape`)
  - `# Feature: app-pydantic-migration, Property 11: /api/v1/nodes response shape`
  - **Validates: Requirements 11.1** — passes with `max_examples=100` ✅

- [x] 3.9.2 **Property 13 — compatible nodes bidirectional consistency** (`test_property_13_compatible_nodes_bidirectional`)
  - `# Feature: app-pydantic-migration, Property 13: compatible nodes are bidirectionally consistent`
  - **Validates: Requirements 11.6** — passes with `max_examples=50` ✅

### Acceptance checks
- Both property tests pass ✅
- Each test is annotated with `# Feature:` and `# Validates:` comments ✅

---

## Task 3.10 — Write integration tests for API layer

**Requirement:** 10.1–13.6

### Tests to implement

- [x] 3.10.1 `test_nodes_all_registered_nodes_present`
- [x] 3.10.2 `test_validate_pipeline_linear_format`
- [x] 3.10.3 `test_validate_pipeline_dag_format`
- [x] 3.10.4 `test_validate_pipeline_no_audio_constraint`
- [x] 3.10.5 `test_run_async_run_id_directory_exists`
- [x] 3.10.6 `test_no_root_path_endpoints`

### Acceptance checks
- All integration tests pass ✅
- `test_no_root_path_endpoints` confirms clean break from legacy paths ✅
