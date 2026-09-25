# app/api/routers/ship.py
"""
Bounded Context:  REST API Layer
Responsibility:   Ship package REST (§9.2.14) under /projects/{name}/ship/packages.
Owns:             list/create/get/download/promote/transition routes.
Public Surface:   FastAPI router mounted at /api/v1.
Must NOT:         Contain persistence — delegate to app.core.ship_packages.
Dependencies:     fastapi, ship_packages, idempotency, actor, errors patterns.
Reason To Change: New ship package endpoint or contract change.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor

router = APIRouter(prefix="/projects", tags=["ship"])


def _pm():
    from app.domain.project_manager import ProjectManager

    return ProjectManager()


def _require_project(name: str):
    try:
        return _pm()._require_project(name)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc


def _invalid_transition(package_id: str, current: str, action: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "invalid_transition",
            "message": f"cannot {action} from status={current}",
            "package_id": package_id,
            "resource_type": "ship_package",
        },
    )


class CreateShipPackageBody(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=64)
    model_stage_or_version: str = Field(..., min_length=1, max_length=64)
    target: dict[str, Any] = Field(..., description="runtime/arch and optional extras")
    env: Optional[str] = Field("draft", description="draft|staging")
    notes: Optional[str] = None
    unsigned_allowed: bool = True


class PromoteShipPackageBody(BaseModel):
    to_env: str = Field(..., description="staging|prod")
    approve: bool = False
    resource_version: Optional[str] = None


class TransitionShipPackageBody(BaseModel):
    action: str = Field(
        ...,
        description="validate|build|sign|publish|deploy|fail|supersede",
    )
    resource_version: Optional[str] = None


@router.get("/{name}/ship/packages", summary="List ship packages")
def list_ship_packages(
    name: str,
    limit: int = Query(100, ge=1, le=500),
    env: Optional[str] = Query(None),
):
    from app.core.ship_packages import list_packages

    project_dir = _require_project(name)
    return list_packages(project_dir, limit=limit, env=env)


@router.post("/{name}/ship/packages", summary="Create a ship package", status_code=201)
def create_ship_package(name: str, body: CreateShipPackageBody, request: Request):
    """POST create — Idempotency-Key required (API-CONV-004 / §9.2.14)."""
    from app.api.idempotency import begin_idempotent, complete_idempotent
    from app.core.ship_packages import InvalidPackageTransition, create_package

    key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
    if not key or not str(key).strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Idempotency-Key header is required",
            },
        )

    body_dict = body.model_dump()
    cached = begin_idempotent(request, body=body_dict, route=f"POST /projects/{name}/ship/packages")
    if cached is not None:
        return cached

    project_dir = _require_project(name)
    try:
        result = create_package(
            project_dir,
            project_name=name,
            model_name=body.model_name,
            model_stage_or_version=body.model_stage_or_version,
            target=body.target,
            env=body.env or "draft",
            actor=resolve_actor(request),
            notes=body.notes,
            unsigned_allowed=body.unsigned_allowed,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except InvalidPackageTransition as exc:
        raise _invalid_transition("new", exc.current, exc.action) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_failed", "message": str(exc)},
        ) from exc

    complete_idempotent(request, status_code=201, body=result)
    return JSONResponse(status_code=201, content=result)


@router.get("/{name}/ship/packages/{package_id}", summary="Get ship package")
def get_ship_package(name: str, package_id: str):
    from app.core.ship_packages import get_package

    project_dir = _require_project(name)
    try:
        return get_package(project_dir, package_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_failed", "message": str(exc)},
        ) from exc


@router.get(
    "/{name}/ship/packages/{package_id}/download",
    summary="Download ship package archive",
)
def download_ship_package(name: str, package_id: str):
    from app.core.ship_packages import download_package_path

    project_dir = _require_project(name)
    try:
        archive, man = download_package_path(project_dir, package_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "conflict", "message": str(exc)},
        ) from exc

    checksums = man.get("checksums") if isinstance(man.get("checksums"), dict) else {}
    sha = str(checksums.get("sha256") or "")
    headers = {
        "Content-Disposition": f'attachment; filename="{package_id}.zip"',
    }
    if sha:
        headers["X-Content-SHA256"] = sha
    return FileResponse(
        path=str(archive),
        media_type="application/octet-stream",
        filename=f"{package_id}.zip",
        headers=headers,
    )


@router.post(
    "/{name}/ship/packages/{package_id}/promote",
    summary="Promote ship package to staging/prod",
)
def promote_ship_package(
    name: str, package_id: str, body: PromoteShipPackageBody, request: Request
):
    """Promote — Idempotency-Key required."""
    from app.api.idempotency import begin_idempotent, complete_idempotent
    from app.core.ship_packages import InvalidPackageTransition, promote_package

    key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
    if not key or not str(key).strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Idempotency-Key header is required",
            },
        )

    body_dict = body.model_dump()
    cached = begin_idempotent(
        request,
        body=body_dict,
        route=f"POST /projects/{name}/ship/packages/{package_id}/promote",
    )
    if cached is not None:
        return cached

    from app.api.concurrency import resolve_expected_version, version_conflict_http
    from app.core.errors import VersionConflict

    expected, via_if_match = resolve_expected_version(request, body.resource_version)
    project_dir = _require_project(name)
    try:
        result = promote_package(
            project_dir,
            package_id,
            to_env=body.to_env,
            approve=body.approve,
            actor=resolve_actor(request),
            expected_resource_version=expected,
            via_if_match=via_if_match,
        )
    except VersionConflict as exc:
        raise version_conflict_http(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except InvalidPackageTransition as exc:
        raise _invalid_transition(package_id, exc.current, exc.action) from exc
    except ValueError as exc:
        msg = str(exc)
        code = "validation_failed"
        status = 422
        if "approve" in msg.lower():
            status = 400
        raise HTTPException(
            status_code=status,
            detail={"error": code, "message": msg},
        ) from exc

    complete_idempotent(request, status_code=200, body=result)
    return result


@router.post(
    "/{name}/ship/packages/{package_id}/transition",
    summary="Apply a lifecycle transition",
)
def transition_ship_package(
    name: str, package_id: str, body: TransitionShipPackageBody, request: Request
):
    from app.core.ship_packages import InvalidPackageTransition, transition_package

    from app.api.concurrency import resolve_expected_version, version_conflict_http
    from app.core.errors import VersionConflict

    expected, via_if_match = resolve_expected_version(request, body.resource_version)
    project_dir = _require_project(name)
    try:
        return transition_package(
            project_dir,
            package_id,
            body.action,
            actor=resolve_actor(request),
            expected_resource_version=expected,
            via_if_match=via_if_match,
        )
    except VersionConflict as exc:
        raise version_conflict_http(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except InvalidPackageTransition as exc:
        raise _invalid_transition(package_id, exc.current, exc.action) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_failed", "message": str(exc)},
        ) from exc
