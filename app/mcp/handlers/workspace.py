# app/mcp/handlers/workspace.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Thin MCP tools for experiments, trace, projects, and data
                  listing (agent parity with REST observe surfaces).
Owns:             list_experiments / get_trace / list_projects / list_data_inputs
                  handlers + schemas.
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA
Must NOT:         Import app.domain; must not mutate workspace.
Dependencies:     app.core.experiments, app.core.trace, app.core.config.
Reason To Change: New observe tools or response schema changes.
"""
from __future__ import annotations

from typing import Any

LIST_EXPERIMENTS_DESCRIPTION = (
    "List experiment blocks (metrics/runs) from the workspace run journal. "
    "Optional project filter."
)
LIST_EXPERIMENTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {
            "type": "string",
            "description": "Optional project name filter.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

GET_TRACE_DESCRIPTION = (
    "Assemble a Trace backtrack payload for an artifact_id and/or run_id "
    "(same as GET /api/v1/trace)."
)
GET_TRACE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "artifact_id": {"type": "string"},
        "node_id": {"type": "string"},
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

LIST_PROJECTS_DESCRIPTION = (
    "List dataset project folders under workspace/datasets/output (names + status when present)."
)
LIST_PROJECTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "q": {
            "type": "string",
            "description": "Optional substring filter on project name.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

LIST_DATA_INPUTS_DESCRIPTION = (
    "List input dataset labels under workspace/datasets/input (names + file counts)."
)
LIST_DATA_INPUTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}


def list_experiments_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.experiments import list_experiments

    args = arguments or {}
    project = args.get("project") if isinstance(args.get("project"), str) else None
    project = (project or "").strip() or None
    blocks = list_experiments(project=project)
    return {"experiments": blocks, "count": len(blocks)}


def get_trace_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.trace import assemble_trace

    args = arguments or {}
    run_id = args.get("run_id") if isinstance(args.get("run_id"), str) else None
    artifact_id = args.get("artifact_id") if isinstance(args.get("artifact_id"), str) else None
    node_id = args.get("node_id") if isinstance(args.get("node_id"), str) else None
    try:
        return assemble_trace(
            run_id=(run_id or "").strip() or None,
            artifact_id=(artifact_id or "").strip() or None,
            node_id=(node_id or "").strip() or None,
        )
    except ValueError as exc:
        return {"error_type": "invalid_request", "message": str(exc)}


def list_projects_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    from app.core.config import datasets_output_dir

    args = arguments or {}
    q = args.get("q") if isinstance(args.get("q"), str) else None
    q_lower = (q or "").strip().lower()
    root = datasets_output_dir()
    projects: list[dict[str, Any]] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if q_lower and q_lower not in child.name.lower():
                continue
            meta: dict[str, Any] = {"name": child.name}
            status_path = child / "project.json"
            if status_path.is_file():
                try:
                    raw = json.loads(status_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        if raw.get("status"):
                            meta["status"] = raw["status"]
                        if raw.get("description"):
                            meta["description"] = raw["description"]
                except Exception:
                    pass
            projects.append(meta)
    return {"projects": projects, "count": len(projects)}


def list_data_inputs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import os

    from app.core.config import datasets_input_dir

    root = datasets_input_dir()
    labels: list[dict[str, Any]] = []
    if root.is_dir():
        for label in sorted(os.listdir(root)):
            path = root / label
            if not path.is_dir():
                continue
            try:
                n = sum(1 for p in path.rglob("*") if p.is_file())
            except OSError:
                n = 0
            labels.append({"label": label, "file_count": n})
    return {"inputs": labels, "count": len(labels)}
