# app/api/routers/models.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for the lightweight model registry.
Owns:             /api/v1/models routes; registry error → HTTP mapping
                  (run missing 404, run not succeeded 409, direct
                  stage=prod 403 — prod only via request-prod/approve-prod).
Public Surface:   FastAPI router mounted at /api/v1.
Must NOT:         Contain registry persistence — delegate to model_registry.
Dependencies:     fastapi, app.core.mlops.model_registry, app.api.actor.
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
    slug: str
    stage: str = "staging"
    description: Optional[str] = None


class RequestProdBody(BaseModel):
    run_id: Optional[str] = None


@router.get("", summary="List registered models")
def list_models_endpoint():
    from app.api.store_guard import ensure_store_readable
    from app.core.mlops.model_registry import list_models

    ensure_store_readable()
    return {"models": list_models()}


@router.get("/{name}", summary="Get one registered model")
def get_model_endpoint(name: str):
    from app.api.store_guard import ensure_store_readable
    from app.core.mlops.model_registry import get_model

    ensure_store_readable()
    try:
        return get_model(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _registry_http_error(exc: Exception) -> HTTPException | None:
    """Map typed registry errors: missing run 404, unfinished run 409,
    direct prod write 403 (must go through request-prod → approve-prod)."""
    from app.core.mlops.model_registry import (
        ModelRunNotFound,
        ModelRunNotSucceeded,
        ProdRequiresApproval,
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
    from app.core.mlops.model_registry import register_model

    try:
        return register_model(
            body.name,
            run_id=body.run_id,
            slug=body.slug,
            stage=body.stage,
            description=body.description,
            actor=resolve_actor(request),
        )
    except ValueError as exc:
        mapped = _registry_http_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{name}/request-prod", summary="Request prod stage (approval)")
def request_prod_endpoint(name: str, request: Request, body: RequestProdBody = RequestProdBody()):
    from app.core.mlops.model_registry import request_prod

    try:
        return request_prod(name, run_id=body.run_id, actor=resolve_actor(request))
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

    try:
        return approve_prod(name, actor=resolve_actor(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        mapped = _registry_http_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
