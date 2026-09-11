# app/api/routers/models.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for the lightweight model registry.
Owns:             /api/v1/models routes.
Public Surface:   FastAPI router mounted at /api/v1.
Must NOT:         Contain registry persistence — delegate to model_registry.
Dependencies:     fastapi, app.core.model_registry, app.api.actor.
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
    from app.core.model_registry import list_models

    return {"models": list_models()}


@router.get("/{name}", summary="Get one registered model")
def get_model_endpoint(name: str):
    from app.core.model_registry import get_model

    try:
        return get_model(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", summary="Register model from a run (point stage alias)")
def register_model_endpoint(body: RegisterBody, request: Request):
    from app.core.model_registry import register_model

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
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{name}/request-prod", summary="Request prod stage (approval)")
def request_prod_endpoint(name: str, request: Request, body: RequestProdBody = RequestProdBody()):
    from app.core.model_registry import request_prod

    try:
        return request_prod(name, run_id=body.run_id, actor=resolve_actor(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{name}/approve-prod", summary="Approve pending prod stage")
def approve_prod_endpoint(name: str, request: Request):
    from app.core.model_registry import approve_prod

    try:
        return approve_prod(name, actor=resolve_actor(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
