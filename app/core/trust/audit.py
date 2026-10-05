# app/core/trust/audit.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Thin append-only audit event log for accountability mutations.
Owns:             record_audit(), list_audit(), audit_path helpers, the
                  action → label / category table (audit_label, audit_category).
Public Surface:   record_audit(..., actor_verified, claimed_actor),
                  list_audit(limit, offset, resource_id, run_id, action, q,
                  with_total, category, exclude_category),
                  normalize_audit_event, audit_label, audit_category,
                  AUDIT_CATEGORIES.
Must NOT:         Import from app.api or execution orchestrators.
Dependencies:     stdlib, app.core.config.project_dir,
                  app.core.trust.identity (request identity ContextVar, lazy).
Reason To Change: Audit schema evolves or storage backend changes.

SRS §22.1 fields: event_id, timestamp, actor, actor_kind?, request_id, action,
resource_type, resource_id, result, metadata?; ``ts`` kept as alias of timestamp.
Identity fields: actor_verified (bearer token mapped to the actor),
claimed_actor (X-Actor / body actor when it differs), origin (http | internal).
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


# ── readable labels / categories (computed at read time) ─────────────────────

AUDIT_CATEGORIES = ("run", "model", "data", "admin", "system", "ui")

_ACTION_LABELS: dict[str, str] = {
    "run.start": "Run started",
    "run.finish": "Run finished",
    "run.fail": "Run failed",
    "run.cancel": "Run cancelled",
    "run.pause": "Run paused",
    "run.resume": "Run resumed",
    "run.archive": "Run archived",
    "run.restore": "Run restored",
    "run.purge": "Run permanently deleted",
    "run.replay": "Run replayed",
    "run.verified": "Run verified",
    "run.promote": "Run promoted",
    "run.output_download": "Output file downloaded",
    "run.outputs_zip": "Run outputs downloaded (zip)",
    "model.download": "Model / package file downloaded",
    "model.register": "Model registered",
    "model.promote_request": "Model prod requested",
    "model.approve_prod": "Model approved for prod",
    "ship.create": "Ship package created",
    "ship.promote": "Ship package promoted",
    "ship.download": "Ship package downloaded",
    "notifications.mark_read": "Notifications marked read",
    "system.cleanup": "Workspace cleaned up",
    "ops.shutdown_drain": "Server shutdown",
    "worker.register": "Worker registered",
    "webhook.set": "Webhook settings changed",
    "webhook.test": "Webhook test sent",
    "webhook.received": "Webhook delivery accepted",
    "webhook.rejected": "Webhook delivery rejected",
    "hook.create": "Inbound webhook created",
    "hook.update": "Inbound webhook updated",
    "hook.delete": "Inbound webhook removed",
    "hook.rotate": "Inbound webhook secret rotated",
    "gate.decision": "Approval decision",
    "schedule.create": "Schedule created",
    "schedule.delete": "Schedule deleted",
    "schedule.enable": "Schedule enabled",
    "schedule.disable": "Schedule disabled",
    "schedule.env": "Schedule environment changed",
    "schedule.run": "Schedule run now",
    "schedule.tick": "Schedules checked",
    "credential.create": "Credential created",
    "credential.update": "Credential updated",
    "credential.bind_default": "Credential set as default",
    "credential.delete": "Credential deleted",
    "credential.revoke": "Credential revoked",
    "plugin.install": "Plugin installed",
    "plugin.uninstall": "Plugin uninstalled",
    "plugin.enable": "Plugin enabled",
    "plugin.disable": "Plugin disabled",
    "plugin.install_deps": "Plugin dependencies installed",
    "pipeline.publish": "Pipeline version published",
    "pipeline.promote": "Pipeline promoted",
    "pipeline.promote_request": "Pipeline promotion requested",
    "pipeline.rollback": "Pipeline rolled back",
    "template.save": "Template saved",
    "proposal.create": "Proposal created",
    "proposal.accept": "Proposal accepted",
    "proposal.reject": "Proposal rejected",
    "dataset.version_delete": "Dataset version deleted",
    "dataset.version_create": "Dataset version written",
    "dataset.upload": "Dataset files uploaded",
    "dataset.label_delete": "Input dataset deleted",
    "dataset.snapshot": "Input dataset frozen as version",
    "dataset.merge": "Datasets merged",
    "dataset.download": "Dataset downloaded",
    "dataset.ingest_start": "Dataset import started",
    "dataset.ingest_finish": "Dataset import finished",
    "dataset.link": "Dataset linked to workspace",
    "dataset.unlink": "Dataset unlinked from workspace",
    "workspace.created": "Workspace created",
    "workspace.deleted": "Workspace deleted",
    "workspace.renamed": "Workspace id renamed (legacy)",
    "workspace.updated": "Workspace details updated",
    "workspace.status_changed": "Workspace status changed",
    "workspace.archived": "Workspace archived",
    "workspace.unarchived": "Workspace unarchived",
    "workspace.cloned": "Workspace cloned",
    "workspace.spec_updated": "Workspace spec updated",
    "workspace.taxonomy_updated": "Workspace taxonomy updated",
    "workspace.contract_updated": "Workspace contract updated",
    "workspace.snapshot_created": "Workspace snapshot created",
    "workspace.snapshot_restored": "Workspace snapshot restored",
    "workspace.version_restored": "Dataset version restored into workspace",
}
_CATEGORY_BY_PREFIX: dict[str, str] = {
    "run": "run",
    "model": "model",
    "ship": "model",
    "notifications": "ui",
    "notification": "ui",
    "ui": "ui",
    "system": "admin",
    "ops": "system",
    "worker": "system",
    "webhook": "admin",
    "schedule": "admin",
    "credential": "admin",
    "plugin": "admin",
    "pipeline": "admin",
    "template": "admin",
    "proposal": "admin",
    "dataset": "data",
    "workspace": "admin",
    "hook": "admin",
    "gate": "run",
}
# Exact overrides (automatic / machine events).
_CATEGORY_EXACT: dict[str, str] = {"schedule.tick": "system"}


def audit_action_name(ev: dict[str, Any]) -> str:
    return str(ev.get("action") or ev.get("type") or "").strip()


def audit_category(action: str) -> str:
    """Category of an audit action: run | model | data | admin | system | ui."""
    a = (action or "").strip().lower()
    if a in _CATEGORY_EXACT:
        return _CATEGORY_EXACT[a]
    return _CATEGORY_BY_PREFIX.get(a.split(".", 1)[0], "system")


def audit_label(action: str) -> str:
    """Plain-words label for an audit action (falls back to a humanized name)."""
    a = (action or "").strip()
    if a in _ACTION_LABELS:
        return _ACTION_LABELS[a]
    if not a:
        return "Event"
    head, _, tail = a.partition(".")
    if head == "ship" and tail:
        return f"Ship package {tail.replace('_', ' ')}"
    words = " ".join(x for x in (head, tail) if x).replace("_", " ").replace(".", " ")
    return words[:1].upper() + words[1:]


def _csv_set(raw: str | None) -> set[str]:
    return {x.strip().lower() for x in str(raw or "").split(",") if x.strip()}


def normalize_audit_event(obj: dict[str, Any]) -> dict[str, Any]:
    """Ensure readers see §22.1 field names (timestamp/result/request_id/…).

    Adds read-time ``label`` (plain words) and ``category``
    (run | model | data | admin | system | ui) computed from ``action`` / ``type``;
    legacy events without identity fields get ``actor_verified: false``.
    """
    out = dict(obj)
    name = audit_action_name(out)
    out["label"] = audit_label(name)
    out["category"] = audit_category(name)
    out.setdefault("actor_verified", False)
    out.setdefault("claimed_actor", None)
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


def _bind_identity(
    actor: str | None, verified: bool | None, claimed: str | None
) -> tuple[str, bool, str | None, str]:
    """Merge an explicit actor with the current request identity (if any)."""
    try:
        from app.core.trust.identity import bind_actor

        return bind_actor(actor, verified, claimed)
    except Exception:
        return str(actor or "").strip()[:128] or "system", bool(verified), claimed, "internal"


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
    actor_verified: bool | None = None,
    claimed_actor: str | None = None,
) -> dict[str, Any]:
    """Append one audit event to ``audit/events.jsonl``. Never raises to callers.

    Events are JSONL (one JSON object per line). Failures are logged and
    swallowed so mutation endpoints stay available if the audit disk is full.

    Identity: inside an HTTP request (app.core.trust.identity ContextVar set by
    the API middleware) a generic ``actor`` ("api" / "system" / "human" / "")
    is replaced by the request identity, and ``actor_verified`` /
    ``claimed_actor`` default from it. Outside a request (background jobs)
    an empty actor becomes ``"system"`` and ``actor_verified`` is False.
    """
    actor, actor_verified, claimed_actor, origin = _bind_identity(actor, actor_verified, claimed_actor)
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
        "actor_verified": bool(actor_verified),
        "claimed_actor": claimed_actor,
        "origin": origin,
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
    category: str | None = None,
    exclude_category: str | None = None,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], int]:
    """Return audit events (newest first) after filters, paged by offset/limit.

    Filters: ``resource_id`` (exact, or unique-prefix match ≥ 8 chars),
    ``run_id`` (resource_type ``run`` + resource_id, or metadata
    ``replay_of``), ``action`` (exact or ``prefix.*``), ``q`` (case-insensitive
    substring over the serialized event). The whole log is scanned, so paging
    reaches beyond the newest 1000 events. ``with_total`` returns
    ``(events, total_matched)``. ``category`` / ``exclude_category`` are
    comma lists over :func:`audit_category` (e.g. ``exclude_category="ui,system"``).
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
    cats = _csv_set(category)
    no_cats = _csv_set(exclude_category)

    def _match(ev: dict[str, Any], raw: str) -> bool:
        if cats or no_cats:
            cat = audit_category(audit_action_name(ev))
            if cats and cat not in cats:
                return False
            if cat in no_cats:
                return False
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
        if needle and needle not in raw.lower() and needle not in audit_label(audit_action_name(ev)).lower():
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
