# app/mcp/handlers/journey/runs.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Run list, get, outputs, and compare MCP tools.
Owns:             list_runs, get_run, get_run_outputs, compare_runs handlers and schemas
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

# ── Runs (J1/J2/J6) ───────────────────────────────────────────────────────────

LIST_RUNS_DESCRIPTION = "List pipeline runs (newest first), optional project/status filter."
LIST_RUNS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "status": {"type": "string"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        **meta_props(),
    },
    "additionalProperties": False,
}

GET_RUN_DESCRIPTION = "Get run metadata for a run_id."
GET_RUN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        **meta_props(),
    },
    "required": ["run_id"],
    "additionalProperties": False,
}

GET_RUN_OUTPUTS_DESCRIPTION = "List downloadable output file descriptors for a run."
GET_RUN_OUTPUTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        **meta_props(),
    },
    "required": ["run_id"],
    "additionalProperties": False,
}


def list_runs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """MCP list_runs — same lister and store guard as REST GET /runs."""
    from app.core.runs.run_listing import list_runs
    from app.core.runs.run_status import normalize_status
    from app.core.persist.store_integrity import readiness_store_corrupt

    args = arguments or {}
    try:
        limit = max(1, min(int(args.get("limit") or 50), 500))
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        return handler_error("validation_failed", "limit/offset must be integers")
    # PERS-020 parity with REST ensure_store_readable (503 store_corrupt).
    if readiness_store_corrupt():
        return handler_error("store_corrupt", "Critical store index corrupt")

    page = list_runs(
        limit=limit,
        offset=offset,
        project=args.get("project"),
        status=args.get("status"),
    )
    rows: list[dict[str, Any]] = []
    for _entry, meta in page.rows:
        if "status" in meta:
            meta["status"] = normalize_status(str(meta.get("status")))
        rows.append(meta)
    return {"runs": rows, "count": len(rows), "total_matched": page.total_matched}


def get_run_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    from app.core.config import runs_dir
    from app.core.runs.run_status import normalize_status

    args = arguments or {}
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return handler_error("validation_failed", "run_id required")
    path = runs_dir() / run_id / "meta.json"
    if not path.is_file():
        return handler_error("not_found", f"Run '{run_id}' not found")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return handler_error("internal_error", f"Failed to read run meta: {exc}")
    if not isinstance(meta, dict):
        return handler_error("internal_error", "Corrupt run meta")
    if "status" in meta:
        meta["status"] = normalize_status(str(meta.get("status")))
    meta.setdefault("run_id", run_id)
    return meta


def get_run_outputs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.config import runs_dir
    from app.core.runs.run_outputs import list_run_output_files

    args = arguments or {}
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return handler_error("validation_failed", "run_id required")
    run_path = runs_dir() / run_id
    if not run_path.is_dir():
        return handler_error("not_found", f"Run '{run_id}' not found")
    return {"run_id": run_id, "outputs": list_run_output_files(run_id, run_path)}


COMPARE_RUNS_DESCRIPTION = "Compare two runs by returning both metas side-by-side."
COMPARE_RUNS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id_a": {"type": "string"},
        "run_id_b": {"type": "string"},
        **meta_props(),
    },
    "required": ["run_id_a", "run_id_b"],
    "additionalProperties": False,
}



def compare_runs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    a = get_run_handler({"run_id": args.get("run_id_a")})
    b = get_run_handler({"run_id": args.get("run_id_b")})
    if a.get("error"):
        return a
    if b.get("error"):
        return b
    return {"run_a": a, "run_b": b}
