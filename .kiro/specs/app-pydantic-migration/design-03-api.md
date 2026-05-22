
# Design Sub-File 03 — Complete FastAPI Redesign

← Back to [design.md](design.md)

This sub-file covers the complete redesign of the FastAPI layer:

1. **API versioning** — all endpoints under `/api/v1/`, legacy paths return 301 redirects
2. **Router split** — `app/api/main.py` monolith split into focused routers
3. **Node Catalogue API** — rich node discovery, port introspection, type compatibility
4. **Pipeline API** — validate and execute pipelines (linear + DAG), templates
5. **Runs API** — list runs, get run details, poll async status, browse checkpoints
6. **Data API** — input/output dataset browsing, mic upload, merge
7. **System API** — health, cleanup, webhooks, projects-registry
8. **Fix `/run-async` run ID tracking** — eliminate the dual-RunManager bug
9. **UTC timestamp fixes** — replace all `datetime.utcnow()` in `main.py`

---

## 1. Restructured app/api/main.py

The current `main.py` is 500+ lines of inline endpoint logic. After the redesign it becomes a thin app factory under 100 lines.

### Before (current structure)

```
app/api/main.py  — 500+ lines
  - CORS, auth, static mounts
  - All endpoint logic inline: /schemas, /validate, /validate-node,
    /run-stream, /run-async, /run/*, /datasets, /dataset, /dataset-stats,
    /input-datasets, /input-dataset, /mic-upload, /templates, /template/*
  - Duplicate RUNS_ROOT definition (known issue #5)
  - datetime.utcnow() calls (deprecated)
  - Dual RunManager in /run-async (known issue #6)
```

### After (new structure)

```python
# app/api/main.py (AFTER — thin app factory)
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path
import os

from app.api.routers.nodes import router as nodes_router
from app.api.routers.pipelines import router as pipelines_router
from app.api.routers.runs import router as runs_router
from app.api.routers.data import router as data_router
from app.api.routers.system import router as system_router
from app.api.routers.projects import router as projects_router
from app.api.routers.ingest import router as ingest_router

app = FastAPI(title="AudioBuilder API", version="1.0.0")

# Auth, CORS, static mounts (unchanged)
_auth_dep = _get_auth_dependency()

app.add_middleware(CORSMiddleware, ...)

WORKSPACE_ROOT = Path("workspace").resolve()
app.mount("/files", StaticFiles(directory=str(WORKSPACE_ROOT / "datasets" / "output")), name="files")
app.mount("/input-files", StaticFiles(directory=str(WORKSPACE_ROOT / "datasets" / "input")), name="input-files")
app.mount("/run-files", StaticFiles(directory=str(WORKSPACE_ROOT / "runs")), name="run-files")

# New versioned routers
app.include_router(nodes_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])
app.include_router(pipelines_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])
app.include_router(runs_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])
app.include_router(data_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])
app.include_router(system_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])
app.include_router(projects_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])
app.include_router(ingest_router, prefix="/api/v1", dependencies=[Depends(_auth_dep)])

# 301 redirect aliases for backward compatibility (6-month transition)
_REDIRECTS = {
    "/schemas":           "/api/v1/nodes",
    "/validate":          "/api/v1/pipelines/validate",
    "/validate-node":     "/api/v1/nodes/{node_type}/validate-config",
    "/run-stream":        "/api/v1/pipelines/run",
    "/run-async":         "/api/v1/pipelines/run-async",
    "/templates":         "/api/v1/pipelines/templates",
    "/runs":              "/api/v1/runs",
    "/datasets":          "/api/v1/data/outputs",
    "/input-datasets":    "/api/v1/data/inputs",
    "/mic-upload":        "/api/v1/data/inputs/upload",
    "/registry":          "/api/v1/system/projects-registry",
    "/cleanup":           "/api/v1/system/cleanup",
    "/webhooks":          "/api/v1/system/webhooks",
    "/merge":             "/api/v1/data/merge",
}

for legacy_path, new_path in _REDIRECTS.items():
    _new_path = new_path  # capture for closure
    @app.api_route(legacy_path, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def _redirect(new_path: str = _new_path):
        return RedirectResponse(url=new_path, status_code=301)
```

---

## 2. Node Catalogue API — app/api/routers/nodes.py

### Router Definition

```python
# app/api/routers/nodes.py
from fastapi import APIRouter, HTTPException, Query
from app.core.registry_runtime import get_registry
from app.core.nodes.errors import NodeNotFoundError, PortTypeNotFoundError

router = APIRouter(prefix="/nodes", tags=["nodes"])
```

### GET /api/v1/nodes

Returns all registered nodes with full metadata.

```python
@router.get("")
def list_nodes(category: str | None = Query(None)):
    """List all registered nodes with full metadata.

    Optional ?category= filter (e.g. "Audio", "processing", "augmentation").
    """
    registry = get_registry()
    nodes = registry.list_nodes(category=category)
    result = []
    for meta in nodes:
        result.append({
            "node_type": meta.node_type,
            "label": meta.label,
            "description": meta.description,
            "category": meta.category,
            "version": meta.version,
            "tags": meta.tags,
            "input_ports": meta.input_ports,
            "output_ports": meta.output_ports,
            "config_schema": registry.get_config_schema(meta.node_type),
        })
    return result
```

**Example response entry:**
```json
{
  "node_type": "clean",
  "label": "Clean",
  "description": "Resample and normalise audio samples",
  "category": "processing",
  "version": "1.0.0",
  "tags": [],
  "input_ports": {
    "input": {"name": "input", "data_type": "app.models.audio_sample.AudioSample", "cardinality": "single", "required": true}
  },
  "output_ports": {
    "output": {"name": "output", "data_type": "app.models.audio_sample.AudioSample"}
  },
  "config_schema": {
    "title": "Config",
    "type": "object",
    "properties": {"sample_rate": {"type": "integer", "default": 16000}}
  }
}
```

### GET /api/v1/nodes/{node_type}

```python
@router.get("/{node_type}")
def get_node(node_type: str):
    """Get full metadata for a single node type. Returns 404 if not registered."""
    registry = get_registry()
    try:
        meta = registry.get_metadata(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")
    return {
        "node_type": meta.node_type,
        "label": meta.label,
        "description": meta.description,
        "category": meta.category,
        "version": meta.version,
        "tags": meta.tags,
        "input_ports": meta.input_ports,
        "output_ports": meta.output_ports,
        "config_schema": registry.get_config_schema(node_type),
    }
```

### GET /api/v1/nodes/{node_type}/config-schema

```python
@router.get("/{node_type}/config-schema")
def get_config_schema(node_type: str):
    """Return the JSON Schema for the node's Config model."""
    registry = get_registry()
    try:
        return registry.get_config_schema(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")
```

### GET /api/v1/nodes/{node_type}/port-schema

```python
@router.get("/{node_type}/port-schema")
def get_port_schema(node_type: str):
    """Return the port definitions (input_ports + output_ports) for the node."""
    registry = get_registry()
    try:
        return registry.get_port_schema(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")
```

### GET /api/v1/nodes/compatible

```python
@router.get("/compatible")
def find_compatible_nodes(
    output_type: str = Query(..., description="Fully-qualified PortDataType name"),
    direction: str = Query("input", description="'input' or 'output'"),
):
    """Find nodes compatible with a given port data type.

    direction='input'  → nodes that can CONSUME output_type
    direction='output' → nodes that PRODUCE a type compatible with output_type
    """
    registry = get_registry()
    try:
        resolved = registry.type_catalogue.resolve(output_type)
    except PortTypeNotFoundError:
        raise HTTPException(
            status_code=400,
            detail=f"Type '{output_type}' is not registered in TypeCatalogue. "
                   f"Use GET /api/v1/types to list available types.",
        )
    if direction not in ("input", "output"):
        raise HTTPException(status_code=400, detail="direction must be 'input' or 'output'")

    nodes = registry.find_compatible_nodes(resolved, direction=direction)
    return [n.model_dump(mode="json") for n in nodes]
```

### GET /api/v1/types

```python
# In nodes.py (or a separate types.py — kept in nodes.py for simplicity)
@router.get("/types", tags=["types"])
def list_types():
    """List all registered PortDataType fully-qualified names from TypeCatalogue."""
    registry = get_registry()
    return registry.type_catalogue.list_types()
```

**Note:** The `/types` endpoint is registered at `/api/v1/types` (not `/api/v1/nodes/types`) to avoid ambiguity with the `{node_type}` path parameter. This requires it to be on a separate router or registered before the `{node_type}` routes.

### POST /api/v1/nodes/{node_type}/validate-config

Replaces the legacy `/validate-node` endpoint.

```python
@router.post("/{node_type}/validate-config")
def validate_node_config(node_type: str, payload: ValidateConfigRequest):
    """Validate a config dict against the node's Config model.

    Returns {"errors": {}} on success or {"errors": {"field": "message"}} on failure.
    """
    registry = get_registry()
    if node_type not in registry:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    try:
        node_class = registry.get_class(node_type)
        node_class.Config.model_validate(payload.config)
        return {"errors": {}}
    except pydantic.ValidationError as exc:
        errors = {}
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"]) if error["loc"] else "__root__"
            errors[field] = error["msg"]
        return {"errors": errors}
```

---

## 3. Pipeline API — app/api/routers/pipelines.py

### Router Definition

```python
# app/api/routers/pipelines.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import threading, tempfile, os, json
from datetime import datetime, timezone
from queue import Queue

from app.core.pipeline import run_pipeline
from app.core.logger import PipelineLogger
from app.core.registry_runtime import get_registry
from app.core.validation import validate_pipeline
import yaml as pyyaml

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
```

### POST /api/v1/pipelines/validate

```python
class PipelinePayload(BaseModel):
    yaml: str

@router.post("/validate")
def validate_pipeline_config(payload: PipelinePayload):
    """Validate a pipeline YAML without executing it.

    Accepts both legacy linear format and new DAG format with explicit edges.
    Validation checks: node types exist, configs are valid, port types are compatible.
    Does NOT enforce audio-specific first/last node rules.
    """
    try:
        config = pyyaml.safe_load(payload.yaml)
    except pyyaml.YAMLError as exc:
        return {"valid": False, "error": f"YAML parse error: {exc}"}

    registry = get_registry()
    try:
        validate_pipeline(config, registry)
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}

    return {"valid": True}
```

### POST /api/v1/pipelines/run

Replaces `/run-stream`. Streams NDJSON events.

```python
@router.post("/run")
async def run_pipeline_stream(payload: PipelinePayload):
    """Execute a pipeline and stream structured log events as NDJSON.

    Event types: pipeline_start, node_start, node_end, node_error,
                 pipeline_summary, done, error.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as f:
        f.write(payload.yaml.encode())
        config_path = f.name

    queue = Queue()
    logger = PipelineLogger(queue=queue)

    def run():
        try:
            run_pipeline(config_path, logger=logger)
        except Exception as e:
            queue.put({
                "type": "error",
                "error_type": e.__class__.__name__,
                "time": datetime.now(timezone.utc).isoformat(),  # ✅ UTC-aware
                "message": str(e),
            })
        finally:
            try:
                os.unlink(config_path)
            except FileNotFoundError:
                pass
            queue.put({"type": "done", "time": datetime.now(timezone.utc).isoformat()})
            queue.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while True:
            item = queue.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

    return StreamingResponse(stream(), media_type="application/json")
```

### POST /api/v1/pipelines/run-async — Fixed Run ID Tracking

This is the fix for known issue #6. The current implementation creates two `RunManager` instances with different `run_id` values. The fix creates exactly one `RunManager` before the thread starts and passes it into the thread.

**Root cause of the bug:**

```python
# CURRENT BROKEN CODE in app/api/main.py
@app.post("/run-async")
def run_pipeline_async(payload: dict):
    run_mgr = RunManager()          # ← RunManager #1, run_id = "abc12345"
    run_id = run_mgr.run_id         # ← returns "abc12345" to caller

    def _run():
        run_pipeline(config_path, ...)  # ← run_pipeline creates RunManager #2
                                        #   with run_id = "xyz99999"
                                        #   writes to workspace/runs/xyz99999/
                                        #   workspace/runs/abc12345/ stays empty

    return {"run_id": run_id}  # ← caller polls /run/abc12345/status → 404
```

**Fixed implementation:**

```python
# app/api/routers/pipelines.py (AFTER — fixed /run-async)
_async_runs: dict[str, dict] = {}

@router.post("/run-async")
def run_pipeline_async(payload: PipelinePayload):
    """Start a pipeline in a background thread. Returns run_id immediately.

    The returned run_id is the same one used by the pipeline executor,
    so GET /api/v1/runs/{run_id}/status will always find the correct run.
    """
    from app.core.run_manager import RunManager

    # Write config to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as f:
        f.write(payload.yaml.encode())
        config_path = f.name

    # Create ONE RunManager before the thread starts.
    # This run_id is returned to the caller AND used by the pipeline.
    run_mgr = RunManager()
    run_id = run_mgr.run_id
    run_mgr.save_config(payload.yaml)

    _async_runs[run_id] = {"status": "running"}

    def _run():
        try:
            logger = PipelineLogger()
            # Pass the pre-created run_mgr to run_pipeline so it uses
            # the same run directory. run_pipeline must accept run_manager=
            # as a keyword argument (or we call run_mgr methods directly).
            run_pipeline(config_path, logger=logger, run_manager=run_mgr)
            _async_runs[run_id]["status"] = "completed"
        except Exception as exc:
            _async_runs[run_id]["status"] = "failed"
            _async_runs[run_id]["error"] = str(exc)
            run_mgr.mark_failed(str(exc))
        finally:
            try:
                os.unlink(config_path)
            except FileNotFoundError:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return {"run_id": run_id}
```

**Required change to `run_pipeline`:** The `run_pipeline` function in `app/core/pipeline.py` must accept an optional `run_manager` keyword argument. When provided, it uses that `RunManager` instance instead of creating a new one. When not provided (e.g. from `/run-stream`), it creates its own as before.

```python
# app/core/pipeline.py — signature change
def run_pipeline(
    config_path: str,
    logger: PipelineLogger | None = None,
    checkpoint: bool = False,
    run_manager: RunManager | None = None,  # ← NEW optional parameter
) -> dict:
    if run_manager is None:
        run_manager = RunManager()
    # ... rest of function unchanged
```

### Template Endpoints

```python
TEMPLATES_DIR = Path("workspace/configs/templates")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

@router.get("/templates")
def list_templates():
    """List available pipeline templates."""
    # ... same logic as legacy GET /templates

@router.get("/templates/{name}")
def get_template(name: str):
    """Get YAML content of a named template."""
    # ... same logic as legacy GET /template/{name}

@router.post("/templates")
def save_template(payload: SaveTemplateRequest):
    """Save a user-defined template."""
    # ... same logic as legacy POST /templates

@router.delete("/templates/{name}")
def delete_template(name: str):
    """Delete a named template."""
    # ... same logic as legacy DELETE /templates/{name}
```

---

## 4. Runs API — app/api/routers/runs.py

### Router Definition

```python
# app/api/routers/runs.py
router = APIRouter(prefix="/runs", tags=["runs"])
```

### Endpoints

All run endpoints are moved from `main.py` to this router with the same logic. The only behavioral change is in the checkpoint endpoints: `node_index` (integer) is replaced by `node_id` (string, the directory name) for more robust addressing.

```python
@router.get("")
def list_runs():
    """GET /api/v1/runs — list all runs, newest first."""
    # Same logic as legacy GET /runs

@router.get("/{run_id}")
def get_run(run_id: str):
    """GET /api/v1/runs/{run_id} — get config and logs for a run."""
    # Same logic as legacy GET /run/{run_id}

@router.get("/{run_id}/status")
def get_run_status(run_id: str):
    """GET /api/v1/runs/{run_id}/status — poll async run status."""
    # Same logic as legacy GET /run/{run_id}/status

@router.get("/{run_id}/checkpoints")
def list_checkpoints(run_id: str):
    """GET /api/v1/runs/{run_id}/checkpoints — list checkpoints."""
    # Same logic as legacy GET /run/{run_id}/checkpoints

@router.get("/{run_id}/checkpoints/{node_id}")
def get_checkpoint_manifest(run_id: str, node_id: str):
    """GET /api/v1/runs/{run_id}/checkpoints/{node_id} — get manifest.json.

    node_id is the checkpoint directory name (e.g. "node_0_clean"),
    replacing the legacy integer node_index for more robust addressing.
    """
    # Looks up checkpoint_dir by exact name match on node_id
    # Falls back to prefix match for backward compat

@router.get("/{run_id}/checkpoints/{node_id}/samples")
def get_checkpoint_samples(run_id: str, node_id: str, n: int = 10):
    """GET /api/v1/runs/{run_id}/checkpoints/{node_id}/samples — get N samples."""
    # Same logic as legacy, using node_id instead of node_index
```

---

## 5. Data API — app/api/routers/data.py

### Router Definition

```python
# app/api/routers/data.py
router = APIRouter(prefix="/data", tags=["data"])
```

### Endpoints

```python
@router.get("/inputs")
def list_input_datasets():
    """GET /api/v1/data/inputs — list input dataset labels with file counts.
    Replaces GET /input-datasets."""

@router.get("/inputs/{label}")
def get_input_dataset(label: str):
    """GET /api/v1/data/inputs/{label} — list files in an input label.
    Replaces GET /input-dataset?label=."""

@router.post("/inputs/upload")
async def upload_mic_recording(file: UploadFile = File(...)):
    """POST /api/v1/data/inputs/upload — upload a mic recording.
    Replaces POST /mic-upload.
    Uses datetime.now(timezone.utc) for filename generation (UTC-aware fix).
    """
    from datetime import datetime, timezone
    safe_name = datetime.now(timezone.utc).strftime("mic_%Y%m%d_%H%M%S_%f") + ext  # ✅

@router.get("/outputs")
def list_output_datasets():
    """GET /api/v1/data/outputs — list all output datasets.
    Replaces GET /datasets."""

@router.get("/outputs/{project}/{version}")
def get_output_dataset(project: str, version: str):
    """GET /api/v1/data/outputs/{project}/{version} — list files in a dataset version.
    Replaces GET /dataset?project=&version=."""

@router.get("/outputs/{project}/{version}/stats")
def get_dataset_stats(project: str, version: str):
    """GET /api/v1/data/outputs/{project}/{version}/stats — dataset statistics.
    Replaces GET /dataset-stats?project=&version=."""

@router.post("/merge")
def merge_datasets(payload: MergeRequest):
    """POST /api/v1/data/merge — merge datasets.
    Replaces POST /merge (absorbed from merge.py router)."""
```

---

## 6. System API — app/api/routers/system.py

### Router Definition

```python
# app/api/routers/system.py
router = APIRouter(prefix="/system", tags=["system"])
```

### Endpoints

```python
@router.get("/health")
def health_check():
    """GET /api/v1/system/health — health check. Returns {"status": "ok"}."""
    return {"status": "ok"}

@router.post("/cleanup")
def cleanup(payload: CleanupRequest = CleanupRequest()):
    """POST /api/v1/system/cleanup — delete all runs and cache entries.
    Replaces POST /cleanup (absorbed from cleanup.py router)."""

@router.get("/projects-registry")
def get_projects_registry(q: str | None = None, status: str | None = None):
    """GET /api/v1/system/projects-registry — searchable list of dataset projects.
    Replaces GET /registry (renamed to avoid confusion with node registry)."""

@router.get("/webhooks")
def get_webhooks():
    """GET /api/v1/system/webhooks — get webhook configuration."""

@router.put("/webhooks")
def set_webhooks(payload: WebhookConfig):
    """PUT /api/v1/system/webhooks — set webhook configuration."""

@router.post("/webhooks/test")
def test_webhook():
    """POST /api/v1/system/webhooks/test — send a test notification."""
```

---

## 7. UTC Timestamp Fixes in main.py

All `datetime.utcnow()` calls in the current `main.py` are replaced:

```python
# BEFORE (in /run-stream error/done events)
"time": datetime.utcnow().isoformat()

# AFTER
from datetime import datetime, timezone
"time": datetime.now(timezone.utc).isoformat()

# BEFORE (in /mic-upload filename generation)
safe_name = datetime.utcnow().strftime("mic_%Y%m%d_%H%M%S_%f") + ext

# AFTER
safe_name = datetime.now(timezone.utc).strftime("mic_%Y%m%d_%H%M%S_%f") + ext
```

These fixes are applied in the new `pipelines.py` and `data.py` routers where the logic is moved.

---

## 8. Before/After Summary

### Structural Changes

| Aspect | Before | After |
|--------|--------|-------|
| `main.py` size | 500+ lines | < 100 lines |
| Endpoint prefix | `/` (root) | `/api/v1/` |
| Router files | 7 routers + monolith | 12 focused routers |
| Legacy paths | Active endpoints | 301 redirects |
| `datetime.utcnow()` | 4 occurrences | 0 occurrences |
| Duplicate `RUNS_ROOT` | Yes (known issue #5) | Fixed (defined once in `runs.py`) |
| Dual RunManager bug | Yes (known issue #6) | Fixed (single RunManager) |

### New Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/nodes` | Full node catalogue with metadata |
| `GET /api/v1/nodes/{type}` | Single node metadata |
| `GET /api/v1/nodes/{type}/config-schema` | JSON Schema for node config |
| `GET /api/v1/nodes/{type}/port-schema` | Port definitions |
| `GET /api/v1/nodes/compatible` | Find compatible nodes by port type |
| `GET /api/v1/types` | All registered PortDataTypes |
| `POST /api/v1/nodes/{type}/validate-config` | Validate a node config dict |
| `GET /api/v1/system/health` | Health check |
| `GET /api/v1/system/projects-registry` | Dataset project registry (renamed) |

---

## 9. Testing

### Unit Tests (in `tests/test_migration.py`)

- `test_nodes_endpoint_shape()` — assert `GET /api/v1/nodes` returns list with required keys
- `test_nodes_endpoint_includes_noise()` — assert `"noise"` node present in response
- `test_node_detail_404()` — assert `GET /api/v1/nodes/unknown` returns HTTP 404
- `test_config_schema_endpoint()` — assert `GET /api/v1/nodes/clean/config-schema` returns JSON Schema
- `test_port_schema_endpoint()` — assert `GET /api/v1/nodes/clean/port-schema` returns input/output dicts
- `test_types_endpoint()` — assert `GET /api/v1/types` returns non-empty list of strings
- `test_compatible_nodes_unknown_type()` — assert `GET /api/v1/nodes/compatible?output_type=unknown` returns HTTP 400
- `test_validate_config_valid()` — assert `POST /api/v1/nodes/clean/validate-config` returns `{"errors": {}}`
- `test_validate_config_invalid()` — assert invalid config returns `{"errors": {...}}`
- `test_legacy_schemas_redirect()` — assert `GET /schemas` returns HTTP 301 to `/api/v1/nodes`
- `test_run_async_single_run_id()` — assert `POST /api/v1/pipelines/run-async` returns run_id that exists in `workspace/runs/`
- `test_run_async_status_after_completion()` — assert `GET /api/v1/runs/{run_id}/status` returns `"completed"` after run

### Property Tests (in `tests/test_properties.py`)

- `test_property_11_nodes_response_shape()` — Property 11 (node catalogue response shape)
- `test_property_12_registry_getitem_shim()` — Property 12 (NodeRegistry __getitem__ consistency)
- `test_property_13_compatible_nodes_bidirectional()` — Property 13 (compatible nodes consistency)

### Integration Tests (in `tests/test_pipeline_integration.py`)

- `test_nodes_all_registered_nodes_present()` — assert all `registry.list_nodes()` entries appear in `GET /api/v1/nodes`
- `test_validate_pipeline_linear_format()` — assert linear YAML passes `POST /api/v1/pipelines/validate`
- `test_validate_pipeline_dag_format()` — assert DAG YAML with explicit edges passes validation
- `test_validate_pipeline_no_audio_constraint()` — assert pipeline starting with non-input node passes validation
- `test_run_async_roundtrip()` — full async run + status poll integration test
