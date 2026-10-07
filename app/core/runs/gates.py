# app/core/runs/gates.py
"""
Bounded Context:  BC6 — Observability & Storage (run control: approval gates)
Responsibility:   Discover human-approval gates (``hitl_approve`` nodes) of a
                  run and record a human decision where the node reads it —
                  the out-of-band decision file
                  ``{decision_dir}/{run_id}__{gate_id}.decision.json``.
Owns:             GateError, list_gates(), pending_gates(), decide_gate(),
                  gate_approver_roles(),
                  awaiting_approval_overlay(), HITL_NODE_TYPE.
Public Surface:   The functions above.
Must NOT:         Import app.api / app.domain or plugin modules (the file
                  contract is mirrored here, not imported). Must not write
                  decision files outside the project workspace jail.
Dependencies:     stdlib (hashlib, json, os, re, time, datetime, pathlib),
                  app.core.paths.write_paths (_resolve_under_project jail),
                  app.core.trust.audit (gate.decision event).
Reason To Change: hitl_approve request/decision file contract changes.

File contract (PluginPackage/Agents/hitl_approve):
  request  ``{run_id}__{gate_id}.request.json``  — written by the node:
           {request_id, run_id, gate_id, approver_roles, reason_required,
            timeout_s, requested_at, decision_path, status: pending|approved|rejected}
  decision ``{run_id}__{gate_id}.decision.json`` — written here (create-only):
           {request_id, approved, approver, role, reason, decided_at, ...}
Names are sanitised with ``[^A-Za-z0-9_.-] → _`` (max 128 chars).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

HITL_NODE_TYPE = "hitl_approve"
DEFAULT_GATE_ID = "hitl_approve"
DEFAULT_DECISION_DIR = "workspace/artifacts/agents/hitl_approve/decisions"


class GateError(Exception):
    """Gate lookup / decision refused; ``status_code`` maps to HTTP."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value or "")[:128] or "adhoc"


def _resolve_decision_dir(decision_dir: str, *, strict: bool = False) -> Path | None:
    """Resolve ``decision_dir`` inside the project workspace (path jail).

    Absolute paths and ``workspace/…`` relatives are allowed only when they
    resolve under ``project_dir()``. ``..`` segments and escapes return None
    (or raise GateError when ``strict``).
    """
    from app.core.paths.write_paths import _resolve_under_project

    raw = (decision_dir or DEFAULT_DECISION_DIR).strip() or DEFAULT_DECISION_DIR
    if any(part == ".." for part in Path(raw).parts):
        if strict:
            raise GateError(400, "invalid_decision_dir", "decision_dir must not contain '..'")
        return None
    resolved = _resolve_under_project(raw)
    if resolved is None:
        if strict:
            raise GateError(
                400,
                "invalid_decision_dir",
                "decision_dir must resolve inside the project workspace",
            )
        return None
    return resolved


def _paths(decision_dir: str, run_id: str, gate_id: str, *, strict: bool = False) -> tuple[Path, Path]:
    base = _resolve_decision_dir(decision_dir, strict=strict)
    if base is None:
        # Unreadable outside jail — point at a non-existent default so status is not_reached.
        base = _resolve_decision_dir(DEFAULT_DECISION_DIR) or Path(DEFAULT_DECISION_DIR)
    stem = f"{_safe_key(run_id)}__{_safe_key(gate_id)}"
    return base / f"{stem}.request.json", base / f"{stem}.decision.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_graph(run_dir: Path) -> dict[str, Any]:
    data = _read_json(Path(run_dir) / "graph.json")
    return data or {}


def _parse_iso(text: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _gate_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("node_type") == HITL_NODE_TYPE:
            out.append(node)
    return out


def _gate_view(node: dict[str, Any], run_id: str, now: datetime) -> dict[str, Any]:
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    gate_id = str(cfg.get("gate_id") or DEFAULT_GATE_ID)
    decision_dir = str(cfg.get("decision_dir") or DEFAULT_DECISION_DIR)
    request_path, decision_path = _paths(decision_dir, run_id, gate_id)
    request = _read_json(request_path)
    decision = _read_json(decision_path)
    timeout_s = float((request or {}).get("timeout_s", cfg.get("timeout_s", 3600.0)) or 0.0)
    requested_at = (request or {}).get("requested_at")
    started = _parse_iso(requested_at)
    expires_at = (started + timedelta(seconds=timeout_s)) if started else None

    if cfg.get("unattended_approve"):
        status = "unattended"
    elif request is None:
        status = "not_reached"
    else:
        req_status = str(request.get("status") or "pending")
        if req_status in ("approved", "rejected"):
            status = req_status
        elif decision is not None and decision.get("request_id") == request.get("request_id"):
            status = "decided"  # decision written; node has not polled yet
        elif expires_at is not None and now > expires_at:
            status = "expired"
        else:
            status = "pending"
    outcome = (request or {}).get("outcome") if isinstance((request or {}).get("outcome"), dict) else None
    label = node.get("label") or None
    prompt = cfg.get("prompt") or cfg.get("message") or label or f"Approve gate '{gate_id}'"
    return {
        "node_id": node.get("id"),
        "gate_id": gate_id,
        "label": label,
        "prompt": str(prompt),
        "status": status,
        "pending": status == "pending",
        "request_id": (request or {}).get("request_id"),
        "requested_at": requested_at,
        "waiting_since": requested_at if status == "pending" else None,
        "timeout_s": timeout_s,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "approver_roles": list((request or {}).get("approver_roles", cfg.get("approver_roles") or []) or []),
        "reason_required": bool((request or {}).get("reason_required", cfg.get("reason_required", True))),
        "decision": _public_decision(decision) if decision else None,
        "outcome": outcome,
    }


def _public_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {k: decision.get(k) for k in (
        "approved", "approver", "role", "decided_at", "actor_verified", "role_verified", "user_id",
        "source", "comment_sha256",
    )}


def list_gates(run_dir: Path | str, run_id: str | None = None) -> list[dict[str, Any]]:
    """All approval gates of a run with their current status."""
    rd = Path(run_dir)
    rid = run_id or rd.name
    now = datetime.now(timezone.utc)
    return [_gate_view(n, rid, now) for n in _gate_nodes(_load_graph(rd))]


def pending_gates(run_dir: Path | str, run_id: str | None = None) -> list[dict[str, Any]]:
    return [g for g in list_gates(run_dir, run_id) if g["status"] == "pending"]


def awaiting_approval_overlay(run_dir: Path | str, status: str) -> dict[str, Any]:
    """Display fields for a running run blocked on a gate (else ``{}``).

    Returns ``{status: "awaiting_approval", durable_status: "running",
    awaiting_approval: True, pending_gates: [node_id, …]}``. The durable
    meta status stays ``running`` (transition matrix unchanged).
    """
    if status != "running":
        return {}
    try:
        graph = _load_graph(Path(run_dir))
        if not _gate_nodes(graph):
            return {}
        waiting = pending_gates(run_dir)
    except Exception:
        return {}
    if not waiting:
        return {}
    return {
        "status": "awaiting_approval",
        "durable_status": "running",
        "awaiting_approval": True,
        "pending_gates": [g["node_id"] for g in waiting],
    }


def gate_approver_roles(run_dir: Path | str, node_id: str) -> list[str]:
    """``approver_roles`` configured on one gate node (empty when unknown)."""
    try:
        node = next((n for n in _gate_nodes(_load_graph(Path(run_dir))) if n.get("id") == node_id), None)
    except Exception:
        return []
    cfg = (node or {}).get("config") if isinstance((node or {}).get("config"), dict) else {}
    return [str(r) for r in (cfg.get("approver_roles") or [])]


def decide_gate(
    run_dir: Path | str,
    node_id: str,
    *,
    decision: str,
    comment: str | None,
    actor: str,
    actor_verified: bool,
    role: str | None = None,
    source: str = "api",
    claimed_actor: str | None = None,
    role_verified: bool = False,
    user_id: str | None = None,
    credential_id: str | None = None,
) -> dict[str, Any]:
    """Write the decision file for a pending gate (create-only, atomic).

    Raises GateError: 404 unknown gate, 409 not pending / already decided,
    422 bad decision / missing required comment.
    """
    rd = Path(run_dir)
    run_id = rd.name
    verdict = str(decision or "").strip().lower()
    if verdict not in ("approve", "reject"):
        raise GateError(422, "validation_failed", "decision must be 'approve' or 'reject'")
    text = (comment or "").strip()
    if len(text) > 4000:
        raise GateError(422, "validation_failed", "comment must be at most 4000 characters")
    node = next((n for n in _gate_nodes(_load_graph(rd)) if n.get("id") == node_id), None)
    if node is None:
        raise GateError(404, "not_found", f"Run {run_id} has no approval gate '{node_id}'")
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    # Jail check before status — refuse escaped decision_dir even when not pending.
    _resolve_decision_dir(str(cfg.get("decision_dir") or DEFAULT_DECISION_DIR), strict=True)
    gate = _gate_view(node, run_id, datetime.now(timezone.utc))
    if gate["status"] != "pending":
        raise GateError(409, "gate_not_pending", f"Gate '{node_id}' is {gate['status']}, not pending")
    if gate["reason_required"] and not text:
        raise GateError(422, "validation_failed", "This gate requires a comment (reason)")
    roles = [str(r) for r in gate["approver_roles"]]
    if roles and verdict == "approve" and (role or "") not in roles:
        raise GateError(422, "validation_failed", f"role must be one of {roles} to approve")

    _, decision_path = _paths(
        str(cfg.get("decision_dir") or DEFAULT_DECISION_DIR),
        run_id,
        gate["gate_id"],
        strict=True,
    )
    comment_sha = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
    record = {
        "request_id": gate["request_id"],
        "approved": verdict == "approve",
        "approver": actor,
        "role": role or "",
        "reason": text,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "actor_verified": bool(actor_verified),
        "role_verified": bool(role_verified),
        "user_id": user_id,
        "credential_id": credential_id,
        "source": source,
        "comment_sha256": comment_sha,
    }
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = decision_path.with_name(f".{decision_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        try:
            # Create-only: a concurrent / earlier decision wins; never overwrite.
            os.link(tmp, decision_path)
        except FileExistsError as exc:
            existing = _read_json(decision_path) or {}
            if existing.get("request_id") == gate["request_id"]:
                raise GateError(409, "gate_already_decided", f"Gate '{node_id}' already has a decision") from exc
            # Stale decision from an earlier run attempt — replace atomically.
            os.replace(tmp, decision_path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action="gate.decision",
            resource_type="run",
            resource_id=run_id,
            meta={
                "node_id": node_id,
                "gate_id": gate["gate_id"],
                "decision": verdict,
                "role": role or None,
                "role_verified": bool(role_verified),
                "comment_sha256": comment_sha,
                "request_id": gate["request_id"],
                "source": source,
            },
            actor_verified=bool(actor_verified),
            claimed_actor=claimed_actor,
        )
    except Exception:
        log.debug("gates: audit failed", exc_info=True)

    out = dict(gate)
    out.update({"status": "decided", "pending": False, "decision": _public_decision(record)})
    return out
