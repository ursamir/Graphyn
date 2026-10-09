# app/core/mlops/promotion_policy.py
"""
Bounded Context:  MLOps — model promotion governance
Responsibility:   Separation-of-duties (SoD) policy for prod promotion
                  (F19 / F-08): the principal that requested prod may not be
                  the principal that approves it.
Owns:             promotion_policy_path(), get_promotion_policy(),
                  set_promotion_policy(), check_separation_of_duties(),
                  SeparationOfDutiesError.
Public Surface:   The functions above.
Must NOT:         Import app.api; resolve identities (callers pass actors).
Dependencies:     app.core.config.project_dir, app.core.trust.audit (lazy).
Reason To Change: Promotion governance rules change.

Policy file ``<workspace>/configs/promotion_policy.json``::

    {"require_separation_of_duties": true,
     "updated_by": "...", "updated_at": "...", "reason": "..."}

SoD is ON when the file is absent. It can only be turned off by an explicit
admin policy change (``set_promotion_policy`` — the API route is admin-only),
which is audited; every approval made while SoD is waived is audited with
``sod_waived: true``.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Actors that do not identify a principal: SoD cannot be proven with them.
_ANONYMOUS = frozenset({"", "unidentified", "anonymous", "unknown", "api", "system", "human"})


class SeparationOfDutiesError(PermissionError):
    """Approval refused by the separation-of-duties policy → HTTP 403."""

    def __init__(self, message: str, *, code: str = "separation_of_duties") -> None:
        self.code = code
        super().__init__(message)


def promotion_policy_path(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None:
        root = Path(base_dir)
    else:
        from app.core.config import project_dir

        root = project_dir()
    return root / "configs" / "promotion_policy.json"


def get_promotion_policy(base_dir: str | Path | None = None) -> dict[str, Any]:
    path = promotion_policy_path(base_dir)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            data = {}  # unreadable policy → fail safe (SoD on)
    return {
        "require_separation_of_duties": data.get("require_separation_of_duties") is not False,
        "updated_by": data.get("updated_by"),
        "updated_at": data.get("updated_at"),
        "reason": data.get("reason"),
        "source": "policy_file" if data else "default",
    }


def set_promotion_policy(
    *,
    require_separation_of_duties: bool,
    actor: str,
    reason: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist the policy (admin only at the API layer) and audit the change."""
    actor = (actor or "").strip()
    if actor.lower() in _ANONYMOUS:
        raise SeparationOfDutiesError(
            "Changing the promotion policy requires an identified admin principal.",
            code="identity_required",
        )
    reason = (reason or "").strip()
    if not require_separation_of_duties and not reason:
        raise ValueError("A reason is required to waive separation of duties.")
    before = get_promotion_policy(base_dir)
    record = {
        "require_separation_of_duties": bool(require_separation_of_duties),
        "updated_by": actor,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or None,
    }
    path = promotion_policy_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".promotion_policy.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action="model.promotion_policy.update",
            resource_type="policy",
            resource_id="model-promotion",
            meta={"reason": reason or None},
            before={"require_separation_of_duties": before["require_separation_of_duties"]},
            after={"require_separation_of_duties": bool(require_separation_of_duties)},
            base_dir=base_dir,
        )
    except Exception:
        pass
    return get_promotion_policy(base_dir)


def check_separation_of_duties(
    *,
    requested_by: str | None,
    approver: str | None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Raise :class:`SeparationOfDutiesError` unless approver ≠ requester.

    Returns ``{"enforced": bool, "waived_by": str|None}`` for the audit record.
    """
    policy = get_promotion_policy(base_dir)
    if not policy["require_separation_of_duties"]:
        return {"enforced": False, "waived_by": policy.get("updated_by"), "waiver_reason": policy.get("reason")}
    req = (requested_by or "").strip()
    appr = (approver or "").strip()
    if appr.lower() in _ANONYMOUS:
        raise SeparationOfDutiesError(
            "Prod approval requires an identified approver (separation of duties). "
            "Sign in or use a named API token.",
            code="identity_required",
        )
    if req.lower() in _ANONYMOUS:
        raise SeparationOfDutiesError(
            "The pending prod request has no identified requester, so separation of duties "
            "cannot be verified. Re-request prod as an identified principal.",
        )
    if req.casefold() == appr.casefold():
        raise SeparationOfDutiesError(
            f"Separation of duties: '{appr}' requested this prod promotion and cannot also "
            "approve it. A different principal must approve."
        )
    return {"enforced": True, "waived_by": None}


__all__ = [
    "SeparationOfDutiesError",
    "check_separation_of_duties",
    "get_promotion_policy",
    "promotion_policy_path",
    "set_promotion_policy",
]
