# app/api/routers/pipelines.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for pipeline validation, synchronous streaming
                  execution, async execution, and template management.
Owns:             Route definitions for POST /pipelines/validate,
                  POST /pipelines/run (NDJSON stream),
                  POST /pipelines/run-async,
                  GET/POST/DELETE /pipelines/templates/*.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain pipeline execution logic — delegate to SDK/orchestrator.
Dependencies:     fastapi, app.core.sdk, app.core.ir, app.core.config.
Reason To Change: New pipeline endpoint added, streaming protocol changes,
                  or template storage changes.

Accepts both IR JSON (canonical) and YAML (deprecated) formats.
IR JSON is detected by the presence of a 'schema_version' field in the request body.
All execution delegates to Pipeline.run_with_manager() (SDK as source of truth).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from queue import Queue
from typing import Any

import yaml
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.core.logger import PipelineLogger
from app.core.registry_runtime import get_registry
from app.core.validation import validate_pipeline

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _templates_dir() -> Path:
    """Return the templates directory, resolved from GRAPHYN_PROJECT_DIR."""
    from app.core.config import project_dir as _project_dir
    return _project_dir() / "configs" / "templates"


# ── Request models ────────────────────────────────────────────────────────────

class SaveTemplateRequest(BaseModel):
    name: str
    yaml: str  # field name kept for API backward compat; value is now IR JSON string


# ── Format detection helper ───────────────────────────────────────────────────

def _is_ir_payload(payload: dict) -> bool:
    """Detect IR JSON format by presence of schema_version field (Req 4.7.5)."""
    return "schema_version" in payload


def _build_pipeline_from_payload(payload: dict):
    """Build a Pipeline from either IR JSON or YAML payload.

    Returns (pipeline, deprecation_header) where deprecation_header is None
    for IR JSON and a warning string for YAML payloads.

    Delegates to SDK (V1.md §3.1).
    """
    from app.core.sdk import Pipeline, PipelineNode
    from app.core.ir.loader import load_ir
    from app.core.ir.yaml_shim import yaml_config_to_ir

    if _is_ir_payload(payload):
        # IR JSON path (Req 4.7.1, 4.7.3)
        graph = load_ir(payload)
        nodes = [PipelineNode(n.node_type, dict(n.config)) for n in graph.nodes]
        pipeline = Pipeline(
            nodes=nodes,
            seed=graph.metadata.seed,
            name=graph.metadata.name,
            description=graph.metadata.description,
        )
        return pipeline, None
    else:
        # YAML path (Req 4.7.2, 4.7.4)
        yaml_str = payload.get("yaml", "")
        try:
            raw = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=422, detail=f"YAML parse error: {exc}")
        graph = yaml_config_to_ir(raw)
        nodes = [PipelineNode(n.node_type, dict(n.config)) for n in graph.nodes]
        pipeline = Pipeline(
            nodes=nodes,
            seed=graph.metadata.seed,
            name=graph.metadata.name,
            description=graph.metadata.description,
        )
        return pipeline, "YAML pipeline input is deprecated. Use IR JSON format."


# ── Validate ──────────────────────────────────────────────────────────────────

@router.post("/validate", summary="Validate a pipeline YAML or IR JSON")
def validate_pipeline_config(payload: dict = Body(...)):
    """Validate a pipeline config without executing it.

    Accepts both YAML format ({"yaml": "..."}) and IR JSON format.
    Uses yaml_config_to_ir() for YAML (no DeprecationWarning during validation).

    Req 4.8
    """
    if _is_ir_payload(payload):
        # IR JSON validation (Req 4.8.1, 4.8.3, 4.8.4)
        try:
            from app.core.ir.loader import load_ir
            graph = load_ir(payload)
            return {"valid": True, "node_count": len(graph.nodes)}
        except Exception as exc:
            return JSONResponse(
                status_code=422,
                content={"valid": False, "error": str(exc)},
            )
    else:
        # YAML validation — use yaml_config_to_ir (no DeprecationWarning) (Req 4.8.2, 4.8.5)
        yaml_str = payload.get("yaml", "")
        try:
            config = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            return {"valid": False, "error": f"YAML parse error: {exc}"}

        registry = get_registry()
        try:
            validate_pipeline(config, registry)
        except ValueError as exc:
            return {"valid": False, "error": str(exc)}

        headers = {"X-Deprecation-Warning": "YAML pipeline input is deprecated. Use IR JSON format."}
        return JSONResponse(content={"valid": True}, headers=headers)


# ── Run (streaming) ───────────────────────────────────────────────────────────

@router.post("/run", summary="Run a pipeline and stream log events")
def run_pipeline_stream(payload: dict = Body(...)):
    """Execute a pipeline and stream NDJSON log events as they occur.

    Delegates to Pipeline.run_with_manager() (V1.md §3.1).
    Accepts both IR JSON and YAML formats (Req 4.7).
    """
    try:
        pipeline, deprecation_header = _build_pipeline_from_payload(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    queue: Queue = Queue(maxsize=512)  # bounded — prevents memory leak on slow clients
    logger = PipelineLogger(queue=queue)

    def _run():
        from datetime import datetime, timezone
        try:
            pipeline.run(logger=logger)
            queue.put({
                "type": "done",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            queue.put({
                "type": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
        finally:
            queue.put(None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    def stream():
        while True:
            item = queue.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

    headers = {}
    if deprecation_header:
        headers["X-Deprecation-Warning"] = deprecation_header

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers=headers)


# ── Run async ─────────────────────────────────────────────────────────────────

@router.post("/run-async", summary="Start a pipeline run asynchronously")
def run_pipeline_async(payload: dict = Body(...)):
    """Start a pipeline run in a background thread and return the run_id immediately.

    Delegates to Pipeline.run_with_manager() (V1.md §3.1).
    Accepts both IR JSON and YAML formats (Req 4.7).
    """
    try:
        pipeline, deprecation_header = _build_pipeline_from_payload(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    from app.core.run_journal import RunManager

    # Create ONE RunManager before the thread starts so run_id is known immediately
    run_mgr = RunManager()
    run_id = run_mgr.run_id

    # Save YAML config for backward compat if YAML was submitted
    if not _is_ir_payload(payload):
        run_mgr.save_config(payload.get("yaml", ""))

    def _run():
        try:
            pipeline.run(run_manager=run_mgr)
        except Exception as exc:
            run_mgr.mark_failed(str(exc))

    threading.Thread(target=_run, daemon=True).start()

    headers = {}
    if deprecation_header:
        headers["X-Deprecation-Warning"] = deprecation_header

    return JSONResponse(content={"run_id": run_id}, headers=headers)


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates", summary="List pipeline templates")
def list_templates():
    """Return a list of available pipeline template names."""
    templates_dir = _templates_dir()
    if not templates_dir.exists():
        return []
    return [f.stem.replace(".graph", "") for f in sorted(templates_dir.glob("*.graph.json"))]


@router.get("/templates/{name}", summary="Get a pipeline template")
def get_template(name: str):
    """Return the IR JSON content of a named template."""
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    path = _templates_dir() / f"{name}.graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    import json as _json
    return {"name": name, "graph": _json.loads(path.read_text(encoding="utf-8"))}


@router.post("/templates", summary="Save a pipeline template")
def save_template(payload: SaveTemplateRequest):
    """Save a new pipeline template as IR JSON."""
    if not _SAFE_NAME_RE.match(payload.name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    templates_dir = _templates_dir()
    templates_dir.mkdir(parents=True, exist_ok=True)
    path = templates_dir / f"{payload.name}.graph.json"
    path.write_text(payload.yaml, encoding="utf-8")
    return {"name": payload.name, "saved": True}


@router.delete("/templates/{name}", summary="Delete a pipeline template")
def delete_template(name: str):
    """Delete a named pipeline template."""
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    path = _templates_dir() / f"{name}.graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    path.unlink()
    return {"name": name, "deleted": True}
