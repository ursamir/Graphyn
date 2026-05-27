# app/mcp/handlers/artifacts.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   inspect_run tool handler. Reads run metadata, logs, graph
                  snapshots, and checkpoint manifests from the workspace.
Owns:             inspect_run_handler(), INSPECT_RUN_SCHEMA/DESCRIPTION,
                  _get_runs_dir() (lazy path resolver).
Public Surface:   inspect_run_handler(arguments) -> dict
Must NOT:         Contain business logic beyond filesystem reads. Must not
                  import from app.domain.
Dependencies:     app.core.config (runs_dir — lazy), stdlib (json, os, pathlib).
Reason To Change: inspect_run tool schema changes, new inspection modes are
                  added, or workspace layout changes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Workspace path resolution (Req 5.10) ──────────────────────────────────────
# Resolved dynamically at call time so that GRAPHYN_PROJECT_DIR changes (e.g.
# in tests) are respected without requiring a module reload.
def _get_runs_dir() -> Path:
    """Return the runs directory, resolving GRAPHYN_PROJECT_DIR at call time."""
    from app.core.config import runs_dir as _runs_dir
    return _runs_dir()


# ── Tool schema constants ─────────────────────────────────────────────────────

INSPECT_RUN_DESCRIPTION = (
    "Inspect a pipeline run's metadata, logs, graph snapshot, and artifacts. "
    "Supports listing all runs, retrieving run metadata, logs, graph.json, "
    "checkpoint manifests, and status-only queries."
)

INSPECT_RUN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "description": "Run ID to inspect. Omit to list all runs.",
        },
        "logs": {
            "type": "boolean",
            "description": (
                "Return logs.json contents (requires run_id). "
                "Mutually exclusive with graph, checkpoints, node_id, and status_only — "
                "only the first matching flag is evaluated."
            ),
            "default": False,
        },
        "graph": {
            "type": "boolean",
            "description": (
                "Return graph.json contents (requires run_id). "
                "Mutually exclusive with logs, checkpoints, node_id, and status_only — "
                "only the first matching flag is evaluated."
            ),
            "default": False,
        },
        "checkpoints": {
            "type": "boolean",
            "description": (
                "Return list of node IDs with checkpoints (requires run_id). "
                "Mutually exclusive with logs, graph, node_id, and status_only — "
                "only the first matching flag is evaluated."
            ),
            "default": False,
        },
        "node_id": {
            "type": "string",
            "description": (
                "Return checkpoint manifest for this node (requires run_id). "
                "Mutually exclusive with logs, graph, checkpoints, and status_only — "
                "only the first matching flag is evaluated."
            ),
        },
        "status_only": {
            "type": "boolean",
            "description": (
                "Return only the run status (requires run_id). "
                "Mutually exclusive with logs, graph, checkpoints, and node_id — "
                "evaluated first when set."
            ),
            "default": False,
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}


# ── Handler ───────────────────────────────────────────────────────────────────


def inspect_run_handler(arguments: dict[str, Any]) -> Any:
    """Inspect run artifacts (Req 5.1–5.12).

    Delegates to RunManager workspace path conventions (Req 5.10, 6.5).

    Dispatch table:
      - no run_id          → list all runs, newest-first (Req 5.1)
      - run_id only        → return full meta.json (Req 5.2)
      - status_only: true  → return {"status": ...} (Req 5.9)
      - logs: true         → return logs.json (Req 5.3, 5.12)
      - graph: true        → return graph.json (Req 5.4, 5.6)
      - checkpoints: true  → return list of node IDs (Req 5.7)
      - node_id provided   → return checkpoint manifest (Req 5.8)

    Every file read is wrapped in try/except — no unhandled exceptions (Req 5.11).
    """
    run_id = arguments.get("run_id")

    # Resolve workspace at call time (Req 5.10) so GRAPHYN_PROJECT_DIR changes
    # are respected without a module reload.
    _RUNS_DIR = _get_runs_dir()

    # ── List all runs ──────────────────────────────────────────────────────────
    # Req 5.1: return all runs ordered newest-first by created_at.
    if run_id is None:
        if not _RUNS_DIR.exists():
            return {"runs": []}

        runs = []
        for run_dir in _RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                with meta_path.open("r") as f:
                    meta = json.load(f)
                runs.append({
                    "run_id": meta.get("run_id", run_dir.name),
                    "status": meta.get("status", "unknown"),
                    "created_at": meta.get("created_at"),
                    "duration_s": meta.get("duration_s"),
                    "num_nodes": meta.get("num_nodes", 0),
                })
            except Exception:
                # Req 5.11: never raise; return partial info for unreadable runs.
                runs.append({
                    "run_id": run_dir.name,
                    "status": "unknown",
                    "created_at": None,
                    "duration_s": None,
                    "num_nodes": 0,
                })

        # Req 5.1: sort newest-first by created_at.
        # Parse ISO 8601 timestamps before comparing so that mixed "Z" and
        # "+00:00" suffixes (both valid UTC representations) sort correctly.
        # String comparison would place "Z" after "+" lexicographically,
        # producing wrong order when the two suffix styles are mixed.
        def _parse_ts(ts: str | None) -> datetime:
            if not ts:
                return datetime.min.replace(tzinfo=timezone.utc)
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)

        runs.sort(key=lambda r: _parse_ts(r.get("created_at")), reverse=True)
        return {"runs": runs}

    # ── Single run inspection ──────────────────────────────────────────────────
    run_dir = _RUNS_DIR / run_id

    # Req 5.5: run directory must exist.
    if not run_dir.exists():
        return {
            "error": True,
            "error_type": "unknown_run_id",
            "message": f"Run directory not found: {run_id}",
            "run_id": run_id,
        }

    # ── status_only ────────────────────────────────────────────────────────────
    # Req 5.9: return single-field {"status": ...} from meta.json.
    if arguments.get("status_only"):
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            return {"status": "unknown"}
        try:
            with meta_path.open("r") as f:
                meta = json.load(f)
            return {"status": meta.get("status", "unknown")}
        except Exception:
            return {"status": "unknown"}

    # ── logs ───────────────────────────────────────────────────────────────────
    # Req 5.3, 5.12: return logs.json; error if missing.
    if arguments.get("logs"):
        logs_path = run_dir / "logs.json"
        if not logs_path.exists():
            return {
                "error": True,
                "error_type": "artifact_not_found",
                "message": "logs.json not found for this run.",
                "artifact": "logs.json",
            }
        try:
            with logs_path.open("r") as f:
                logs = json.load(f)
            return {"logs": logs}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
                "artifact": "logs.json",
            }

    # ── graph ──────────────────────────────────────────────────────────────────
    # Req 5.4, 5.6: return graph.json; error if missing.
    if arguments.get("graph"):
        graph_path = run_dir / "graph.json"
        if not graph_path.exists():
            return {
                "error": True,
                "error_type": "artifact_not_found",
                "message": "graph.json not found for this run.",
                "artifact": "graph.json",
            }
        try:
            with graph_path.open("r") as f:
                graph = json.load(f)
            return {"graph": graph}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
                "artifact": "graph.json",
            }

    # ── checkpoints ────────────────────────────────────────────────────────────
    # Req 5.7: list node IDs that have a checkpoint directory.
    if arguments.get("checkpoints"):
        checkpoints_dir = run_dir / "checkpoints"
        if not checkpoints_dir.exists():
            return {"checkpoints": []}
        try:
            node_ids = [
                d.name[len("node_"):]  # strip prefix only, not all occurrences
                for d in checkpoints_dir.iterdir()
                if d.is_dir() and d.name.startswith("node_")
            ]
            return {"checkpoints": sorted(node_ids)}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
                "artifact": "checkpoints/",
            }

    # ── node_id checkpoint manifest ────────────────────────────────────────────
    # Req 5.8: return manifest.json for the given node checkpoint.
    node_id = arguments.get("node_id")
    if node_id:
        checkpoint_dir = run_dir / "checkpoints" / f"node_{node_id}"
        manifest_path = checkpoint_dir / "manifest.json"
        if not manifest_path.exists():
            return {
                "error": True,
                "error_type": "checkpoint_not_found",
                "message": f"Checkpoint not found for node '{node_id}'.",
                "node_id": node_id,
            }
        try:
            with manifest_path.open("r") as f:
                manifest = json.load(f)
            return {"manifest": manifest}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
                "artifact": f"checkpoints/node_{node_id}/manifest.json",
            }

    # ── Default: return full meta.json ─────────────────────────────────────────
    # Req 5.2: return full contents of meta.json when no flags are set.
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return {
            "error": True,
            "error_type": "artifact_not_found",
            "message": "meta.json not found for this run.",
            "artifact": "meta.json",
        }
    try:
        with meta_path.open("r") as f:
            meta = json.load(f)
        return meta
    except Exception as exc:
        return {
            "error": True,
            "error_type": "artifact_read_error",
            "message": str(exc),
            "artifact": "meta.json",
        }
