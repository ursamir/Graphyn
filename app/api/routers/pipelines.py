# app/api/routers/pipelines.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for pipeline validation, synchronous streaming
                  execution, async execution, and template management.
Owns:             Route definitions for POST /pipelines/validate,
                  POST /pipelines/run (NDJSON stream),
                  POST /pipelines/run-async,
                  GET/POST/DELETE /pipelines/templates/*,
                  POST /pipelines/templates/sync-examples,
                  GET /pipelines/examples.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain pipeline execution logic — delegate to SDK/orchestrator.
Dependencies:     fastapi, app.core.sdk, app.core.ir, app.core.config.
Reason To Change: New pipeline endpoint added, streaming protocol changes,
                  or template storage changes.

Accepts both IR JSON (canonical) and YAML (deprecated) formats.
IR JSON is detected by the presence of a 'schema_version' field in the request body.
All execution delegates to RuntimeBackend.execute() with GraphIR as source of truth.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
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
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _templates_dir() -> Path:
    """Return the templates directory, resolved from GRAPHYN_PROJECT_DIR."""
    from app.core.config import project_dir as _project_dir
    return _project_dir() / "configs" / "templates"


def _template_meta_path(name: str) -> Path:
    return _templates_dir() / name / "meta.json"


def _template_version_path(name: str, version: str) -> Path:
    return _templates_dir() / name / f"{version}.graph.json"


def _read_template_meta(name: str) -> dict[str, Any]:
    path = _template_meta_path(name)
    if not path.exists():
        return {"name": name, "latest_version": None, "versions": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"name": name, "latest_version": None, "versions": {}}


def _write_template_meta(name: str, meta: dict[str, Any]) -> None:
    meta_path = _template_meta_path(name)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


# ── Request models ────────────────────────────────────────────────────────────

class SaveTemplateRequest(BaseModel):
    name: str
    yaml: str  # field name kept for API backward compat; value is now IR JSON string
    version: str | None = None
    description: str = ""


# ── Format detection helper ───────────────────────────────────────────────────

def _is_ir_payload(payload: dict) -> bool:
    """Detect IR JSON format by presence of schema_version field (Req 4.7.5)."""
    return "schema_version" in payload


def _build_graph_from_payload(payload: dict):
    """Build a GraphIR from either IR JSON or YAML payload.

    Returns (graph, deprecation_header) where deprecation_header is None
    for IR JSON and a warning string for YAML payloads.

    Delegates to SDK (V1.md §3.1).
    """
    from app.core.ir.loader import load_ir
    from app.core.ir.yaml_shim import yaml_config_to_ir

    from app.core.workspace_paths import apply_output_rewire

    if _is_ir_payload(payload):
        # IR JSON path (Req 4.7.1, 4.7.3)
        graph = apply_output_rewire(load_ir(payload))
        return graph, None
    else:
        # YAML path (Req 4.7.2, 4.7.4)
        yaml_str = payload.get("yaml", "")
        try:
            raw = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=422, detail=f"YAML parse error: {exc}")
        graph = apply_output_rewire(yaml_config_to_ir(raw))
        return graph, "YAML pipeline input is deprecated. Use IR JSON format."


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
            from app.core.workspace_paths import apply_output_rewire
            graph = apply_output_rewire(load_ir(payload))
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
        return JSONResponse(content={"valid": True, "node_count": len(config.get("pipeline", {}).get("nodes", []))}, headers=headers)


# ── Run (streaming) ───────────────────────────────────────────────────────────

@router.post("/run", summary="Run a pipeline and stream log events")
def run_pipeline_stream(payload: dict = Body(...)):
    """Execute a pipeline and stream NDJSON log events as they occur.

    Delegates to get_backend().execute(graph) (V1.md §3.1).
    Accepts both IR JSON and YAML formats (Req 4.7).
    """
    try:
        graph, deprecation_header = _build_graph_from_payload(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    queue: Queue = Queue(maxsize=512)  # bounded — prevents memory leak on slow clients
    logger = PipelineLogger(queue=queue)

    def _run():
        from datetime import datetime, timezone
        from app.core.runtime_backend import get_backend  # noqa: PLC0415
        try:
            get_backend().execute(graph, logger=logger)
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
            try:
                yield json.dumps(item) + "\n"
            except (TypeError, ValueError) as exc:
                yield json.dumps({"type": "error", "message": f"Serialization error: {exc}"}) + "\n"
                break

    headers = {}
    if deprecation_header:
        headers["X-Deprecation-Warning"] = deprecation_header

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers=headers)


# ── Run async ─────────────────────────────────────────────────────────────────

@router.post("/run-async", summary="Start a pipeline run asynchronously")
def run_pipeline_async(payload: dict = Body(...)):
    """Start a pipeline run in a background thread and return the run_id immediately.

    Delegates to get_backend().execute(graph) (V1.md §3.1).
    Accepts both IR JSON and YAML formats (Req 4.7).
    """
    try:
        graph, deprecation_header = _build_graph_from_payload(payload)
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
            from app.core.runtime_backend import get_backend  # noqa: PLC0415
            get_backend().execute(graph, run_manager=run_mgr)
        except Exception as exc:
            run_mgr.mark_failed(str(exc))

    threading.Thread(target=_run, daemon=True).start()

    headers = {}
    if deprecation_header:
        headers["X-Deprecation-Warning"] = deprecation_header

    return JSONResponse(content={"run_id": run_id}, headers=headers)


# ── Templates ─────────────────────────────────────────────────────────────────

@router.post("/templates/sync-examples", summary="Import example graphs as templates")
def sync_example_templates(force: bool = True):
    """Copy all ``examples/**/*.graph.json`` into the project templates directory.

    Absolute paths under the repo root are rewritten to relative paths so graphs
    run correctly from the project root. Safe to re-run (overwrites when force=true).
    """
    from app.core.example_templates import sync_example_templates as _sync

    return _sync(force=force)


@router.get("/examples", summary="List bundled example Graph IR files")
def list_examples():
    """Return metadata for Graph IR examples under the repository ``examples/`` tree."""
    from app.core.example_templates import discover_example_graphs

    return discover_example_graphs()


@router.get("/templates", summary="List pipeline templates")
def list_templates():
    """Return a list of available pipeline template names.

    Supports both legacy flat templates (`{name}.graph.json`) and
    versioned templates (`{name}/{version}.graph.json` + meta.json).
    """
    templates_dir = _templates_dir()
    if not templates_dir.exists():
        return []
    names: set[str] = set()
    for f in sorted(templates_dir.glob("*.graph.json")):
        names.add(f.stem.replace(".graph", ""))
    for d in sorted(templates_dir.iterdir()):
        if d.is_dir() and _SAFE_NAME_RE.match(d.name):
            names.add(d.name)
    return sorted(names)


@router.get("/templates/{name}/versions", summary="List template versions")
def list_template_versions(name: str):
    """List available versions for one template.

    Supports versioned dirs (`{name}/{version}.graph.json`) and legacy flat
    files (`{name}.graph.json`). Legacy-only templates return ``versions: []``
    with ``storage: "legacy_flat"`` (HTTP 200) so clients can still open them
    via ``GET /templates/{name}`` without a version query.
    """
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    templates_dir = _templates_dir()
    template_dir = templates_dir / name
    legacy_path = templates_dir / f"{name}.graph.json"
    has_dir = template_dir.is_dir()
    has_legacy = legacy_path.is_file()
    if not has_dir and not has_legacy:
        raise HTTPException(status_code=404, detail="Template not found")

    versions: list[str] = []
    if has_dir:
        versions = sorted(
            p.stem.replace(".graph", "")
            for p in template_dir.glob("*.graph.json")
            if p.name != "latest.graph.json"
        )
    meta = _read_template_meta(name) if has_dir else {}
    latest = meta.get("latest_version") if has_dir else None
    if latest is None and versions:
        latest = versions[-1]
    return {
        "name": name,
        "latest_version": latest,
        "versions": versions,
        "storage": "versioned" if versions else ("legacy_flat" if has_legacy else "empty"),
    }


@router.get("/templates/{name}", summary="Get a pipeline template")
def get_template(name: str, version: str | None = None):
    """Return the content of a named template.

    Supports both legacy YAML payloads and IR-JSON payloads.
    """
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    if version is not None and not _SAFE_VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Invalid template version")

    path: Path
    if version:
        path = _template_version_path(name, version)
    else:
        meta = _read_template_meta(name)
        latest = meta.get("latest_version")
        if isinstance(latest, str) and _SAFE_VERSION_RE.match(latest):
            path = _template_version_path(name, latest)
        else:
            path = _templates_dir() / f"{name}.graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    text = path.read_text(encoding="utf-8")
    import json as _json
    try:
        graph = _json.loads(text)
        # Always migrate legacy node aliases so the console never paints
        # obsolete types like ``input`` / ``clean`` that are not registered.
        from app.core.ir.loader import dump_ir, load_ir
        from app.core.workspace_paths import apply_output_rewire

        graph = dump_ir(apply_output_rewire(load_ir(graph)))
        response = {"name": name, "graph": graph}
        if version:
            response["version"] = version
        return response
    except _json.JSONDecodeError:
        return {"name": name, "yaml": text}
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Template IR is invalid or could not be migrated: {exc}",
        ) from exc


@router.post("/templates", summary="Save a pipeline template")
def save_template(payload: SaveTemplateRequest):
    """Save a new pipeline template as IR JSON."""
    if not _SAFE_NAME_RE.match(payload.name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    # Validate submitted template is parseable IR JSON.
    try:
        from app.core.ir.loader import load_ir  # noqa: PLC0415
        parsed = json.loads(payload.yaml)
        load_ir(parsed)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid IR JSON template: {exc}")

    from app.core.workspace_paths import rewire_graph_outputs

    parsed = rewire_graph_outputs(parsed, slug=payload.name)
    body = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"

    version = payload.version or datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")
    if not _SAFE_VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Invalid template version")

    template_dir = _templates_dir() / payload.name
    template_dir.mkdir(parents=True, exist_ok=True)
    path = _template_version_path(payload.name, version)
    path.write_text(body, encoding="utf-8")

    # Backward-compat latest pointer for older clients.
    legacy_path = _templates_dir() / f"{payload.name}.graph.json"
    legacy_path.write_text(body, encoding="utf-8")

    meta = _read_template_meta(payload.name)
    versions = meta.get("versions", {})
    versions[version] = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "description": payload.description or "",
    }
    meta.update(
        {
            "name": payload.name,
            "latest_version": version,
            "versions": versions,
        }
    )
    _write_template_meta(payload.name, meta)
    return {"name": payload.name, "version": version, "saved": True}


@router.delete("/templates/{name}", summary="Delete a pipeline template")
def delete_template(name: str, version: str | None = None):
    """Delete a named pipeline template."""
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    if version is not None and not _SAFE_VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Invalid template version")

    template_dir = _templates_dir() / name
    legacy_path = _templates_dir() / f"{name}.graph.json"

    if version:
        path = _template_version_path(name, version)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Template version not found")
        path.unlink()

        meta = _read_template_meta(name)
        versions = meta.get("versions", {})
        versions.pop(version, None)
        latest = meta.get("latest_version")
        if latest == version:
            remaining = sorted(versions.keys())
            meta["latest_version"] = remaining[-1] if remaining else None
        meta["versions"] = versions
        _write_template_meta(name, meta)
        return {"name": name, "version": version, "deleted": True}

    # Delete full template (all versions + legacy pointer)
    if not template_dir.exists() and not legacy_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    if template_dir.exists():
        for p in template_dir.glob("*.graph.json"):
            p.unlink()
        meta_path = template_dir / "meta.json"
        if meta_path.exists():
            meta_path.unlink()
        try:
            template_dir.rmdir()
        except OSError:
            pass

    if legacy_path.exists():
        legacy_path.unlink()

    if not template_dir.exists() and not legacy_path.exists():
        return {"name": name, "deleted": True}
    raise HTTPException(status_code=500, detail="Failed to delete template cleanly")
