"""
FastAPI router for all /projects/* endpoints.

Wires ProjectManager methods to HTTP routes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

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


# ------------------------------------------------------------------ #
# Request / Response models                                            #
# ------------------------------------------------------------------ #

class CreateProjectBody(BaseModel):
    name: str


class RenameProjectBody(BaseModel):
    new_name: str


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


# ------------------------------------------------------------------ #
# Project lifecycle                                                    #
# ------------------------------------------------------------------ #

@router.get("")
def list_projects():
    """GET /projects — list all projects."""
    return _handle(_pm.list_all)


@router.post("")
def create_project(body: CreateProjectBody):
    """POST /projects — create a new project."""
    return _handle(_pm.create, body.name)


@router.patch("/{name}")
def rename_project(name: str, body: RenameProjectBody):
    """PATCH /projects/{name} — rename a project."""
    return _handle(_pm.rename, name, body.new_name)


@router.delete("/{name}")
def delete_project(name: str, body: DeleteProjectBody):
    """DELETE /projects/{name} — delete a project (requires confirm == name)."""
    _handle(_pm.delete, name, body.confirm)
    return {"deleted": name}


@router.patch("/{name}/status")
def set_project_status(name: str, body: SetStatusBody):
    """PATCH /projects/{name}/status — update project status."""
    return _handle(_pm.set_status, name, body.status)


@router.post("/{name}/clone")
def clone_project(name: str, body: CloneProjectBody):
    """POST /projects/{name}/clone — clone a project."""
    return _handle(_pm.clone, name, body.new_name)


# ------------------------------------------------------------------ #
# Taxonomy                                                             #
# ------------------------------------------------------------------ #

@router.get("/{name}/taxonomy")
def get_taxonomy(name: str):
    """GET /projects/{name}/taxonomy — retrieve taxonomy tree."""
    return _handle(_pm.get_taxonomy, name)


@router.put("/{name}/taxonomy")
def set_taxonomy(name: str, body: list[dict]):
    """PUT /projects/{name}/taxonomy — replace taxonomy tree."""
    _handle(_pm.set_taxonomy, name, body)
    return {"ok": True}


# ------------------------------------------------------------------ #
# Contract                                                             #
# ------------------------------------------------------------------ #

@router.get("/{name}/contract")
def get_contract(name: str):
    """GET /projects/{name}/contract — retrieve data contract."""
    return _handle(_pm.get_contract, name)


@router.put("/{name}/contract")
def set_contract(name: str, body: dict):
    """PUT /projects/{name}/contract — replace data contract."""
    _handle(_pm.set_contract, name, body)
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
def set_spec(name: str, body: SetSpecBody):
    """PUT /projects/{name}/spec — replace spec markdown."""
    _handle(_pm.set_spec, name, body.markdown)
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
    project_dir = ProjectManager.BASE / name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

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
def restore_version(name: str, version: str):
    """POST /projects/{name}/versions/{version}/restore — restore a version."""
    _handle(_pm.restore_version, name, version)
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
def create_snapshot(name: str, body: CreateSnapshotBody):
    """POST /projects/{name}/snapshots — create a snapshot."""
    _handle(_pm.create_snapshot, name, body.snapshot_name)
    return {"ok": True, "snapshot_name": body.snapshot_name}


@router.get("/{name}/snapshots")
def list_snapshots(name: str):
    """GET /projects/{name}/snapshots — list all snapshots."""
    return _handle(_pm.list_snapshots, name)


@router.post("/{name}/snapshots/{snapshot_name}/restore")
def restore_snapshot(name: str, snapshot_name: str):
    """POST /projects/{name}/snapshots/{snapshot_name}/restore — restore a snapshot."""
    _handle(_pm.restore_snapshot, name, snapshot_name)
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
