# app/api/routers/models.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for the lightweight model registry.
Owns:             /api/v1/models routes (incl. GET /models/{name}/lineage —
                  made-from / used-in); registry error → HTTP mapping
                  (run missing 404, run not succeeded 409, direct
                  stage=prod 403 — prod only via request-prod/approve-prod,
                  compiled_untrained 422, model_not_in_run 422). Body
                  ``run_id`` accepts a unique prefix >= 8 chars (stored as
                  the full id; ambiguous → 409 run_id_ambiguous). GET rows
                  carry enriched stages (``kind: "model_stage"``, resolved
                  artifact path/format/size/metrics/labels).
Public Surface:   FastAPI router mounted at /api/v1.
Must NOT:         Contain registry persistence — delegate to model_registry.
Dependencies:     fastapi, app.core.mlops.model_registry,
                  app.core.mlops.model_lineage (GET /models/{name}/lineage),
                  app.domain.project_manager (project roots for ship packages),
                  app.api.actor, app.api.run_ids.
Reason To Change: New registry endpoint or response schema.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor

router = APIRouter(prefix="/models", tags=["models"])


class RegisterBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    run_id: str
    slug: Optional[str] = Field(
        None, description="Artifact slug; derived from the model path when omitted"
    )
    stage: str = "staging"
    description: Optional[str] = None
    model_path: Optional[str] = Field(
        None, description="Row ``path`` from GET /runs/{run_id}/models (preferred)"
    )
    node_id: Optional[str] = Field(None, description="Pick the model produced by this node")
    allow_untrained: bool = Field(
        False, description="Allow registering a compiled_untrained (model_builder) artifact"
    )


class RequestProdBody(BaseModel):
    run_id: Optional[str] = None


@router.get("", summary="List registered models")
def list_models_endpoint():
    from app.api.store_guard import ensure_store_readable
    from app.core.mlops.model_registry import list_models

    ensure_store_readable()
    from app.core.mlops.model_registry import describe_models

    try:
        return {"models": describe_models()}
    except Exception:
        return {"models": list_models()}


class PromotionPolicyOut(BaseModel):
    require_separation_of_duties: bool = Field(..., description="Requester and approver of a prod promotion must be different principals")
    updated_by: Optional[str] = Field(None, description="Admin principal that last changed the policy")
    updated_at: Optional[str] = Field(None, description="ISO-8601 time of the last change")
    reason: Optional[str] = Field(None, description="Recorded reason (required to waive SoD)")
    source: str = Field(..., description="default (no policy file) or policy_file")


class PromotionPolicyBody(BaseModel):
    require_separation_of_duties: bool = Field(..., description="false waives SoD (admin only, audited)")
    reason: str = Field("", max_length=500, description="Why the policy changes (required when waiving SoD)")


@router.get("/promotion-policy", summary="Prod promotion governance policy", response_model=PromotionPolicyOut)
def get_promotion_policy_endpoint():
    from app.core.mlops.promotion_policy import get_promotion_policy

    return get_promotion_policy()


@router.put(
    "/promotion-policy",
    summary="Change prod promotion policy (admin only, audited)",
    response_model=PromotionPolicyOut,
)
def put_promotion_policy_endpoint(body: PromotionPolicyBody, request: Request):
    from app.api.actor import resolve_identity
    from app.core.mlops.promotion_policy import SeparationOfDutiesError, set_promotion_policy

    ident = resolve_identity(request)
    # Users/agents are RBAC-checked for "admin" by middleware; a worker identity never may.
    if str(ident.get("kind") or "") == "worker":
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "Admin only"})
    try:
        return set_promotion_policy(
            require_separation_of_duties=body.require_separation_of_duties,
            actor=str(ident.get("actor") or ""),
            reason=body.reason,
        )
    except SeparationOfDutiesError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "reason_required", "message": str(exc)}) from exc


@router.get("/{name}", summary="Get one registered model")
def get_model_endpoint(name: str):
    from app.api.store_guard import ensure_store_readable
    from app.core.mlops.model_registry import describe_model

    ensure_store_readable()
    try:
        return describe_model(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _project_dirs() -> list:
    """Project roots (for ship-package lookup); best-effort, never raises."""
    try:
        from app.domain.project_manager import ProjectManager

        pm = ProjectManager()
        out = []
        for row in pm.list_all():
            name = row.get("name") if isinstance(row, dict) else None
            if not name:
                continue
            try:
                out.append(pm._require_project(str(name)))
            except Exception:
                continue
        return out
    except Exception:
        return []


@router.get("/{name}/lineage", summary="Model lineage: made from / used in")
def get_model_lineage_endpoint(name: str):
    """``{name, description, stages: {stage: {run_id, node_id, path_id,
    artifact_path, format, model_hash, made_from: {...}}}, pending_prod,
    used_in: [...], packages: [...]}`` — see docs/API_REFERENCE.md."""
    from app.api.store_guard import ensure_store_readable
    from app.core.mlops.model_lineage import model_lineage

    ensure_store_readable()
    try:
        return model_lineage(name, project_dirs=_project_dirs())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _registry_http_error(exc: Exception) -> HTTPException | None:
    """Map typed registry errors: missing run 404, unfinished run 409,
    direct prod write 403 (must go through request-prod → approve-prod)."""
    from app.core.mlops.model_registry import (
        ModelArtifactNotFound,
        ModelRunNotFound,
        ModelRunNotSucceeded,
        ModelUntrained,
        ProdRequiresApproval,
    )

    if isinstance(exc, ModelUntrained):
        return HTTPException(
            status_code=422,
            detail={
                "code": "compiled_untrained",
                "message": str(exc),
                "artifact": exc.artifact,
                "hint": "Register the trainer's model, or pass allow_untrained=true",
            },
        )
    if isinstance(exc, ModelArtifactNotFound):
        return HTTPException(
            status_code=422, detail={"code": "model_not_in_run", "message": str(exc)}
        )

    if isinstance(exc, ModelRunNotFound):
        return HTTPException(status_code=404, detail={"code": "run_not_found", "message": str(exc)})
    if isinstance(exc, ModelRunNotSucceeded):
        return HTTPException(
            status_code=409,
            detail={"code": "run_not_succeeded", "message": str(exc), "status": exc.status},
        )
    if isinstance(exc, ProdRequiresApproval):
        return HTTPException(
            status_code=403,
            detail={"code": "prod_requires_approval", "message": str(exc)},
        )
    return None


@router.post("", summary="Register model from a run (point stage alias)")
def register_model_endpoint(body: RegisterBody, request: Request):
    from app.api.run_ids import resolve_run_id_http
    from app.core.mlops.model_registry import register_model

    # Short ids (unique prefix >= 8) resolve here; the registry stores the FULL id.
    run_id = resolve_run_id_http(body.run_id)
    try:
        return register_model(
            body.name,
            run_id=run_id,
            slug=body.slug or "",
            stage=body.stage,
            description=body.description,
            actor=resolve_actor(request),
            node_id=body.node_id,
            model_path=body.model_path,
            allow_untrained=body.allow_untrained,
        )
    except ValueError as exc:
        mapped = _registry_http_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{name}/request-prod", summary="Request prod stage (approval)")
def request_prod_endpoint(name: str, request: Request, body: RequestProdBody = RequestProdBody()):
    from app.api.run_ids import resolve_run_id_http
    from app.core.mlops.model_registry import request_prod

    run_id = resolve_run_id_http(body.run_id) if (body.run_id or "").strip() else body.run_id
    try:
        return request_prod(name, run_id=run_id, actor=resolve_actor(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        mapped = _registry_http_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{name}/approve-prod", summary="Approve pending prod stage")
def approve_prod_endpoint(name: str, request: Request):
    from app.core.mlops.model_registry import approve_prod

    from app.core.mlops.promotion_policy import SeparationOfDutiesError

    try:
        return approve_prod(name, actor=resolve_actor(request))
    except SeparationOfDutiesError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        mapped = _registry_http_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
