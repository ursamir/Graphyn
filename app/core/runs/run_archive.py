# app/core/runs/run_archive.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Archive (soft-delete) and restore runs so the audit trail
                  is never lost by a default DELETE; hard purge stays in
                  run_cleanup.delete_run behind an explicit confirmation.
Owns:             archive_run(), restore_run(), the ``runs/<id>/.archived``
                  marker contents and meta.json ``archived*`` fields.
Public Surface:   archive_run(run_dir, actor) -> dict, restore_run(run_dir, actor) -> dict
Must NOT:         Delete files; import app.api / app.domain.
Dependencies:     stdlib; app.core.runs.run_listing (ARCHIVE_MARKER),
                  app.core.runs.run_status, app.core.trust.audit (lazy).
Reason To Change: Archive semantics / retention policy changes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.runs.run_listing import ARCHIVE_MARKER


class RunActiveError(RuntimeError):
    """The run is still pending/running/paused."""


def _read_meta(run_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_meta_fields(run_dir: Path, fields: dict[str, Any], drop: tuple[str, ...] = ()) -> None:
    meta = _read_meta(run_dir)
    meta.update(fields)
    for key in drop:
        meta.pop(key, None)
    path = run_dir / "meta.json"
    tmp = path.with_name(f"meta.json.archive.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _record_hash(run_dir: Path) -> str | None:
    try:
        data = json.loads((run_dir / "prove.json").read_text(encoding="utf-8"))
        return data.get("record_hash") if isinstance(data, dict) else None
    except Exception:
        return None


def archive_run(run_dir: str | Path, *, actor: str = "api") -> dict[str, Any]:
    """Hide a terminal run from default lists (idempotent, audited)."""
    from app.core.runs.run_status import TERMINAL_STATUSES, normalize_status

    run_dir = Path(run_dir)
    meta = _read_meta(run_dir)
    status = normalize_status(meta.get("status")) if meta.get("status") else "unknown"
    if status not in TERMINAL_STATUSES and status != "unknown":
        raise RunActiveError(f"Run {run_dir.name} is {status}; cancel it before archiving")
    marker = run_dir / ARCHIVE_MARKER
    if marker.exists() and meta.get("archived"):
        return {"run_id": run_dir.name, "archived": True, "archived_at": meta.get("archived_at"),
                "archived_by": meta.get("archived_by"), "already_archived": True}
    now = datetime.now(timezone.utc).isoformat()
    marker.write_text(json.dumps({"archived_at": now, "archived_by": actor}), encoding="utf-8")
    _write_meta_fields(run_dir, {"archived": True, "archived_at": now, "archived_by": actor})
    try:
        from app.core.trust.audit import record_audit

        record_audit(actor=actor, action="run.archive", resource_type="run", resource_id=run_dir.name,
                     meta={"status": status, "record_hash": _record_hash(run_dir),
                           "graph_name": meta.get("graph_name"), "project": meta.get("project")})
    except Exception:
        pass
    return {"run_id": run_dir.name, "archived": True, "archived_at": now, "archived_by": actor}


def restore_run(run_dir: str | Path, *, actor: str = "api") -> dict[str, Any]:
    """Un-archive a run (idempotent, audited)."""
    run_dir = Path(run_dir)
    marker = run_dir / ARCHIVE_MARKER
    was = marker.exists()
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    _write_meta_fields(run_dir, {}, drop=("archived", "archived_at", "archived_by"))
    if was:
        try:
            from app.core.trust.audit import record_audit

            record_audit(actor=actor, action="run.restore", resource_type="run", resource_id=run_dir.name,
                         meta={"record_hash": _record_hash(run_dir),
                               "project": _read_meta(run_dir).get("project")})
        except Exception:
            pass
    return {"run_id": run_dir.name, "archived": False}
