# app/mcp/handlers/journey/readiness.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Host readiness MCP tool.
Owns:             get_readiness handler and schema
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

# ── Readiness (ops) ───────────────────────────────────────────────────────────

GET_READINESS_DESCRIPTION = (
    "Return backend_mode, worker_count, registry/store readiness checks."
)
GET_READINESS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**meta_props()},
    "additionalProperties": False,
}


def get_readiness_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return readiness snapshot (ready + store_corrupt/disk_full)."""
    from app.core.host.readiness import readiness_snapshot

    return readiness_snapshot()
