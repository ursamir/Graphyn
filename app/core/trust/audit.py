# app/core/trust/audit.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Thin append-only audit event log for accountability mutations.
Owns:             record_audit() (hash-chained: prev_hash / event_hash),
                  verify_audit_chain(), list_audit(), audit_path helpers, the
                  action → label / category table (audit_label, audit_category).
Public Surface:   record_audit(..., actor_verified, claimed_actor),
                  list_audit(limit, offset, resource_id, run_id, action, q,
                  with_total, category, exclude_category, actor, user_id,
                  credential_id, worker_id, since, until),
                  verify_audit_chain(),
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

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()

_VALID_RESULTS = frozenset({"success", "failure", "denied"})
_VALID_ACTOR_KINDS = frozenset({"human", "agent", "system", "billing_webhook"})


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
    if a == "billing_webhook":
        return "billing_webhook"
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
    "auth.login": "Signed in",
    "auth.logout": "Signed out",
    "user.create": "User created",
    "user.update": "User updated",
    "user.password_change": "Password changed",
    "token.create": "API token created",
    "token.revoke": "Token revoked",
    "project.member_set": "Project member set",
    "project.member_remove": "Project member removed",
    "worker.join_token_create": "Worker join token created",
    "worker.join_token_revoke": "Worker join token revoked",
    "worker.join": "Worker joined",
    "worker.join_denied": "Worker join refused",
    "audit.export": "Audit log exported",
    "worker.credential_rotate": "Worker credential rotated",
    "worker.credential_revoke": "Worker credential revoked",
    "worker.register": "Worker registered",
    "worker.deregister": "Worker deregistered",
    "worker.trust": "Worker trust changed",
    "worker.patch": "Worker ACL updated",
    "job.claim": "Job claimed",
    "job.complete": "Job completed",
    "job.cancel": "Job cancelled",
    "blob.put": "Artifact blob uploaded",
    "blob.get": "Artifact blob downloaded",
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
    "pipeline.deleted": "Pipeline deleted",
    "agent.create": "Agent created",
    "agent.update": "Agent updated",
    "agent.token_mint": "Agent token minted",
    "agent.token_revoke": "Agent token revoked",
    "compliance.export": "Compliance pack exported",
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
    "job": "system",
    "blob": "system",
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
    "auth": "admin",
    "user": "admin",
    "token": "admin",
    "project": "admin",
    "join_token": "admin",
    "audit": "admin",
}
# Security-relevant worker events stay visible under Admin.
_WORKER_ADMIN_ACTIONS = (
    "worker.join_token_create",
    "worker.join_token_revoke",
    "worker.join",
    "worker.join_denied",
    "worker.credential_rotate",
    "worker.credential_revoke",
)
# Exact overrides (automatic / machine events).
_CATEGORY_EXACT: dict[str, str] = {"schedule.tick": "system", **{a: "admin" for a in _WORKER_ADMIN_ACTIONS}}


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


def _principal() -> dict[str, Any] | None:
    """Who authenticated the current request: user / credential / role / worker / join token."""
    try:
        from app.core.trust.identity import principal_snapshot

        return principal_snapshot()
    except Exception:
        return None


def _flock(fh: Any) -> None:
    """Cross-process append lock (released when ``fh`` closes)."""
    try:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception:
        pass


def _event_hash(event: dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "event_hash"}
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _last_event_hash(path: Path) -> str | None:
    """``event_hash`` of the last line (None for an empty / legacy tail)."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size == 0:
                return None
            back = min(size, 256 * 1024)
            fh.seek(size - back)
            tail = fh.read().splitlines()
    except OSError:
        return None
    for raw in reversed(tail):
        raw = raw.strip()
        if not raw:
            continue
        try:
            return json.loads(raw.decode("utf-8")).get("event_hash")
        except Exception:
            return None
    return None


def verify_audit_chain(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Re-hash every chained event; report the first break (edit / delete / insert)."""
    path = audit_events_path(base_dir)
    checked = legacy = 0
    prev: str | None = None
    started = False
    if not path.exists():
        return {"ok": True, "checked": 0, "legacy_unchained": 0, "first_break": None}
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                return {"ok": False, "checked": checked, "legacy_unchained": legacy,
                        "first_break": {"line": lineno, "reason": "unparseable line"}}
            if "event_hash" not in ev:
                if started:
                    return {"ok": False, "checked": checked, "legacy_unchained": legacy,
                            "first_break": {"line": lineno, "reason": "unchained event after chain start"}}
                legacy += 1
                continue
            if started and ev.get("prev_hash") != prev:
                return {"ok": False, "checked": checked, "legacy_unchained": legacy,
                        "first_break": {"line": lineno, "event_id": ev.get("event_id"), "reason": "prev_hash mismatch"}}
            if _event_hash(ev) != ev.get("event_hash"):
                return {"ok": False, "checked": checked, "legacy_unchained": legacy,
                        "first_break": {"line": lineno, "event_id": ev.get("event_id"), "reason": "event_hash mismatch"}}
            started = True
            prev = ev["event_hash"]
            checked += 1
    return {"ok": True, "checked": checked, "legacy_unchained": legacy, "first_break": None, "head": prev}


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
    principal = _principal()
    if principal:
        event["principal"] = principal
        if principal.get("kind") == "worker" and not actor_kind:
            event["actor_kind"] = "worker"
        elif principal.get("kind") == "user" and not actor_kind:
            event["actor_kind"] = "user"
    try:
        path = audit_events_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a+", encoding="utf-8") as fh:
                _flock(fh)
                event["prev_hash"] = _last_event_hash(path)
                event["event_hash"] = _event_hash(event)
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                fh.flush()
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
    actor: str | None = None,
    user_id: str | None = None,
    credential_id: str | None = None,
    worker_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    max_limit: int = 1000,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], int]:
    """Return audit events (newest first) after filters, paged by offset/limit.

    Filters: ``resource_id`` (exact, or unique-prefix match ≥ 8 chars),
    ``run_id`` (resource_type ``run`` + resource_id, or metadata
    ``replay_of``), ``action`` (exact or ``prefix.*``), ``q`` (case-insensitive
    substring over the serialized event). The whole log is scanned, so paging
    reaches beyond the newest 1000 events. ``with_total`` returns
    ``(events, total_matched)``. ``category`` / ``exclude_category`` are
    comma lists over :func:`audit_category` (e.g. ``exclude_category="ui,system"``).
    ``actor`` (case-insensitive exact), ``user_id`` / ``credential_id`` /
    ``worker_id`` (principal block), ``since`` / ``until`` (ISO timestamps,
    inclusive) narrow to one person / credential / machine / window.
    """
    limit = max(1, min(int(limit or 100), max(1, int(max_limit))))
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
    who = (actor or "").strip().lower()
    t_from = (since or "").strip()
    t_to = (until or "").strip()

    def _principal_match(ev: dict[str, Any]) -> bool:
        pr = ev.get("principal") if isinstance(ev.get("principal"), dict) else {}
        if user_id and pr.get("user_id") != user_id:
            return False
        if credential_id and pr.get("credential_id") != credential_id:
            return False
        if worker_id:
            meta = ev.get("metadata") or ev.get("meta") or {}
            ids = {pr.get("worker_id"), pr.get("mtls_worker_id"), (meta or {}).get("worker_id")}
            if ev.get("resource_type") == "worker":
                ids.add(ev.get("resource_id"))
            if worker_id not in ids:
                return False
        return True

    def _match(ev: dict[str, Any], raw: str) -> bool:
        if who and str(ev.get("actor") or "").lower() != who:
            return False
        if (user_id or credential_id or worker_id) and not _principal_match(ev):
            return False
        if t_from or t_to:
            ts = str(ev.get("timestamp") or ev.get("ts") or "")
            if t_from and ts < t_from:
                return False
            if t_to and ts > t_to:
                return False
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
