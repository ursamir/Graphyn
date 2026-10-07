# app/api/routers/auth.py
"""
Bounded Context:  REST API Layer
Responsibility:   User sign-in, self-service credentials, user administration
                  and project membership (RBAC). Every mutation is audited
                  with the acting user and credential id.
Owns:             POST /auth/login, POST /auth/logout, POST /auth/bootstrap,
                  POST /me/password, GET|POST /me/tokens, DELETE /me/tokens/{id},
                  GET|POST /users, GET|PATCH /users/{id},
                  GET /users/{id}/tokens, DELETE /users/{id}/tokens/{tid},
                  GET /projects/{name}/members,
                  PUT|DELETE /projects/{name}/members/{user_id}.
Public Surface:   router (authenticated, RBAC-checked in app.api.main) and
                  public_router (POST /auth/login only).
Must NOT:         Return password hashes, token secrets or token hashes (a new
                  token is returned once, at creation).
Dependencies:     fastapi, pydantic, app.core.trust.{users, identity, rbac, audit}.
Reason To Change: Login / user admin / membership API changes.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.trust.users import (
    SESSION_TTL_S,
    UserStoreError,
    get_user_store,
)

router = APIRouter(tags=["auth"])
public_router = APIRouter(tags=["auth"])

_API_TOKEN_MAX_TTL_S = 365 * 86400
_FAIL_WINDOW_S = 300.0
_FAIL_MAX = 5
_fail_lock = threading.Lock()
_failures: dict[str, list[float]] = {}


def _err(exc: UserStoreError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _ident() -> dict[str, Any]:
    from app.core.trust.identity import current_identity

    return current_identity() or {}


def _audit(action: str, resource_type: str, resource_id: str, meta: dict | None = None, *, result: str = "success", actor: str = "api") -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(actor=actor, action=action, resource_type=resource_type, resource_id=resource_id, meta=meta or {}, result=result)
    except Exception:
        pass


def _current_user_id() -> str:
    uid = _ident().get("user_id")
    if not uid:
        raise HTTPException(status_code=403, detail="This endpoint needs a signed-in user (not the shared API token)")
    return str(uid)


def _is_user_admin(ident: dict[str, Any]) -> bool:
    if ident.get("kind") != "user":
        # Legacy shared token / unauthenticated dev act as break-glass admin.
        return ident.get("kind") in (None, "operator")
    from app.core.trust.rbac import permissions_for

    perms = permissions_for(ident.get("roles") or [])
    return "users.admin" in perms or "admin" in perms


# ── login ──────────────────────────────────────────────────────────────────────


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=1024)


def _client_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "?"
    return f"{username.strip().lower()}|{host}"


def _locked(key: str) -> bool:
    now = time.time()
    with _fail_lock:
        hits = [t for t in _failures.get(key, []) if now - t < _FAIL_WINDOW_S]
        _failures[key] = hits
        return len(hits) >= _FAIL_MAX


def _note_failure(key: str) -> None:
    with _fail_lock:
        _failures.setdefault(key, []).append(time.time())


@public_router.post("/auth/login", summary="Sign in with username + password")
def login(request: Request, body: LoginBody):
    """Returns a session bearer token (12 h). Five failures in 5 min lock the username for that client."""
    key = _client_key(request, body.username)
    if _locked(key):
        raise HTTPException(status_code=429, detail="Too many failed sign-ins — try again in a few minutes", headers={"Retry-After": "300"})
    store = get_user_store()
    user = store.authenticate(body.username, body.password)
    if user is None:
        _note_failure(key)
        _audit("auth.login", "user", body.username.strip().lower(), {"reason": "bad_credentials"}, result="failure", actor=body.username.strip().lower()[:64] or "unidentified")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    with _fail_lock:
        _failures.pop(key, None)
    ua = (request.headers.get("user-agent") or "")[:200]
    token, cred = store.issue_credential(
        "session", user_id=user.id, name="console session", ttl_s=SESSION_TTL_S, created_by=user.username, meta={"user_agent": ua}
    )
    _audit("auth.login", "user", user.id, {"credential_id": cred.id, "username": user.username}, actor=user.username)
    return {"token": token, "expires_at": cred.public()["expires_at"], "credential_id": cred.id, "user": user.public()}


@router.post("/auth/logout", summary="End the current session")
def logout():
    ident = _ident()
    cid = ident.get("credential_id")
    if ident.get("auth_method") == "session" and cid:
        get_user_store().revoke_credential(str(cid))
        _audit("auth.logout", "credential", str(cid))
    return {"ok": True}


class BootstrapBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=10, max_length=1024)
    display_name: str = Field("", max_length=128)


@router.post("/auth/bootstrap", summary="Create the first admin (only while no users exist)")
def bootstrap(body: BootstrapBody):
    ident = _ident()
    if ident.get("kind") == "user":
        raise HTTPException(status_code=409, detail="Users already exist")
    store = get_user_store()
    if store.has_users():
        raise HTTPException(status_code=409, detail="Users already exist — sign in as an admin to add more")
    try:
        user = store.create_user(body.username, body.password, roles=["admin"], display_name=body.display_name, created_by=str(ident.get("actor") or "bootstrap"))
    except UserStoreError as exc:
        raise _err(exc)
    _audit("user.create", "user", user.id, {"username": user.username, "roles": user.roles, "bootstrap": True})
    return {"user": user.public()}


# ── self-service ───────────────────────────────────────────────────────────────


class PasswordBody(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=10, max_length=1024)


@router.post("/me/password", summary="Change my password (ends my other sessions)")
def change_password(body: PasswordBody):
    uid = _current_user_id()
    store = get_user_store()
    user = store.get_user(uid)
    if user is None or store.authenticate(user.username, body.current_password) is None:
        raise HTTPException(status_code=401, detail="Current password is wrong")
    try:
        store.update_user(uid, password=body.new_password)
    except UserStoreError as exc:
        raise _err(exc)
    _audit("user.password_change", "user", uid)
    return {"ok": True, "note": "All sessions were signed out — sign in again."}


class TokenBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    ttl_days: Optional[int] = Field(90, ge=1, le=365)


def _tokens_view(user_id: str) -> list[dict[str, Any]]:
    return [c.public() for c in get_user_store().list_credentials(user_id=user_id, kind="api", include_inactive=True)]


@router.get("/me/tokens", summary="My personal API tokens")
def my_tokens():
    return _tokens_view(_current_user_id())


@router.post("/me/tokens", summary="Create a personal API token (shown once)")
def create_my_token(body: TokenBody):
    uid = _current_user_id()
    ident = _ident()
    ttl = min(int(body.ttl_days or 90) * 86400, _API_TOKEN_MAX_TTL_S)
    token, cred = get_user_store().issue_credential("api", user_id=uid, name=body.name, ttl_s=ttl, created_by=str(ident.get("actor") or ""))
    _audit("token.create", "credential", cred.id, {"name": cred.name, "user_id": uid, "expires_at": cred.public()["expires_at"]})
    return {"token": token, "credential": cred.public()}


@router.delete("/me/tokens/{token_id}", summary="Revoke one of my API tokens")
def revoke_my_token(token_id: str):
    uid = _current_user_id()
    store = get_user_store()
    cred = store.get_credential(token_id)
    if cred is None or cred.user_id != uid or cred.kind != "api":
        raise HTTPException(status_code=404, detail="Token not found")
    store.revoke_credential(token_id)
    _audit("token.revoke", "credential", token_id, {"user_id": uid})
    return {"ok": True}


# ── user admin ─────────────────────────────────────────────────────────────────


class UserCreateBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=10, max_length=1024)
    display_name: str = Field("", max_length=128)
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    approver_roles: list[str] = Field(default_factory=list)


class UserPatchBody(BaseModel):
    display_name: Optional[str] = Field(None, max_length=128)
    roles: Optional[list[str]] = None
    approver_roles: Optional[list[str]] = None
    disabled: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=10, max_length=1024)


def _require_user_admin() -> dict[str, Any]:
    ident = _ident()
    if not _is_user_admin(ident):
        raise HTTPException(status_code=403, detail="Permission 'users.admin' required")
    return ident


@router.get("/users", summary="List users")
def list_users():
    _require_user_admin()
    return [u.public() for u in get_user_store().list_users()]


@router.post("/users", summary="Create a user")
def create_user(body: UserCreateBody):
    ident = _require_user_admin()
    try:
        user = get_user_store().create_user(
            body.username,
            body.password,
            roles=body.roles,
            display_name=body.display_name,
            approver_roles=body.approver_roles,
            created_by=str(ident.get("actor") or ""),
        )
    except UserStoreError as exc:
        raise _err(exc)
    _audit("user.create", "user", user.id, {"username": user.username, "roles": user.roles, "approver_roles": user.approver_roles})
    return user.public()


@router.get("/users/{user_id}", summary="Get one user")
def get_user(user_id: str):
    _require_user_admin()
    user = get_user_store().get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user.public()


@router.patch("/users/{user_id}", summary="Update roles / approver roles / disabled / password")
def patch_user(user_id: str, body: UserPatchBody):
    _require_user_admin()
    store = get_user_store()
    before = store.get_user(user_id)
    if before is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        after = store.update_user(
            user_id,
            roles=body.roles,
            display_name=body.display_name,
            approver_roles=body.approver_roles,
            disabled=body.disabled,
            password=body.password,
        )
    except UserStoreError as exc:
        raise _err(exc)
    changed = {k: v for k, v in body.model_dump(exclude_none=True).items() if k != "password"}
    if body.password is not None:
        changed["password_reset"] = True
    _audit(
        "user.update",
        "user",
        user_id,
        {"username": after.username, "changes": changed, "roles_before": before.roles, "roles_after": after.roles},
    )
    return after.public()


@router.get("/users/{user_id}/tokens", summary="A user's API tokens and sessions")
def user_tokens(user_id: str):
    _require_user_admin()
    store = get_user_store()
    return [c.public() for c in store.list_credentials(user_id=user_id, include_inactive=True) if c.kind in ("api", "session")]


@router.delete("/users/{user_id}/tokens/{token_id}", summary="Revoke a user's token / session")
def revoke_user_token(user_id: str, token_id: str):
    _require_user_admin()
    store = get_user_store()
    cred = store.get_credential(token_id)
    if cred is None or cred.user_id != user_id:
        raise HTTPException(status_code=404, detail="Token not found")
    store.revoke_credential(token_id)
    _audit("token.revoke", "credential", token_id, {"user_id": user_id, "kind": cred.kind})
    return {"ok": True}


# ── project membership ─────────────────────────────────────────────────────────


class MemberBody(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)


@router.get("/projects/{name}/members", summary="Project members")
def project_members(name: str):
    return get_user_store().project_members(name)


@router.put("/projects/{name}/members/{user_id}", summary="Add / change a project member")
def put_member(name: str, user_id: str, body: MemberBody):
    ident = _ident()
    try:
        get_user_store().set_membership(name, user_id, body.role, added_by=str(ident.get("actor") or ""))
    except UserStoreError as exc:
        raise _err(exc)
    _audit("project.member_set", "project", name, {"user_id": user_id, "role": body.role.strip().lower()})
    return get_user_store().project_members(name)


@router.delete("/projects/{name}/members/{user_id}", summary="Remove a project member")
def delete_member(name: str, user_id: str):
    if not get_user_store().remove_membership(name, user_id):
        raise HTTPException(status_code=404, detail="Not a member")
    _audit("project.member_remove", "project", name, {"user_id": user_id})
    return get_user_store().project_members(name)
