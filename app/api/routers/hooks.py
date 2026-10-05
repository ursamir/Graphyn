# app/api/routers/hooks.py
"""
Bounded Context:  REST API Layer
Responsibility:   Inbound webhook trigger endpoint and per-pipeline hook
                  management.
Owns:             public_router: POST /hooks/{workspace}/{pipeline}
                  (own auth: HMAC signature or bearer token — mounted
                  WITHOUT the global bearer dependency);
                  router: GET/PUT/DELETE /projects/{ws}/pipelines/{p}/hook,
                  POST /projects/{ws}/pipelines/{p}/hook/rotate (bearer auth).
Public Surface:   public_router, router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain trigger / signature logic (app.core.pipelines.hooks);
                  log or echo secrets except the one-time rotate response.
Dependencies:     fastapi, app.core.pipelines.hooks, app.api.actor,
                  app.core.trust.identity, app.core.trust.audit.
Reason To Change: Hook endpoint contract or auth policy changes.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.pipelines.hooks import HookError

public_router = APIRouter(tags=["hooks"])
router = APIRouter(tags=["hooks"])

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_QUERY_KEYS = 50


def _http(exc: HookError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers=exc.headers or None,
    )


def _project_dir(workspace: str) -> Path:
    from app.core.config import datasets_output_dir

    if not _SAFE_NAME.match(workspace or ""):
        raise HTTPException(status_code=422, detail={"code": "validation_failed", "message": "Invalid workspace name"})
    path = datasets_output_dir() / workspace
    if not path.is_dir():
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"Project not found: {workspace}"})
    return path


def _client_ip(request: Request) -> Optional[str]:
    client = getattr(request, "client", None)
    return getattr(client, "host", None) if client else None


# ── Inbound trigger ────────────────────────────────────────────────────────────

@public_router.post(
    "/hooks/{workspace}/{pipeline}",
    status_code=202,
    summary="Inbound webhook: start a pipeline run with the request payload",
)
async def receive_webhook(
    workspace: str,
    pipeline: str,
    request: Request,
    env: Optional[str] = Query(None, description="draft | staging | prod (must be in the hook's allowed_envs)"),
):
    """Authenticate (HMAC signature or bearer token), then start the run.

    Returns 202 ``{run_id, status, hook_id, env, idempotent_replay}``.
    """
    from app.core.host.shutdown import is_draining
    from app.core.pipelines import hooks as core
    from app.core.trust.identity import bearer_from_header, lookup_token, token_accepted

    if is_draining():
        raise HTTPException(status_code=503, detail={"code": "draining", "message": "Control plane is shutting down", "retryable": True}, headers={"Retry-After": "30"})
    project_dir = _project_dir(workspace)
    try:
        hook = core.get_hook(project_dir, pipeline)
    except HookError as exc:
        raise _http(exc)
    if not hook or not hook.get("enabled"):
        raise HTTPException(status_code=404, detail={"code": "hook_not_found", "message": "No enabled webhook for this pipeline"})

    limit = core.max_body_bytes()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large", "message": f"Body exceeds {limit} bytes"})
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            raise HTTPException(status_code=413, detail={"code": "payload_too_large", "message": f"Body exceeds {limit} bytes"})

    signature = request.headers.get(core.SIGNATURE_HEADER)
    principal: Optional[str] = None
    try:
        if signature:
            cid = hook.get("secret_connection_id")
            if not cid:
                raise HookError(401, "no_secret", "Hook has no signing secret; rotate one first")
            from app.core.credentials import get_payload

            try:
                _kind, payload = await run_in_threadpool(get_payload, str(cid))
            except Exception as exc:
                raise HookError(401, "no_secret", "Hook signing secret is unavailable") from exc
            secret = str(payload.get("secret") or "")
            if not secret:
                raise HookError(401, "no_secret", "Hook signing secret is empty")
            core.verify_signature(secret, raw, signature, request.headers.get(core.TIMESTAMP_HEADER),
                                  check_replay=False)
            auth_method, actor_verified = "hmac", True
        else:
            token = bearer_from_header(request.headers.get("authorization"))
            if not token or not token_accepted(token):
                raise HookError(401, "unauthorized",
                                "Send X-Graphyn-Signature + X-Graphyn-Timestamp, or Authorization: Bearer <token>")
            principal = lookup_token(token)
            auth_method, actor_verified = "bearer", principal is not None
        core.check_rate_limit(str(hook.get("hook_id") or pipeline))
        default_env_early = str(hook.get("env") or "prod")
        prior_run = await run_in_threadpool(
            core.find_idempotent_run, project_dir, pipeline, request.headers.get("idempotency-key")
        )
        if prior_run:
            # Authenticated retry of an already-accepted delivery → original run.
            return JSONResponse(
                status_code=200,
                content={"run_id": prior_run, "status": "accepted", "hook_id": hook.get("hook_id"),
                         "env": (env or default_env_early).strip().lower(), "idempotent_replay": True},
                headers={"X-Run-Id": prior_run},
            )
        if signature and not core.remember_signature(signature, request.headers.get(core.TIMESTAMP_HEADER)):
            raise HookError(409, "replay_detected", "This signed request was already accepted")

        default_env = str(hook.get("env") or "prod")
        chosen = (env or default_env).strip().lower()
        allowed = list(hook.get("allowed_envs") or [default_env])
        if chosen not in allowed:
            raise HookError(403, "env_not_allowed", f"env '{chosen}' is not allowed for this hook (allowed: {allowed})")

        query: dict[str, str] = {}
        for key, value in request.query_params.multi_items():
            if key == "env" or key in query:
                continue
            if len(query) >= _MAX_QUERY_KEYS:
                break
            query[str(key)[:128]] = str(value)[:1024]

        ack = await run_in_threadpool(
            core.start_webhook_run,
            project_dir=project_dir,
            workspace=workspace,
            pipeline=pipeline,
            hook=hook,
            env=chosen,
            raw_body=raw,
            headers={k.lower(): v for k, v in request.headers.items()},
            query=query,
            actor=f"webhook:{hook.get('hook_id')}",
            actor_verified=actor_verified,
            auth_method=auth_method,
            source_ip=_client_ip(request),
            idempotency_key=request.headers.get("idempotency-key"),
            principal=principal,
        )
    except HookError as exc:
        _audit_rejected(workspace, pipeline, hook, exc, request)
        raise _http(exc)
    status = 200 if ack.get("idempotent_replay") else 202
    return JSONResponse(status_code=status, content=ack, headers={"X-Run-Id": str(ack["run_id"])})


def _audit_rejected(workspace: str, pipeline: str, hook: dict, exc: HookError, request: Request) -> None:
    """Audit refused deliveries (bad signature / replay / rate limit)."""
    if exc.status_code not in (401, 403, 409, 429):
        return
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=f"webhook:{hook.get('hook_id')}",
            action="webhook.rejected",
            resource_type="pipeline",
            resource_id=f"{workspace}/{pipeline}",
            meta={"code": exc.code, "status": exc.status_code, "source_ip": _client_ip(request)},
            result="denied",
            actor_verified=False,
        )
    except Exception:
        pass


# ── Management ─────────────────────────────────────────────────────────────────

class HookUpdateBody(BaseModel):
    enabled: Optional[bool] = None
    env: Optional[str] = None
    allowed_envs: Optional[list[str]] = None
    header_allowlist: Optional[list[str]] = None


def _audit(request: Request, action: str, workspace: str, pipeline: str, meta: dict[str, Any]) -> None:
    try:
        from app.api.actor import audit_identity_fields
        from app.core.trust.audit import record_audit

        record_audit(action=action, resource_type="pipeline_hook",
                     resource_id=f"{workspace}/{pipeline}", meta=meta,
                     **audit_identity_fields(request))
    except Exception:
        pass


@router.get("/projects/{workspace}/pipelines/{pipeline}/hook", summary="Get pipeline webhook settings")
def get_pipeline_hook(workspace: str, pipeline: str):
    from app.core.pipelines import hooks as core

    project_dir = _project_dir(workspace)
    try:
        if not core._pipeline_exists(project_dir, pipeline):
            raise HookError(404, "not_found", f"Pipeline '{pipeline}' not found")
        return core.public_hook_view(core.get_hook(project_dir, pipeline), workspace, pipeline)
    except HookError as exc:
        raise _http(exc)


@router.put("/projects/{workspace}/pipelines/{pipeline}/hook", summary="Create / update pipeline webhook settings")
def put_pipeline_hook(workspace: str, pipeline: str, request: Request, body: HookUpdateBody = Body(...)):
    from app.api.actor import resolve_actor
    from app.core.pipelines import hooks as core

    project_dir = _project_dir(workspace)
    try:
        before = core.get_hook(project_dir, pipeline)
        hook = core.put_hook(
            project_dir, pipeline,
            enabled=body.enabled, env=body.env, allowed_envs=body.allowed_envs,
            header_allowlist=body.header_allowlist, actor=resolve_actor(request),
        )
    except HookError as exc:
        raise _http(exc)
    view = core.public_hook_view(hook, workspace, pipeline)
    _audit(request, "hook.create" if before is None else "hook.update", workspace, pipeline,
           {"enabled": view["enabled"], "env": view["env"], "allowed_envs": view["allowed_envs"],
            "hook_id": view["hook_id"]})
    return view


@router.delete("/projects/{workspace}/pipelines/{pipeline}/hook", summary="Delete pipeline webhook (revokes secret)")
def delete_pipeline_hook(workspace: str, pipeline: str, request: Request):
    from app.core.pipelines import hooks as core

    project_dir = _project_dir(workspace)
    try:
        old = core.delete_hook(project_dir, pipeline)
    except HookError as exc:
        raise _http(exc)
    if old is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Pipeline has no webhook"})
    _audit(request, "hook.delete", workspace, pipeline, {"hook_id": old.get("hook_id")})
    return {"ok": True, "deleted": True, "hook_id": old.get("hook_id")}


@router.post("/projects/{workspace}/pipelines/{pipeline}/hook/rotate", summary="Create / rotate the webhook signing secret")
def rotate_pipeline_hook(workspace: str, pipeline: str, request: Request):
    """Returns the hook view plus ``secret`` — shown ONCE, never retrievable again."""
    from app.api.actor import resolve_actor
    from app.core.pipelines import hooks as core

    project_dir = _project_dir(workspace)
    try:
        hook, secret = core.rotate_hook_secret(project_dir, pipeline, actor=resolve_actor(request))
    except HookError as exc:
        raise _http(exc)
    view = core.public_hook_view(hook, workspace, pipeline)
    _audit(request, "hook.rotate", workspace, pipeline,
           {"hook_id": view["hook_id"], "secret_connection_id": view["secret_connection_id"]})
    return {**view, "secret": secret, "secret_shown_once": True}
