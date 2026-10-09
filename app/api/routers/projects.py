# app/api/routers/projects.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for full project lifecycle management —
                  create, get, update, delete, clone, list versions, taxonomy,
                  contract, spec, annotations, quality reports, snapshots,
                  and curation decisions. Every workspace mutation records a
                  ``workspace.*`` audit event (category admin) via _audit.
Owns:             All route definitions under /api/v1/projects/.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain project storage logic — delegate to ProjectManager
                  and QualityChecker.
Dependencies:     fastapi, app.domain.project_manager.ProjectManager,
                  app.domain.quality_checker.QualityChecker,
                  app.core.trust.audit.record_audit.
Reason To Change: New project endpoint added, or project schema changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor
from app.domain.project_manager import ProjectManager
from app.domain.quality_checker import QualityChecker

router = APIRouter(prefix="/projects", tags=["projects"])

_pm = ProjectManager()
_qc = QualityChecker()


# ------------------------------------------------------------------ #
# Exception helpers                                                    #
# ------------------------------------------------------------------ #

def _handle(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), mapping common exceptions to HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _audit(
    request: Request | None,
    action: str,
    resource_id: str,
    *,
    meta: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    resource_type: str = "workspace",
) -> None:
    """Record one ``workspace.*`` audit event (best effort, never raises)."""
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            meta=meta or {},
            before=before,
            after=after,
            request_id=getattr(getattr(request, "state", None), "request_id", None),
        )
    except Exception:
        pass


def _meta_snapshot(name: str) -> dict[str, Any]:
    """Current project.json-derived fields (empty dict when unreadable)."""
    try:
        meta = _pm.get(name)
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def _delete_summary(name: str) -> dict[str, Any]:
    """What a workspace delete removes (computed before the rmtree, best effort)."""
    out: dict[str, Any] = {}
    try:
        from app.core.pipelines.project_pipelines import list_pipelines

        project_dir = _pm._require_project(name)
        out["pipelines"] = [p.get("name") for p in list_pipelines(project_dir)]
    except Exception:
        pass
    try:
        versions = _pm.list_versions(name)
        if isinstance(versions, list):
            out["dataset_versions"] = [
                v.get("version") if isinstance(v, dict) else str(v) for v in versions
            ]
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ #
# Request / Response models                                            #
# ------------------------------------------------------------------ #

class CreateProjectBody(BaseModel):
    name: str


class RenameProjectBody(BaseModel):
    new_name: str


class UpdateProjectBody(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    linked_input_labels: Optional[list[str]] = None
    favorite_pipelines: Optional[list[str]] = None
    resource_version: Optional[str] = None


class DeleteProjectBody(BaseModel):
    confirm: str


class SetStatusBody(BaseModel):
    status: str


class CloneProjectBody(BaseModel):
    new_name: str


class SetSpecBody(BaseModel):
    markdown: str


class AddAnnotationsBody(BaseModel):
    annotations: list[dict]


class ImportAnnotationsBody(BaseModel):
    content: str
    format: str


class BulkAnnotateBody(BaseModel):
    paths: list[str]
    label: str


class AddCurationDecisionBody(BaseModel):
    path: str
    decision: str


class QualityCheckBody(BaseModel):
    version: Optional[str] = None


class CreateSnapshotBody(BaseModel):
    snapshot_name: str


class DeduplicateBody(BaseModel):
    mode: str


class DatasetCardBody(BaseModel):
    pass


class RestoreVersionBody(BaseModel):
    pass


class ProjectLinksBody(BaseModel):
    inputs: Optional[list[str]] = None
    outputs: Optional[list[dict]] = None




# ------------------------------------------------------------------ #
# Project lifecycle                                                    #
# ------------------------------------------------------------------ #

@router.get("")
def list_projects(
    envelope: Optional[str] = Query(None, description="List envelope (default on). Pass 0/false/no/off for bare array."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
):
    """GET /projects — list all projects. Envelope by default (API-PAGE-001 P1); ``?envelope=0`` → bare array."""
    from app.api.pagination import maybe_envelope, parse_envelope_flag
    from app.api.store_guard import ensure_store_readable

    ensure_store_readable()
    items = _handle(_pm.list_all)
    if not isinstance(items, list):
        items = list(items or [])
    from app.core.trust.identity import current_identity
    from app.core.trust.rbac import visible_projects_filter

    visible = visible_projects_filter(current_identity())
    if visible is not None:
        items = [p for p in items if visible(p.get("name"))]
    if q:
        ql = q.lower()
        items = [
            p for p in items
            if ql in str(p.get("name", "")).lower()
            or ql in str(p.get("display_name", "")).lower()
        ]
    total = len(items)
    page = items[offset : offset + limit]
    return maybe_envelope(
        page,
        envelope=parse_envelope_flag(envelope),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("")
def create_project(body: CreateProjectBody, request: Request):
    """POST /projects — create a new project (Idempotency-Key supported)."""
    from app.api.idempotency import begin_idempotent, complete_idempotent, idempotency_guard

    cached = begin_idempotent(
        request, body=body.model_dump(), route="POST /api/v1/projects"
    )
    if cached is not None:
        return cached
    with idempotency_guard(request):
        try:
            result = _handle(_pm.create, body.name)
        except HTTPException as exc:
            # Duplicate name is a state conflict (409), not a validation error (422).
            if exc.status_code == 422 and "already exists" in str(exc.detail):
                raise HTTPException(status_code=409, detail=exc.detail) from exc
            raise
        from app.core.trust.identity import current_identity
        from app.core.trust.metering import MeterStoreError, get_meter_store, record_meter_event
        from app.core.trust.orgs import DEFAULT_ORG_ID, get_org_store

        ident = current_identity() or {}
        org_id = ident.get("org_id") or DEFAULT_ORG_ID
        try:
            get_meter_store().check_quota(str(org_id), "projects")
        except MeterStoreError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
        try:
            get_org_store().assign_project(body.name, str(org_id))
            record_meter_event(str(org_id), "project.created", actor=str(ident.get("actor") or ""), resource_type="project", resource_id=body.name)
            meta = dict(result) if isinstance(result, dict) else {}
            meta["org_id"] = org_id
            _pm._write_json(_pm._project_dir(body.name) / "project.json", meta)
            result = meta
        except HTTPException:
            raise
        except Exception:
            pass
        complete_idempotent(request, status_code=200, body=result)
    _audit(request, "workspace.created", body.name)
    return result


@router.get("/{name}")
def get_project(name: str):
    """GET /projects/{name} — single project metadata (SRS §9.2.1)."""
    return _handle(_pm.get, name)


@router.put("/{name}")
def update_project(name: str, body: UpdateProjectBody, request: Request):
    """PUT /projects/{name} — update project metadata (SRS §9.2.1).

    Legacy PATCH /{name} remains for rename-only clients.
    """
    if_match = request.headers.get("If-Match") or request.headers.get("if-match")
    before_meta = _meta_snapshot(name)
    try:
        result = _pm.update(
            name,
            display_name=body.display_name,
            description=body.description,
            tags=body.tags,
            linked_input_labels=body.linked_input_labels,
            favorite_pipelines=body.favorite_pipelines,
            resource_version=body.resource_version,
            if_match=if_match,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _raise_update_error(exc, if_match)
        raise
    _audit_update(request, name, body, before_meta)
    return result


_UPDATE_FIELDS = (
    "display_name",
    "description",
    "tags",
    "linked_input_labels",
    "favorite_pipelines",
)


def _audit_update(
    request: Request, name: str, body: UpdateProjectBody, before_meta: dict[str, Any]
) -> None:
    """``workspace.updated`` with the fields whose value actually changed."""
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field in _UPDATE_FIELDS:
        new = getattr(body, field)
        if new is None:
            continue
        old = before_meta.get(field) if before_meta else None
        if before_meta and old == new:
            continue
        before[field] = old
        after[field] = new
    if not after:
        return
    _audit(
        request,
        "workspace.updated",
        name,
        meta={"changed": sorted(after)},
        before=before,
        after=after,
    )


def _raise_update_error(exc: Exception, if_match: Optional[str]) -> None:
    """Map known PUT /projects/{name} failures to HTTP errors.

    Returns normally for unknown exceptions — the caller re-raises them.
    """
    from app.api.concurrency import version_conflict_http
    from app.core.errors import VersionConflict

    if isinstance(exc, VersionConflict):
        raise version_conflict_http(exc) from exc
    if str(exc) == "version_conflict":
        raise version_conflict_http(VersionConflict(via_if_match=bool(if_match))) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{name}")
def rename_project(name: str, body: RenameProjectBody, request: Request):
    """PATCH /projects/{name} — rename the workspace **id** (DEPRECATED).

    Kept for API compatibility only. It moves the workspace folder and
    nothing else: runs (``meta.project``), the audit chain
    (``audit/chains/<project>.jsonl``), the model registry, schedules and
    saved references keep the old id, so renaming orphans run history and
    breaks the per-project audit chain. To change what people see, use
    ``PUT /projects/{name}`` with ``display_name`` (the id stays the same).
    Records ``workspace.renamed``.
    """
    result = _handle(_pm.rename, name, body.new_name)
    _audit(
        request,
        "workspace.renamed",
        name,
        meta={
            "deprecated": True,
            "migrated": False,
            "note": "runs, audit chain, models and schedules keep the old id",
        },
        before={"name": name},
        after={"name": body.new_name},
    )
    return result


@router.delete("/{name}")
def delete_project(name: str, request: Request, body: DeleteProjectBody = Body(...)):
    """DELETE /projects/{name} — delete a project (requires confirm == name).

    Removes the workspace folder (pipelines + versions, spec/taxonomy/contract,
    links, snapshots, dataset output versions) and disables its schedules.
    Run history, run artifacts and registered models are kept.
    Records ``workspace.deleted`` with what was removed.
    """
    removed = _delete_summary(name) if body.confirm == name else {}
    _handle(_pm.delete, name, body.confirm)
    _audit(request, "workspace.deleted", name, meta={"removed": removed})
    return {"deleted": name}


@router.patch("/{name}/status")
def set_project_status(name: str, body: SetStatusBody, request: Request):
    """PATCH /projects/{name}/status — update project status.

    ``archived`` hides the workspace from the default Workspaces list in the
    console. Records ``workspace.archived`` / ``workspace.unarchived`` when
    crossing the archived boundary, else ``workspace.status_changed``.
    """
    old = str(_meta_snapshot(name).get("status") or "") or None
    result = _handle(_pm.set_status, name, body.status)
    new = result.get("status") if isinstance(result, dict) else body.status
    if new != old:
        if new == "archived":
            action = "workspace.archived"
        elif old == "archived":
            action = "workspace.unarchived"
        else:
            action = "workspace.status_changed"
        _audit(request, action, name, before={"status": old}, after={"status": new})
    return result


@router.post("/{name}/clone")
def clone_project(name: str, body: CloneProjectBody, request: Request):
    """POST /projects/{name}/clone — new workspace from this one's pipelines and settings.

    Copies draft pipelines, description, linked datasets and
    spec/taxonomy/contract. Not copied: runs, pipeline version history,
    models, snapshots or dataset output versions. Records ``workspace.cloned``.
    """
    result = _handle(_pm.clone, name, body.new_name)
    _audit(request, "workspace.cloned", body.new_name, meta={"source": name})
    return result



# ------------------------------------------------------------------ #
# Linked datasets (Phase 2)                                            #
# ------------------------------------------------------------------ #

@router.get("/{name}/links")
def get_project_links(name: str):
    """GET /projects/{name}/links — linked input labels (+ output refs, API-only).

    The console pins **inputs** only; ``outputs`` in ``links.json`` is retained
    for API / MCP callers and is not surfaced in Home or Datasets.
    """
    return _handle(_pm.get_links, name)


@router.post("/{name}/links")
def add_project_links(name: str, body: ProjectLinksBody, request: Request):
    """POST /projects/{name}/links — merge linked inputs/outputs (audited ``dataset.link``)."""
    out = _handle(_pm.add_links, name, body.inputs, body.outputs)
    _audit(
        request,
        "dataset.link",
        name,
        meta={"inputs": list(body.inputs or []), "outputs": list(body.outputs or [])},
    )
    return out


@router.delete("/{name}/links")
def remove_project_links(name: str, request: Request, body: ProjectLinksBody = Body(...)):
    """DELETE /projects/{name}/links — unlink specific inputs/outputs (audited ``dataset.unlink``)."""
    out = _handle(_pm.remove_links, name, body.inputs, body.outputs)
    _audit(
        request,
        "dataset.unlink",
        name,
        meta={"inputs": list(body.inputs or []), "outputs": list(body.outputs or [])},
    )
    return out


# ------------------------------------------------------------------ #
# Taxonomy                                                             #
# ------------------------------------------------------------------ #

@router.get("/{name}/taxonomy")
def get_taxonomy(name: str):
    """GET /projects/{name}/taxonomy — retrieve taxonomy tree."""
    return _handle(_pm.get_taxonomy, name)


@router.put("/{name}/taxonomy")
def set_taxonomy(name: str, body: list[dict], request: Request):
    """PUT /projects/{name}/taxonomy — replace taxonomy tree."""
    _handle(_pm.set_taxonomy, name, body)
    _audit(request, "workspace.taxonomy_updated", name, meta={"nodes": len(body)})
    return {"ok": True}


# ------------------------------------------------------------------ #
# Contract                                                             #
# ------------------------------------------------------------------ #

@router.get("/{name}/contract")
def get_contract(name: str):
    """GET /projects/{name}/contract — retrieve data contract."""
    return _handle(_pm.get_contract, name)


@router.put("/{name}/contract")
def set_contract(name: str, body: dict, request: Request):
    """PUT /projects/{name}/contract — replace data contract."""
    _handle(_pm.set_contract, name, body)
    _audit(request, "workspace.contract_updated", name, meta={"keys": sorted(body)})
    return {"ok": True}


# ------------------------------------------------------------------ #
# Spec                                                                 #
# ------------------------------------------------------------------ #

@router.get("/{name}/spec")
def get_spec(name: str):
    """GET /projects/{name}/spec — retrieve spec markdown."""
    markdown = _handle(_pm.get_spec, name)
    return {"markdown": markdown}


@router.put("/{name}/spec")
def set_spec(name: str, body: SetSpecBody, request: Request):
    """PUT /projects/{name}/spec — replace spec markdown."""
    _handle(_pm.set_spec, name, body.markdown)
    _audit(request, "workspace.spec_updated", name, meta={"chars": len(body.markdown)})
    return {"ok": True}


# ------------------------------------------------------------------ #
# Annotations                                                          #
# ------------------------------------------------------------------ #

@router.get("/{name}/annotations")
def get_annotations(name: str):
    """GET /projects/{name}/annotations — list all annotations."""
    return _handle(_pm.get_annotations, name)


@router.post("/{name}/annotations")
def add_annotations(name: str, body: list[dict]):
    """POST /projects/{name}/annotations — add/overwrite annotations."""
    _handle(_pm.add_annotations, name, body)
    return {"ok": True}


@router.get("/{name}/annotations/export")
def export_annotations(
    name: str,
    format: str = Query("jsonl", description="Export format: jsonl or csv"),
):
    """GET /projects/{name}/annotations/export — export annotations as JSONL or CSV."""
    content = _handle(_pm.export_annotations, name, format)
    media_type = "text/csv" if format == "csv" else "application/x-ndjson"
    return PlainTextResponse(content=content, media_type=media_type)


@router.post("/{name}/annotations/import")
def import_annotations(name: str, body: ImportAnnotationsBody):
    """POST /projects/{name}/annotations/import — import annotations from JSONL or CSV."""
    return _handle(_pm.import_annotations, name, body.content, body.format)


@router.get("/{name}/annotations/validate")
def validate_annotations(name: str):
    """GET /projects/{name}/annotations/validate — validate annotation coverage."""
    return _handle(_pm.validate_annotations, name)


@router.post("/{name}/annotations/bulk")
def bulk_annotate(name: str, body: BulkAnnotateBody):
    """POST /projects/{name}/annotations/bulk — assign a label to multiple paths."""
    _handle(_pm.bulk_annotate, name, body.paths, body.label)
    return {"ok": True}


# ------------------------------------------------------------------ #
# Curation                                                             #
# ------------------------------------------------------------------ #

@router.get("/{name}/curation")
def get_curation(name: str):
    """GET /projects/{name}/curation — list curation decisions."""
    return _handle(_pm.get_curation_decisions, name)


@router.post("/{name}/curation")
def add_curation(name: str, body: AddCurationDecisionBody):
    """POST /projects/{name}/curation — add a curation decision."""
    _handle(_pm.add_curation_decision, name, body.path, body.decision)
    return {"ok": True}


# ------------------------------------------------------------------ #
# Quality check                                                        #
# ------------------------------------------------------------------ #

@router.post("/{name}/quality-check")
def trigger_quality_check(name: str, body: QualityCheckBody):
    """POST /projects/{name}/quality-check — run quality checks on a version."""
    # Determine which version to check
    version = body.version
    if version is None:
        # Default to the latest version
        versions = _handle(_pm.list_versions, name)
        if not versions:
            raise HTTPException(
                status_code=422,
                detail="No versions found; specify a version in the request body",
            )
        version = versions[-1]["version"]

    # Validate name + version before any filesystem access (no ``../`` escape).
    from app.domain.quality_checker import validate_dataset_target

    bad = validate_dataset_target(_qc.BASE, name, str(version))
    if bad:
        raise HTTPException(status_code=422, detail=bad)

    contract = _handle(_pm.get_contract, name)
    try:
        findings = _qc.run(name, version, contract or None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"version": version, "findings": findings}


@router.get("/{name}/quality-check/{job_id}")
def get_quality_check_status(name: str, job_id: str):
    """GET /projects/{name}/quality-check/{job_id} — get quality check report.

    Stub: returns the persisted quality_report.json from the project directory.
    """
    project_dir = _handle(_pm._require_project, name)

    report_path = project_dir / "quality_report.json"
    if not report_path.exists():
        return {"job_id": job_id, "status": "not_found", "findings": []}

    try:
        with report_path.open("r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read quality report: {exc}")

    return {"job_id": job_id, "status": "completed", **report}


# ------------------------------------------------------------------ #
# Versions                                                             #
# ------------------------------------------------------------------ #

@router.get("/{name}/versions")
def list_versions(name: str):
    """GET /projects/{name}/versions — list all versions."""
    return _handle(_pm.list_versions, name)


@router.get("/{name}/versions/{version}/stats")
def get_version_stats(name: str, version: str):
    """GET /projects/{name}/versions/{version}/stats — compute dataset statistics."""
    return _handle(_pm.get_stats, name, version)


@router.get("/{name}/versions/{version}/lineage")
def get_version_lineage(name: str, version: str):
    """GET /projects/{name}/versions/{version}/lineage — get lineage metadata."""
    return _handle(_pm.get_lineage, name, version)


@router.post("/{name}/versions/{version}/restore")
def restore_version(name: str, version: str, request: Request):
    """POST /projects/{name}/versions/{version}/restore — copy a version into the project root.

    Legacy: the console no longer offers this (nothing reads the root
    "working area" and it can overwrite workspace files). Records
    ``workspace.version_restored``.
    """
    _handle(_pm.restore_version, name, version)
    _audit(
        request,
        "workspace.version_restored",
        f"{name}/{version}",
        resource_type="dataset_version",
        meta={"workspace": name, "version": version},
    )
    return {"ok": True, "restored": version}


@router.get("/{name}/versions/{version}/samples")
def list_samples(
    name: str,
    version: str,
    label: Optional[str] = Query(None),
    split: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """GET /projects/{name}/versions/{version}/samples — paginated sample list."""
    filters: dict[str, Any] = {}
    if label:
        filters["label"] = label
    if split:
        filters["split"] = split
    return _handle(_pm.list_samples, name, version, filters, page, page_size)


@router.get("/{name}/versions/{version}/random-samples")
def random_samples(
    name: str,
    version: str,
    n: int = Query(10, ge=1, le=1000),
    seed: Optional[int] = Query(None),
):
    """GET /projects/{name}/versions/{version}/random-samples — random sample selection."""
    return _handle(_pm.random_samples, name, version, n, seed)


@router.post("/{name}/versions/{version}/deduplicate")
def deduplicate(name: str, version: str, body: DeduplicateBody):
    """POST /projects/{name}/versions/{version}/deduplicate — find/remove duplicates."""
    return _handle(_pm.deduplicate, name, version, body.mode)


@router.post("/{name}/versions/{version}/dataset-card")
def generate_dataset_card(name: str, version: str):
    """POST /projects/{name}/versions/{version}/dataset-card — generate dataset card markdown."""
    card = _handle(_pm.generate_dataset_card, name, version)
    return {"markdown": card}


# ------------------------------------------------------------------ #
# Diff and lineage                                                     #
# ------------------------------------------------------------------ #

@router.get("/{name}/diff")
def diff_versions(
    name: str,
    version_a: str = Query(..., description="First version to compare"),
    version_b: str = Query(..., description="Second version to compare"),
):
    """GET /projects/{name}/diff — diff two versions."""
    return _handle(_pm.diff_versions, name, version_a, version_b)


@router.get("/{name}/lineage")
def get_latest_lineage(name: str):
    """GET /projects/{name}/lineage — get lineage for the latest version."""
    versions = _handle(_pm.list_versions, name)
    if not versions:
        raise HTTPException(status_code=404, detail="No versions found for this project")
    latest_version = versions[-1]["version"]
    return _handle(_pm.get_lineage, name, latest_version)


# ------------------------------------------------------------------ #
# Snapshots                                                            #
# ------------------------------------------------------------------ #

@router.post("/{name}/snapshots")
def create_snapshot(name: str, body: CreateSnapshotBody, request: Request):
    """POST /projects/{name}/snapshots — create a snapshot."""
    _handle(_pm.create_snapshot, name, body.snapshot_name)
    _audit(request, "workspace.snapshot_created", name, meta={"snapshot": body.snapshot_name})
    return {"ok": True, "snapshot_name": body.snapshot_name}


@router.get("/{name}/snapshots")
def list_snapshots(name: str):
    """GET /projects/{name}/snapshots — list all snapshots."""
    return _handle(_pm.list_snapshots, name)


@router.post("/{name}/snapshots/{snapshot_name}/restore")
def restore_snapshot(name: str, snapshot_name: str, request: Request):
    """POST /projects/{name}/snapshots/{snapshot_name}/restore — restore a snapshot."""
    _handle(_pm.restore_snapshot, name, snapshot_name)
    _audit(request, "workspace.snapshot_restored", name, meta={"snapshot": snapshot_name})
    return {"ok": True, "restored": snapshot_name}


# ------------------------------------------------------------------ #
# Export gate and quality report export                                #
# ------------------------------------------------------------------ #

@router.get("/{name}/export-gate")
def get_export_gate(name: str):
    """GET /projects/{name}/export-gate — check if dataset is safe to export.

    Returns {can_export: bool, blocking_issues: [...], reason: str}.
    """
    return _handle(_pm.get_export_gate, name)


@router.get("/{name}/quality-report/export")
def export_quality_report(
    name: str,
    format: str = Query("json", description="Export format: json or csv"),
):
    """GET /projects/{name}/quality-report/export — download quality report.

    Returns the quality_report.json as JSON or CSV.
    """
    content = _handle(_pm.export_quality_report, name, format)
    if format == "csv":
        return PlainTextResponse(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=quality_report.csv"},
        )
    return PlainTextResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=quality_report.json"},
    )


# ------------------------------------------------------------------ #
# Project-owned pipelines (Graph IR assets)                            #
# ------------------------------------------------------------------ #

@router.get("/{name}/pipelines", summary="List project pipelines")
def list_project_pipelines(name: str):
    """GET /projects/{name}/pipelines — Graph IR files under pipelines/."""
    from app.core.pipelines.pipeline_environments import enrich_pipeline_summary
    from app.core.pipelines.project_pipelines import list_pipelines

    project_dir = _handle(_pm._require_project, name)
    return [enrich_pipeline_summary(project_dir, row) for row in list_pipelines(project_dir)]


@router.get("/{name}/pipelines/{pipeline}/versions", summary="List pipeline versions")
def list_pipeline_versions(name: str, pipeline: str):
    from app.core.pipelines.pipeline_environments import list_versions

    project_dir = _handle(_pm._require_project, name)
    return {"pipeline": pipeline, "versions": list_versions(project_dir, pipeline)}


@router.get(
    "/{name}/pipelines/{pipeline}/versions/{version}",
    summary="Get a published pipeline version",
)
def get_pipeline_version(name: str, pipeline: str, version: str):
    from app.core.pipelines.pipeline_environments import get_version

    project_dir = _handle(_pm._require_project, name)
    return _handle(get_version, project_dir, pipeline, version)


@router.get(
    "/{name}/pipelines/{pipeline}/environments",
    summary="Get draft/staging/prod environment pointers",
)
def get_pipeline_environments(name: str, pipeline: str):
    from app.core.pipelines.pipeline_environments import get_environments

    project_dir = _handle(_pm._require_project, name)
    return get_environments(project_dir, pipeline)


class PipelinePublishBody(BaseModel):
    message: Optional[str] = None
    set_env: Optional[str] = Field(
        None, description="Optional: staging (immediate) or prod (pending approval)"
    )


class PipelinePromoteBody(BaseModel):
    to_env: str = Field(..., description="staging or prod")
    version: Optional[str] = None
    from_env: Optional[str] = Field(None, description="e.g. staging → prod")
    approve: bool = Field(
        False,
        description="Required true to point prod (creates pending_prod when false)",
    )


class PipelineRollbackBody(BaseModel):
    version: str


@router.post("/{name}/pipelines/{pipeline}/publish", summary="Publish draft → version")
def publish_pipeline_version(
    name: str, pipeline: str, request: Request, body: PipelinePublishBody = PipelinePublishBody()
):
    from app.core.pipelines.pipeline_environments import publish_version

    project_dir = _handle(_pm._require_project, name)
    try:
        return publish_version(
            project_dir,
            pipeline,
            project_name=name,
            message=body.message,
            set_env=body.set_env,
            actor=resolve_actor(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{name}/pipelines/{pipeline}/promote", summary="Promote version to env")
def promote_pipeline_env(
    name: str, pipeline: str, request: Request, body: PipelinePromoteBody
):
    from app.core.pipelines.pipeline_environments import promote_environment

    project_dir = _handle(_pm._require_project, name)
    try:
        return promote_environment(
            project_dir,
            pipeline,
            to_env=body.to_env,
            version=body.version,
            from_env=body.from_env,
            approve=body.approve,
            actor=resolve_actor(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{name}/pipelines/{pipeline}/rollback",
    summary="Copy a version back onto draft head",
)
def rollback_pipeline_draft(
    name: str, pipeline: str, request: Request, body: PipelineRollbackBody
):
    from app.core.pipelines.pipeline_environments import rollback_draft_to_version

    project_dir = _handle(_pm._require_project, name)
    try:
        graph = rollback_draft_to_version(
            project_dir, pipeline, body.version, project_name=name
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="pipeline.rollback",
            resource_type="pipeline",
            resource_id=f"{name}/{pipeline}@{body.version}",
            meta={},
        )
    except Exception:
        pass
    return {"pipeline": pipeline, "version": body.version, "graph": graph}


@router.get("/{name}/pipelines/{pipeline}", summary="Get a project pipeline")
def get_project_pipeline(
    name: str,
    pipeline: str,
    env: Optional[str] = Query(
        None, description="draft (default), staging, or prod"
    ),
):
    """GET /projects/{name}/pipelines/{pipeline} — draft head, or env pointer."""
    from app.core.pipelines.pipeline_environments import get_environment_graph
    from app.core.pipelines.project_pipelines import get_pipeline

    project_dir = _handle(_pm._require_project, name)
    if env and env.strip().lower() != "draft":
        return _handle(get_environment_graph, project_dir, pipeline, env.strip().lower())
    return _handle(get_pipeline, project_dir, pipeline)


@router.put("/{name}/pipelines/{pipeline}", summary="Save a project pipeline")
def put_project_pipeline(
    name: str,
    pipeline: str,
    request: Request,
    payload: dict = Body(...),
):
    """PUT /projects/{name}/pipelines/{pipeline} — validate, stamp, write IR (draft).

    Supports optimistic concurrency via ``If-Match`` / body ``resource_version``
    (API-CONV-005). Mismatch → 412 (If-Match) or 409 ``version_conflict``.
    """
    from app.api.concurrency import (
        optional_resource_version_from_payload,
        resolve_expected_version,
        version_conflict_http,
    )
    from app.core.errors import VersionConflict
    from app.core.ir.secret_policy import InlineSecretError
    from app.core.pipelines.project_pipelines import put_pipeline

    project_dir = _handle(_pm._require_project, name)
    expected, via_if_match = resolve_expected_version(
        request, optional_resource_version_from_payload(payload)
    )
    try:
        result = put_pipeline(
            project_dir,
            pipeline,
            payload,
            project_name=name,
            expected_resource_version=expected,
            via_if_match=via_if_match,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InlineSecretError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except VersionConflict as exc:
        raise version_conflict_http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    from fastapi.responses import JSONResponse
    from app.api.concurrency import etag_value
    resp = JSONResponse(content=result)
    if result.get("resource_version") is not None:
        resp.headers["ETag"] = etag_value(result["resource_version"])
    return resp


@router.delete("/{name}/pipelines/{pipeline}", summary="Delete a project pipeline")
def delete_project_pipeline(name: str, pipeline: str, request: Request):
    """DELETE /projects/{name}/pipelines/{pipeline}.

    Removes the draft ``.graph.json``, version bundle (versions +
    environments), and webhook hook. Schedules targeting this pipeline are
    disabled and marked orphaned. Run history is kept.
    """
    from app.core.pipelines.project_pipelines import delete_pipeline
    from app.core.pipelines.schedules import disable_schedules_for_pipeline

    project_dir = _handle(_pm._require_project, name)
    summary = _handle(delete_pipeline, project_dir, pipeline)
    orphaned = []
    try:
        orphaned = disable_schedules_for_pipeline(name, pipeline) or []
    except Exception as exc:  # pipeline is already deleted; surface in logs
        import logging

        logging.getLogger(__name__).warning(
            "delete pipeline %s/%s: could not orphan schedules: %s", name, pipeline, exc
        )
        orphaned = []
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="pipeline.deleted",
            resource_type="pipeline",
            resource_id=f"{name}/{pipeline}",
            meta={
                "removed": summary,
                "schedules_orphaned": len(orphaned),
            },
        )
    except Exception:
        pass
    return {
        "deleted": True,
        "name": pipeline,
        "removed": summary,
        "schedules_orphaned": len(orphaned),
    }
