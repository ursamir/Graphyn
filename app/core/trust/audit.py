# app/core/trust/audit.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Thin append-only audit event log for accountability mutations.
Owns:             record_audit(), list_audit(), audit_path helpers.
Public Surface:   record_audit(...), list_audit(limit, offset, resource_id, run_id,
                  action, q, with_total), normalize_audit_event.
Must NOT:         Import from app.api or execution orchestrators.
Dependencies:     stdlib, app.core.config.project_dir.
Reason To Change: Audit schema evolves or storage backend changes.

SRS §22.1 fields: event_id, timestamp, actor, actor_kind?, request_id, action,
resource_type, resource_id, result, metadata?; ``ts`` kept as alias of timestamp.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()

_VALID_RESULTS = frozenset({"success", "failure", "denied"})
_VALID_ACTOR_KINDS = frozenset({"human", "agent", "system"})


def audit_dir(base_dir: str | Path | None = None) -> Path:
    """Return ``{project}/audit`` (or ``{base_dir}/audit``)."""
    if base_dir is not None:
        return Path(base_dir) / "audit"
    from app.core.config import project_dir

    return project_dir() / "audit"


def audit_events_path(base_dir: str | Path | None = None) -> Path:
    return audit_dir(base_dir) / "events.jsonl"


def _infer_actor_kind(actor: str, actor_kind: str | None) -> str | None:
    if actor_kind and actor_kind in _VALID_ACTOR_KINDS:
        return actor_kind
    a = (actor or "").strip().lower()
    if a in ("system", "api", "scheduler", "cleanup", "worker"):
        return "system"
    if a.startswith("agent:") or a.startswith("mcp") or a == "agent":
        return "agent"
    if a and a not in ("unknown", "anonymous"):
        return "human"
    return None


def normalize_audit_event(obj: dict[str, Any]) -> dict[str, Any]:
    """Ensure readers see §22.1 field names (timestamp/result/request_id/…)."""
    out = dict(obj)
    ts = out.get("timestamp") or out.get("ts")
    if ts:
        out["timestamp"] = ts
        out.setdefault("ts", ts)  # alias retained for legacy readers
    if "result" not in out or out.get("result") not in _VALID_RESULTS:
        out["result"] = out.get("result") or "success"
    if "request_id" not in out or not out.get("request_id"):
        out["request_id"] = out.get("request_id") or out.get("event_id") or ""
    if "metadata" not in out and "meta" in out:
        out["metadata"] = out.get("meta") or {}
    if "meta" not in out and "metadata" in out:
        out["meta"] = out.get("metadata") or {}
    # SEC-P0: never surface raw webhook URLs (the secret) via audit/trace.
    if str(out.get("resource_type") or "") == "webhook":
        rid = str(out.get("resource_id") or "")
        if rid and "://" in rid:
            try:
                from app.core.trust.egress import redact_webhook_url_for_api

                out["resource_id"] = redact_webhook_url_for_api(rid) or "***"
            except Exception:
                out["resource_id"] = "***"
    return out


def record_audit(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    meta: dict[str, Any] | None = None,
    *,
    base_dir: str | Path | None = None,
    result: str = "success",
    request_id: str | None = None,
    actor_kind: str | None = None,
    resource_version: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one audit event to ``audit/events.jsonl``. Never raises to callers.

    Events are JSONL (one JSON object per line). Failures are logged and
    swallowed so mutation endpoints stay available if the audit disk is full.
    """
    now = datetime.now(timezone.utc).isoformat()
    res = result if result in _VALID_RESULTS else "success"
    rid = (request_id or "").strip() or uuid.uuid4().hex
    meta_obj = dict(metadata) if isinstance(metadata, dict) else {}
    if isinstance(meta, dict) and meta:
        meta_obj.update(meta)
    event: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "timestamp": now,
        "ts": now,  # legacy alias
        "actor": actor or "unknown",
        "actor_kind": _infer_actor_kind(actor or "", actor_kind),
        "request_id": rid,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_version": resource_version,
        "before": before,
        "after": after,
        "result": res,
        "error_code": error_code,
        "metadata": meta_obj,
        "meta": meta_obj,  # legacy alias
    }
    try:
        path = audit_events_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:
        logger.warning("record_audit failed (%s): %s", action, exc)
    return event


def list_audit(
    limit: int = 100,
    *,
    base_dir: str | Path | None = None,
    offset: int = 0,
    resource_id: str | None = None,
    run_id: str | None = None,
    action: str | None = None,
    q: str | None = None,
    with_total: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], int]:
    """Return audit events (newest first) after filters, paged by offset/limit.

    Filters: ``resource_id`` (exact, or unique-prefix match ≥ 8 chars),
    ``run_id`` (resource_type ``run`` + resource_id, or metadata
    ``replay_of``), ``action`` (exact or ``prefix.*``), ``q`` (case-insensitive
    substring over the serialized event). The whole log is scanned, so paging
    reaches beyond the newest 1000 events. ``with_total`` returns
    ``(events, total_matched)``.
    """
    limit = max(1, min(int(limit or 100), 1000))
    offset = max(0, int(offset or 0))
    path = audit_events_path(base_dir)
    if not path.exists():
        return ([], 0) if with_total else []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("list_audit read failed: %s", exc)
        return ([], 0) if with_total else []

    needle = (q or "").strip().lower()
    rid = (resource_id or "").strip()
    run = (run_id or "").strip()
    act = (action or "").strip()

    def _match(ev: dict[str, Any], raw: str) -> bool:
        res = str(ev.get("resource_id") or "")
        if rid and not (res == rid or (len(rid) >= 8 and res.startswith(rid))):
            return False
        if run:
            meta = ev.get("metadata") or ev.get("meta") or {}
            linked = isinstance(meta, dict) and str(meta.get("replay_of") or "").startswith(run)
            is_run = str(ev.get("resource_type") or "") == "run" and (
                res == run or (len(run) >= 8 and res.startswith(run))
            )
            if not (is_run or linked):
                return False
        if act:
            name = str(ev.get("action") or "")
            if act.endswith(".*"):
                if not name.startswith(act[:-1]):
                    return False
            elif name != act:
                return False
        if needle and needle not in raw.lower():
            return False
        return True

    matched: list[dict[str, Any]] = []
    total = 0
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict) or not _match(obj, line):
            continue
        total += 1
        if total > offset and len(matched) < limit:
            matched.append(normalize_audit_event(obj))
    return (matched, total) if with_total else matched
