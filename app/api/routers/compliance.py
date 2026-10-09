# app/api/routers/compliance.py
"""
Bounded Context:  REST API Layer
Responsibility:   Compliance export pack + retention/KMS/residency status.
Owns:             /compliance/* routes.
Public Surface:   router (authenticated; export requires admin).
Must NOT:         Leak secrets or raw CMK material.
Dependencies:     fastapi, app.core.trust.compliance / kms / residency / rbac.
Reason To Change: Compliance pack contents or auth policy.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter(tags=["compliance"])


def _ident() -> dict[str, Any]:
    from app.core.trust.identity import current_identity

    return current_identity() or {}


def _require_admin() -> dict[str, Any]:
    ident = _ident()
    if ident.get("kind") == "user":
        from app.core.trust.rbac import permissions_for

        perms = permissions_for(ident.get("roles") or [])
        if "users.admin" in perms or "admin" in perms or "audit.read" in perms:
            return ident
        raise HTTPException(status_code=403, detail="Compliance export requires admin or audit.read")
    # Break-glass operator / shared token
    if ident.get("kind") in (None, "operator", "token"):
        return ident
    raise HTTPException(status_code=403, detail="Compliance export requires admin")


@router.get("/compliance/status", summary="KMS, residency, and audit retention status")
def compliance_status():
    from app.core.trust.compliance import compliance_status as _status

    return _status()


@router.get("/compliance/export", summary="Download compliance export pack (zip)")
def compliance_export(
    org_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO timestamp lower bound"),
    until: Optional[str] = Query(None, description="ISO timestamp upper bound"),
    limit: int = Query(50_000, ge=1, le=100_000),
):
    """Zip bundle: audit JSONL + retention/KMS/residency policy + doc excerpts."""
    _require_admin()
    from app.core.trust.compliance import build_compliance_bundle
    from app.core.trust.audit import record_audit

    try:
        blob = build_compliance_bundle(
            org_id=org_id,
            since=since,
            until=until,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compliance export failed: {exc}") from exc
    try:
        record_audit(
            actor=str(_ident().get("actor") or "api"),
            action="compliance.export",
            resource_type="compliance",
            resource_id=org_id or "all",
            meta={"bytes": len(blob), "limit": limit},
        )
    except Exception:
        pass
    headers = {
        "Content-Disposition": 'attachment; filename="graphyn-compliance-pack.zip"',
    }
    return Response(content=blob, media_type="application/zip", headers=headers)


@router.get("/compliance/retention", summary="Audit retention policy")
def compliance_retention():
    from app.core.trust.compliance import retention_policy

    return retention_policy()


@router.post("/compliance/retention/prune", summary="Dry-run (default) or prune expired audit")
def compliance_prune(dry_run: bool = Query(True)):
    _require_admin()
    from app.core.trust.compliance import prune_expired_audit

    return prune_expired_audit(dry_run=dry_run)
