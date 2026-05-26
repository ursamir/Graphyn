# app/mcp/handlers/provenance.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   list_artifacts, get_artifact_lineage, replay_run tool handlers.
                  Thin delegation to ArtifactStore, ProvenanceStore, and the
                  pipeline executor.
Owns:             list_artifacts_handler, get_artifact_lineage_handler,
                  replay_run_handler and their SCHEMA/DESCRIPTION constants,
                  _REPLAY_EXECUTOR (module-level shared ThreadPoolExecutor).
Public Surface:   All three handler functions above.
Must NOT:         Contain artifact storage logic — delegates to ArtifactStore
                  and ProvenanceStore. Must not import from app.domain.
Dependencies:     BC5 (runtime_backend — module-level import), BC6 (artifact_store,
                  provenance, run_journal — lazy), BC1 (ir.loader — lazy),
                  app.core.config (runs_dir — lazy), stdlib (concurrent.futures).
Reason To Change: Provenance tool schemas change, or replay strategy changes.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.runtime_backend import get_backend as _get_backend  # module-level — patchable in tests

# NEW-7 fix: module-level shared executor — avoids creating a new ThreadPoolExecutor
# per replay_run call (which leaks OS threads under load).
_REPLAY_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ── Tool schema constants ─────────────────────────────────────────────────────

LIST_ARTIFACTS_DESCRIPTION = (
    "List registered artifacts with optional filters. "
    "Returns all artifacts or a filtered subset by run_id, node_type, or artifact_type."
)

LIST_ARTIFACTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "description": "Filter artifacts by run ID.",
        },
        "node_type": {
            "type": "string",
            "description": "Filter artifacts by node type (e.g. 'clean', 'train').",
        },
        "artifact_type": {
            "type": "string",
            "description": "Filter artifacts by artifact type (e.g. 'audio_samples', 'model_artifact').",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

GET_ARTIFACT_LINEAGE_DESCRIPTION = (
    "Retrieve the full upstream lineage tree for an artifact. "
    "Returns a recursive tree of provenance records showing how the artifact was produced."
)

GET_ARTIFACT_LINEAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "artifact_id": {
            "type": "string",
            "description": "The artifact ID to trace lineage for.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["artifact_id"],
    "additionalProperties": False,
}

REPLAY_RUN_DESCRIPTION = (
    "Replay a previous run from its stored graph.json. "
    "Loads the graph from workspace/runs/{run_id}/graph.json and executes it asynchronously. "
    "Returns a new run_id immediately."
)

REPLAY_RUN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "description": "The original run ID to replay.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["run_id"],
    "additionalProperties": False,
}


# ── Handlers ──────────────────────────────────────────────────────────────────


def list_artifacts_handler(arguments: dict[str, Any]) -> dict:
    """List artifacts with optional filters (Req 6 §1).

    Returns {"artifacts": [...], "count": N} or an error dict.
    """
    try:
        from app.core.artifact_store import ArtifactStore

        run_id = arguments.get("run_id")
        node_type = arguments.get("node_type")
        artifact_type = arguments.get("artifact_type")

        store = ArtifactStore()
        records = store.list(run_id=run_id, node_type=node_type, artifact_type=artifact_type)
        return {
            "artifacts": [r.model_dump(mode="json") for r in records],
            "count": len(records),
        }
    except Exception as e:
        return {"error": True, "error_type": "store_error", "message": str(e)}


def get_artifact_lineage_handler(arguments: dict[str, Any]) -> dict:
    """Return the full lineage tree for an artifact (Req 6 §2).

    Returns the lineage tree dict or an error dict.
    """
    artifact_id = arguments.get("artifact_id")
    if not artifact_id:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "artifact_id is required",
        }

    try:
        from app.core.provenance import ProvenanceStore

        store = ProvenanceStore()
        lineage = store.get_lineage(artifact_id)
        return lineage
    except Exception as e:
        return {"error": True, "error_type": "store_error", "message": str(e)}


def replay_run_handler(arguments: dict[str, Any]) -> dict:
    """Replay a previous run from its stored graph.json (Req 6 §3).

    Delegates to Pipeline.run_with_manager() (V1.md §3.1).
    Returns {"run_id": new_run_id, "status": "started"} or an error dict.
    """
    run_id = arguments.get("run_id")
    if not run_id:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "run_id is required",
        }

    try:
        from pathlib import Path

        from app.core.ir.loader import load_ir_from_file
        from app.core.run_journal import RunManager

        from app.core.config import runs_dir as _runs_dir
        run_dir = _runs_dir() / run_id

        if not run_dir.exists():
            return {
                "error": True,
                "error_type": "unknown_run_id",
                "message": f"Run '{run_id}' not found",
            }

        graph_path = run_dir / "graph.json"
        if not graph_path.exists():
            return {
                "error": True,
                "error_type": "graph_not_found",
                "message": f"graph.json not found for run '{run_id}'",
            }

        graph = load_ir_from_file(str(graph_path))
        new_run_manager = RunManager()

        # NEW-7 fix: use module-level shared executor instead of per-call pool.
        _REPLAY_EXECUTOR.submit(_get_backend().execute, graph, run_manager=new_run_manager)

        return {"run_id": new_run_manager.run_id, "status": "started"}
    except Exception as e:
        return {"error": True, "error_type": "replay_error", "message": str(e)}
