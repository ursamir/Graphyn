# app/mcp/handlers/workers_ops.py
"""MCP observe tools for Mode B workers/jobs (Wave B leftover)."""
from __future__ import annotations

from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


def _meta_props() -> dict[str, Any]:
    return {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        }
    }


LIST_WORKERS_DESCRIPTION = "List registered distributed workers (Mode B observe)."
LIST_WORKERS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "include_stale": {"type": "boolean", "default": False},
        **_meta_props(),
    },
    "additionalProperties": False,
}


def list_workers_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    include_stale = bool(args.get("include_stale") or False)
    try:
        from app.core.distributed.registry import get_worker_registry

        workers = get_worker_registry().list(include_stale=include_stale)
    except Exception as exc:
        return _err("internal_error", f"Failed to list workers: {exc}")
    items = []
    for w in workers:
        if hasattr(w, "model_dump"):
            items.append(w.model_dump(mode="json"))
        elif isinstance(w, dict):
            items.append(w)
        else:
            items.append({"worker": str(w)})
    return {"workers": items, "total": len(items)}


LIST_JOBS_DESCRIPTION = "List distributed jobs (Mode B observe)."
LIST_JOBS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "Optional status filter."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
        **_meta_props(),
    },
    "additionalProperties": False,
}


def list_jobs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Observe jobs from the durable queue snapshot when available."""
    args = arguments or {}
    limit = max(1, min(int(args.get("limit") or 50), 500))
    status = args.get("status")
    try:
        from app.core.distributed.queue import get_job_queue

        queue = get_job_queue()
        items: list[dict[str, Any]] = []
        # Prefer any public list; else read durable snapshot fields carefully.
        if hasattr(queue, "list_jobs"):
            raw = queue.list_jobs(status=status, limit=limit)  # type: ignore[attr-defined]
            for j in raw or []:
                items.append(j.model_dump(mode="json") if hasattr(j, "model_dump") else dict(j))
        else:
            snap = None
            try:
                # Best-effort: JobQueue keeps durable state via _queue_snapshot_unlocked
                lock = getattr(queue, "_lock", None)
                if lock is not None:
                    with lock:
                        snap = queue._queue_snapshot_unlocked()  # noqa: SLF001
                else:
                    snap = queue._queue_snapshot_unlocked()  # noqa: SLF001
            except Exception:
                snap = None
            jobs_map = {}
            if isinstance(snap, dict):
                jobs_map = snap.get("jobs") or snap.get("by_id") or {}
            if isinstance(jobs_map, dict):
                for jid, j in jobs_map.items():
                    row = dict(j) if isinstance(j, dict) else {"job_id": jid, "raw": str(j)}
                    row.setdefault("job_id", jid)
                    if status and str(row.get("status") or "") != str(status):
                        continue
                    items.append(row)
            pending = 0
            try:
                pending = int(queue.pending_count())
            except Exception:
                pending = len(items)
            return {
                "jobs": items[:limit],
                "total": len(items),
                "pending_count": pending,
            }
        return {"jobs": items[:limit], "total": len(items)}
    except Exception as exc:
        return _err("internal_error", f"Failed to list jobs: {exc}")
