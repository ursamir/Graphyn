# app/core/runs/verify_log.py
"""
Bounded Context:  BC6 — Observability (Prove pillar / verification history)
Responsibility:   Persist every verification of a sealed run record — who
                  checked, when, and the per-check result — next to the run
                  as ``runs/<id>/verify.json`` (append-only history), emit the
                  ``run.verified`` audit event, and summarize the latest one.
Owns:             record_verification(), load_verify_history(), last_verify(),
                  summarize_checks(), VERIFY_FILE.
Public Surface:   record_verification(run_dir, result, *, actor,
                  actor_verified, claimed_actor=None) -> entry;
                  last_verify(run_dir) -> {checked_at, actor, actor_verified,
                  ok, status, passed, total} | None.
Must NOT:         Touch prove.json / outputs_manifest.json / the chain (a
                  verification never mutates the record); import app.api.
Dependencies:     stdlib; app.core.trust.audit (lazy).
Reason To Change: Verification history schema or retention changes.

verify.json shape: ``{"run_id": str, "history": [entry, ...]}`` oldest first,
capped at ``MAX_HISTORY`` entries. Entry: ``{checked_at, actor,
actor_verified, claimed_actor, ok, status, record_hash, checks: [...],
summary: {passed, total, failed, changed, missing, skipped}}``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

VERIFY_FILE = "verify.json"
MAX_HISTORY = 200
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize_checks(checks: list[dict[str, Any]] | None) -> dict[str, int]:
    """Counts per check status; ``total`` excludes ``skipped`` rows."""
    counts = {"passed": 0, "failed": 0, "changed": 0, "missing": 0, "skipped": 0}
    for c in checks or []:
        st = str((c or {}).get("status") or "")
        if st == "pass":
            counts["passed"] += 1
        elif st == "fail":
            counts["failed"] += 1
        elif st == "changed":
            counts["changed"] += 1
        elif st == "missing":
            counts["missing"] += 1
        elif st == "skipped":
            counts["skipped"] += 1
    counts["total"] = counts["passed"] + counts["failed"] + counts["changed"] + counts["missing"]
    return counts


def _path(run_dir: str | Path) -> Path:
    return Path(run_dir) / VERIFY_FILE


def load_verify_history(run_dir: str | Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    hist = data.get("history") if isinstance(data, dict) else None
    return [h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else []


def record_verification(
    run_dir: str | Path,
    result: dict[str, Any],
    *,
    actor: str,
    actor_verified: bool = False,
    claimed_actor: str | None = None,
) -> dict[str, Any]:
    """Append one verification to verify.json and audit ``run.verified``.

    Best-effort: storage failures are logged; the entry is still returned.
    """
    run_dir = Path(run_dir)
    checks = list(result.get("checks") or [])
    entry: dict[str, Any] = {
        "checked_at": str(result.get("verified_at") or _now()),
        "actor": str(actor or "unidentified"),
        "actor_verified": bool(actor_verified),
        "claimed_actor": claimed_actor or None,
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "record_hash": result.get("record_hash"),
        "checks": checks,
        "summary": summarize_checks(checks),
    }
    path = _path(run_dir)
    with _lock:
        try:
            history = load_verify_history(run_dir)
            history.append(entry)
            history = history[-MAX_HISTORY:]
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"run_id": run_dir.name, "history": history}, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, path)
            entry["history_count"] = len(history)
        except OSError as exc:
            log.warning("verify history write failed for %s: %s", run_dir.name, exc)
    try:
        from app.core.trust.audit import record_audit

        summ = entry["summary"]
        record_audit(
            actor=entry["actor"],
            actor_verified=entry["actor_verified"],
            claimed_actor=entry["claimed_actor"],
            action="run.verified",
            resource_type="run",
            resource_id=run_dir.name,
            result="success" if entry["ok"] else "failure",
            meta={
                "ok": entry["ok"],
                "status": entry["status"],
                "passed": summ["passed"],
                "total": summ["total"],
                "record_hash": entry["record_hash"],
            },
        )
    except Exception:
        log.debug("run.verified audit failed", exc_info=True)
    return entry


def _brief(entry: dict[str, Any]) -> dict[str, Any]:
    summ = entry.get("summary") if isinstance(entry.get("summary"), dict) else summarize_checks(entry.get("checks"))
    return {
        "checked_at": entry.get("checked_at"),
        "actor": entry.get("actor"),
        "actor_verified": bool(entry.get("actor_verified")),
        "ok": bool(entry.get("ok")),
        "status": entry.get("status"),
        "passed": int(summ.get("passed") or 0),
        "total": int(summ.get("total") or 0),
    }


def last_verify(run_dir: str | Path) -> dict[str, Any] | None:
    """Latest verification brief ``{checked_at, actor, actor_verified, ok,
    status, passed, total}`` or None when the run was never verified."""
    hist = load_verify_history(run_dir)
    return _brief(hist[-1]) if hist else None


__all__ = [
    "MAX_HISTORY",
    "VERIFY_FILE",
    "last_verify",
    "load_verify_history",
    "record_verification",
    "summarize_checks",
]
