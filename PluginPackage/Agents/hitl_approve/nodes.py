"""HitlApproveNode — Human-in-the-loop approval gate before promote/ship/destructive ops

Approval is NEVER taken from the gated payload (an upstream step must not be
able to self-approve by emitting ``approved: true``). Decisions arrive
out-of-band through a decision file:

1. On execution the node writes a *request* file
   ``{decision_dir}/{run_id}__{gate_id}.request.json`` containing a random
   ``request_id``, the configured approver roles and the timeout.
2. A human (UI/CLI/ops tooling) writes the *decision* file
   ``{decision_dir}/{run_id}__{gate_id}.decision.json``::

       {"request_id": "<from request>", "approved": true,
        "approver": "alice", "role": "release-manager", "reason": "LGTM"}

3. The node polls for the decision until ``timeout_s`` elapses. A decision is
   honoured only when ``request_id`` matches (stale files from earlier runs are
   ignored), the role is in ``approver_roles`` (when configured) and a reason
   is present (when ``reason_required``).

No decision / timeout / invalid decision → the ``rejected`` port is emitted
(fail closed). ``unattended_approve=True`` is the only way to pass without a
human and must be set explicitly; it records a receipt.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("hitl_approve.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

DEFAULT_DECISION_DIR = "workspace/artifacts/agents/hitl_approve/decisions"


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value or "")[:128] or "adhoc"


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def decision_paths(decision_dir: str | Path, run_id: str, gate_id: str) -> tuple[Path, Path]:
    """Return ``(request_path, decision_path)`` for a gate in a run."""
    base = Path(decision_dir or DEFAULT_DECISION_DIR)
    stem = f"{_safe_key(run_id)}__{_safe_key(gate_id)}"
    return base / f"{stem}.request.json", base / f"{stem}.decision.json"


def _read_decision(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _evaluate_decision(decision: dict, request_id: str, config: Any) -> tuple[bool, str]:
    """Return ``(approved, reason_or_error)`` for a decision record."""
    if str(decision.get("request_id") or "") != request_id:
        return False, "stale decision (request_id mismatch)"
    approver = str(decision.get("approver") or "").strip()
    if not approver:
        return False, "decision has no approver"
    roles = [str(r) for r in (config.approver_roles or [])]
    role = str(decision.get("role") or "").strip()
    if roles and role not in roles:
        return False, f"approver role {role!r} not in approver_roles {roles}"
    reason = str(decision.get("reason") or "").strip()
    if config.reason_required and not reason:
        return False, "reason_required=True but decision has no reason"
    if decision.get("approved") is True:
        return True, reason
    return False, reason or "rejected by approver"


def _hitl(node: "HitlApproveNode", inputs: dict) -> dict:
    config = node.config
    payload = _dump(inputs.get("input"))
    run_id = str(getattr(node, "_run_id", "") or "adhoc")
    gate_id = str(config.gate_id or "hitl_approve")
    timeout_s = float(config.timeout_s)
    poll_s = max(0.01, float(config.poll_interval_s))
    request_path, decision_path = decision_paths(config.decision_dir, run_id, gate_id)

    if config.unattended_approve:
        receipt = {
            "approved": True,
            "mode": "unattended_approve",
            "run_id": run_id,
            "gate_id": gate_id,
            "approver": "unattended",
            "decided_at": _utc_now(),
        }
        try:
            _atomic_write_json(decision_path.with_name(decision_path.name.replace(
                ".decision.json", ".unattended.json")), receipt)
        except OSError:
            pass
        log.warning("hitl_approve: unattended_approve=True — gate %s passed with no human", gate_id)
        return {"approved": payload, "rejected": None, "decision": receipt}

    request_id = secrets.token_hex(16)
    request = {
        "request_id": request_id,
        "run_id": run_id,
        "gate_id": gate_id,
        "approver_roles": list(config.approver_roles or []),
        "reason_required": bool(config.reason_required),
        "timeout_s": timeout_s,
        "requested_at": _utc_now(),
        "decision_path": str(decision_path),
        "status": "pending",
    }
    _atomic_write_json(request_path, request)
    log.info("hitl_approve: waiting up to %.1fs for decision at %s", timeout_s, decision_path)

    deadline = time.monotonic() + max(0.0, timeout_s)
    outcome: tuple[bool, str] | None = None
    decision: dict | None = None
    while True:
        if decision_path.is_file():
            decision = _read_decision(decision_path)
            if decision is not None and str(decision.get("request_id") or "") == request_id:
                outcome = _evaluate_decision(decision, request_id, config)
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.0, min(poll_s, deadline - time.monotonic())))

    if outcome is None:
        approved, why = False, f"no decision within timeout_s={timeout_s}"
        decision = None
    else:
        approved, why = outcome

    record = {
        "approved": approved,
        "reason": why,
        "run_id": run_id,
        "gate_id": gate_id,
        "request_id": request_id,
        "approver": (decision or {}).get("approver"),
        "role": (decision or {}).get("role"),
        "decided_at": _utc_now(),
    }
    try:
        _atomic_write_json(request_path, {**request, "status": "approved" if approved else "rejected",
                                          "outcome": record})
    except OSError:
        pass
    if approved:
        return {"approved": payload, "rejected": None, "decision": record}
    log.warning("hitl_approve: gate %s rejected: %s", gate_id, why)
    return {"approved": None, "rejected": {"payload": payload, **record}, "decision": record}


class HitlApproveNode(Node):
    """Human-in-the-loop approval gate before promote/ship/destructive ops"""

    node_type: ClassVar[str] = "hitl_approve"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="hitl_approve",
        label="Hitl Approve",
        description=(
            "Human-in-the-loop approval gate. Waits for an out-of-band decision file "
            "(never trusts the payload); emits `rejected` on timeout/denial."
        ),
        category="Control",
        version="0.2.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="Any"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "approved": OutputPort(name="approved", data_type=object, description="Payload when approved, else None"),
        "rejected": OutputPort(name="rejected", data_type=object, description="Rejection record (payload + reason) when not approved, else None"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        timeout_s: float = Field(default=3600.0, ge=0, title="Timeout s", description="Seconds to wait for a decision before rejecting (0 = check once).")
        poll_interval_s: float = Field(default=2.0, gt=0, title="Poll interval s", description="Decision file poll interval.")
        approver_roles: list = Field(default_factory=list, title="Approver roles", description="Allowed decision roles (empty = any named approver).")
        reason_required: bool = Field(default=True, title="Reason required", description="Reject decisions that carry no reason.")
        gate_id: str = Field(default="hitl_approve", title="Gate id", description="Decision key within the run (use the graph node id).")
        decision_dir: str = Field(default=DEFAULT_DECISION_DIR, title="Decision dir", description="Directory for request/decision files.")
        unattended_approve: bool = Field(
            default=False,
            title="Unattended approve",
            description="DANGEROUS: pass the gate with no human present (records a receipt). Default false.",
        )

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        if bool(self.config.stub):
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            return {"approved": None, "rejected": None}
        return self._process_real(inputs)

    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        result = _hitl(self, inputs)
        return {"approved": result["approved"], "rejected": result["rejected"]}
