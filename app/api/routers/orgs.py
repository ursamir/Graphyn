# app/api/routers/orgs.py
"""
Bounded Context:  REST API Layer
Responsibility:   Organization CRUD, membership, and active-org switching.
Owns:             /orgs* routes.
Public Surface:   router (authenticated).
Must NOT:         Leak credentials or cross-org data.
Dependencies:     fastapi, app.core.trust.orgs, users, audit, identity.
Reason To Change: Org tenancy API changes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.queue_schemas import OrgQuotaView, OrgUsageView, doc as _doc
from app.core.trust.orgs import (
    OrgStoreError,
    get_org_store,
    org_can_see_all_projects,
)
from app.core.trust.users import get_user_store

router = APIRouter(tags=["orgs"])


def _err(exc: OrgStoreError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _ident() -> dict[str, Any]:
    from app.core.trust.identity import current_identity

    return current_identity() or {}


def _audit(action: str, resource_id: str, meta: dict | None = None) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=str(_ident().get("actor") or "api"),
            action=action,
            resource_type="org",
            resource_id=resource_id,
            meta=meta or {},
        )
    except Exception:
        pass


def _require_user() -> dict[str, Any]:
    ident = _ident()
    if ident.get("kind") != "user" or not ident.get("user_id"):
        raise HTTPException(status_code=403, detail="Organization APIs require a signed-in user")
    return ident


def _is_platform_admin(ident: dict[str, Any]) -> bool:
    if ident.get("kind") != "user":
        return ident.get("kind") in (None, "operator")
    from app.core.trust.rbac import permissions_for

    perms = permissions_for(ident.get("roles") or [])
    return "users.admin" in perms or "admin" in perms


def _require_org_manager(org_id: str) -> tuple[dict[str, Any], str]:
    ident = _require_user()
    store = get_org_store()
    mem = store.membership_for(org_id, str(ident["user_id"]))
    if _is_platform_admin(ident):
        return ident, (mem.role if mem else "admin")
    if mem is None or mem.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Org owner or admin role required")
    return ident, mem.role


def _require_org_member(org_id: str) -> dict[str, Any]:
    ident = _require_user()
    if _is_platform_admin(ident):
        return ident
    if get_org_store().membership_for(org_id, str(ident["user_id"])) is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return ident


class OrgCreateBody(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    name: str = Field("", max_length=128)
    region: Optional[str] = Field(None, max_length=64)


class OrgPatchBody(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    disabled: Optional[bool] = None
    region: Optional[str] = Field(None, max_length=64)


class OrgMemberBody(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)


@router.get("/orgs", summary="List organizations")
def list_orgs():
    ident = _ident()
    store = get_org_store()
    if ident.get("kind") == "user" and not _is_platform_admin(ident):
        rows = store.orgs_for_user(str(ident["user_id"]))
        return [
            {**o.public(), "role": role, "active": o.id == ident.get("org_id")}
            for o, role in rows
        ]
    # Platform admin / break-glass: all orgs
    out = []
    for o in store.list_orgs():
        role = None
        if ident.get("kind") == "user":
            mem = store.membership_for(o.id, str(ident.get("user_id") or ""))
            role = mem.role if mem else None
        out.append({**o.public(), "role": role, "active": o.id == ident.get("org_id")})
    return out


@router.post("/orgs", summary="Create an organization")
def create_org(body: OrgCreateBody):
    ident = _require_user()
    store = get_org_store()
    try:
        org = store.create_org(
            body.slug,
            body.name,
            owner_user_id=str(ident["user_id"]),
            created_by=str(ident.get("actor") or ""),
            region=body.region,
        )
    except OrgStoreError as exc:
        raise _err(exc)
    _audit("org.create", org.id, {"slug": org.slug, "name": org.name})
    return {**org.public(), "role": "owner", "active": False}


@router.get("/orgs/{org_id}", summary="Get one organization")
def get_org(org_id: str):
    _require_org_member(org_id)
    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    mem = get_org_store().membership_for(org.id, str(_ident().get("user_id") or ""))
    return {**org.public(), "role": mem.role if mem else None, "active": org.id == _ident().get("org_id")}


@router.patch("/orgs/{org_id}", summary="Update organization")
def patch_org(org_id: str, body: OrgPatchBody):
    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    _require_org_manager(org.id)
    try:
        after = get_org_store().update_org(
            org.id, name=body.name, disabled=body.disabled, region=body.region
        )
    except OrgStoreError as exc:
        raise _err(exc)
    _audit("org.update", after.id, body.model_dump(exclude_none=True))
    return after.public()


@router.post("/orgs/{org_id}/activate", summary="Switch active organization for this session")
def activate_org(org_id: str):
    ident = _require_user()
    store = get_org_store()
    org = store.get_org(org_id) or store.get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    try:
        store.set_user_active_org(str(ident["user_id"]), org.id)
    except OrgStoreError as exc:
        raise _err(exc)
    # Stamp session / API credential meta so subsequent requests keep the org
    # even without the X-Graphyn-Org-Id header.
    cid = ident.get("credential_id")
    if cid:
        try:
            ustore = get_user_store()
            cred = ustore.get_credential(str(cid))
            if cred and cred.user_id == ident["user_id"]:
                meta = dict(cred.meta or {})
                meta["org_id"] = org.id
                with ustore._lock, ustore._conn() as c:
                    c.execute("UPDATE credentials SET meta=? WHERE id=?", (json_dumps(meta), cid))
        except Exception:
            pass
    mem = store.membership_for(org.id, str(ident["user_id"]))
    _audit("org.activate", org.id, {"slug": org.slug})
    return {
        "ok": True,
        "org": org.public(),
        "org_id": org.id,
        "org_role": mem.role if mem else None,
    }


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


@router.get("/orgs/{org_id}/members", summary="List organization members")
def list_members(org_id: str):
    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    _require_org_member(org.id)
    return [m.public() for m in get_org_store().org_members(org.id)]


@router.put("/orgs/{org_id}/members/{user_id}", summary="Add or update an organization member")
def put_member(org_id: str, user_id: str, body: OrgMemberBody):
    from app.core.trust.metering import MeterStoreError, get_meter_store

    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    ident, _ = _require_org_manager(org.id)
    existing = get_org_store().membership_for(org.id, user_id)
    if existing is None:
        try:
            get_meter_store().check_quota(org.id, "seats")
        except MeterStoreError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    try:
        get_org_store().set_membership(org.id, user_id, body.role, added_by=str(ident.get("actor") or ""))
    except OrgStoreError as exc:
        raise _err(exc)
    _audit("org.member_set", org.id, {"user_id": user_id, "role": body.role.strip().lower()})
    return [m.public() for m in get_org_store().org_members(org.id)]


@router.delete("/orgs/{org_id}/members/{user_id}", summary="Remove an organization member")
def delete_member(org_id: str, user_id: str):
    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    _require_org_manager(org.id)
    try:
        if not get_org_store().remove_membership(org.id, user_id):
            raise HTTPException(status_code=404, detail="Not a member")
    except OrgStoreError as exc:
        raise _err(exc)
    _audit("org.member_remove", org.id, {"user_id": user_id})
    return [m.public() for m in get_org_store().org_members(org.id)]



class QuotaBody(BaseModel):
    max_seats: Optional[int] = Field(None, ge=0)
    max_projects: Optional[int] = Field(None, ge=0)
    max_runs_per_day: Optional[int] = Field(None, ge=0)
    max_credentials: Optional[int] = Field(None, ge=0)
    max_concurrent_jobs: Optional[int] = Field(None, ge=0)
    max_queued_jobs: Optional[int] = Field(None, ge=0)


@router.get("/orgs/{org_id}/usage", summary="Organization usage counters", responses=_doc(OrgUsageView))
def org_usage(org_id: str):
    from app.core.trust.metering import get_meter_store

    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    _require_org_member(org.id)
    usage = get_meter_store().usage(org.id)
    quota = get_meter_store().get_quota(org.id)
    return {"usage": usage.public(), "quota": quota.public()}


@router.get("/orgs/{org_id}/quotas", summary="Organization quotas", responses=_doc(OrgQuotaView))
def org_quotas(org_id: str):
    from app.core.trust.metering import get_meter_store

    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    _require_org_member(org.id)
    return get_meter_store().get_quota(org.id).public()


@router.put("/orgs/{org_id}/quotas", summary="Set organization quotas (org owner/admin or platform admin)", responses=_doc(OrgQuotaView))
def put_org_quotas(org_id: str, body: QuotaBody):
    from app.core.trust.metering import MeterStoreError, get_meter_store

    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    ident, _ = _require_org_manager(org.id)
    try:
        q = get_meter_store().set_quota(
            org.id,
            max_seats=body.max_seats,
            max_projects=body.max_projects,
            max_runs_per_day=body.max_runs_per_day,
            max_credentials=body.max_credentials,
            max_concurrent_jobs=body.max_concurrent_jobs,
            max_queued_jobs=body.max_queued_jobs,
            updated_by=str(ident.get("actor") or ""),
        )
    except MeterStoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    _audit("org.quota_set", org.id, body.model_dump(exclude_none=True))
    return q.public()


@router.get("/orgs/{org_id}/meter-events", summary="List metering events for billing export")
def org_meter_events(org_id: str, limit: int = 100, since: Optional[float] = None):
    from app.core.trust.metering import get_meter_store

    org = get_org_store().get_org(org_id) or get_org_store().get_org_by_slug(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    _require_org_manager(org.id)
    return get_meter_store().list_events(org.id, since=since, limit=limit)
