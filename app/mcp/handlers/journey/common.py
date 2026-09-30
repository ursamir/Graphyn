# app/mcp/handlers/journey/common.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Shared helpers for journey MCP handlers.
Owns:             _err, _require_project_dir, _meta_props
Public Surface:   _err, _require_project_dir, _meta_props
Must NOT:         Register tools or own a product domain.
Dependencies:     app.domain.project_manager (lazy)
Reason To Change: Journey error shape or project lookup changes.
"""
from __future__ import annotations

from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


def _require_project_dir(project: str):
    from app.domain.project_manager import ProjectManager

    name = (project or "").strip()
    if not name:
        raise ValueError("project is required")
    return ProjectManager()._require_project(name), name


def _meta_props() -> dict[str, Any]:
    return {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        }
    }

# Public names. A leading underscore stays private to this module.
handler_error = _err
meta_props = _meta_props
require_project_dir = _require_project_dir
