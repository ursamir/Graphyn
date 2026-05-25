# app/api/routers/runs.py
"""Runs API — /api/v1/runs endpoints."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from app.core.config import runs_dir as _runs_dir

router = APIRouter(prefix="/runs", tags=["runs"])


def _get_runs_root() -> Path:
    """Return the runs directory, resolved from GRAPHYN_PROJECT_DIR."""
    return _runs_dir()


def _run_dir(run_id: str) -> Path:
    """Return the run directory path, raising 400/404 as appropriate.

    Validates run_id is alphanumeric (hyphens allowed) and that the resolved
    path stays within the runs root (SEC-7 fix — consistent with _safe_child()).
    """
    if not run_id.replace("-", "").isalnum() or not run_id.replace("-", ""):
        raise HTTPException(status_code=400, detail="Invalid run_id")
    runs_root = _get_runs_root().resolve()
    path = (runs_root / run_id).resolve()
    # Guard against path traversal — resolved path must stay inside runs root
    if not path.is_relative_to(runs_root):
        raise HTTPException(status_code=400, detail="Invalid run_id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return path


# ── List runs ─────────────────────────────────────────────────────────────────

@router.get("", summary="List all pipeline runs")
def list_runs(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
):
    """Return a summary list of pipeline runs, newest first, with pagination.

    Use limit/offset for large run histories. Default: first 50 runs.
    """
    runs_root = _get_runs_root()
    if not runs_root.exists():
        return []

    runs = []
    for entry in runs_root.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            continue
        runs.append(meta)

    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return runs[offset: offset + limit]


# ── Get run ───────────────────────────────────────────────────────────────────

@router.get("/{run_id}", summary="Get a run's config and logs")
def get_run(run_id: str):
    """Return the config YAML and log entries for a specific run."""
    run_path = _run_dir(run_id)

    config_yaml: str | None = None
    config_file = run_path / "config.yaml"
    if config_file.exists():
        config_yaml = config_file.read_text(encoding="utf-8")

    logs: list = []
    logs_file = run_path / "logs.json"
    if logs_file.exists():
        try:
            logs = json.loads(logs_file.read_text())
        except Exception:
            logs = []

    meta: dict = {}
    meta_file = run_path / "meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            pass

    return {"run_id": run_id, "meta": meta, "config_yaml": config_yaml, "logs": logs}


# ── Run status ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/status", summary="Get a run's status")
def get_run_status(run_id: str):
    """Return the status of a specific run."""
    run_path = _run_dir(run_id)
    meta_file = run_path / "meta.json"
    if not meta_file.exists():
        return {"status": "unknown"}
    try:
        meta = json.loads(meta_file.read_text())
    except Exception:
        return {"status": "unknown"}

    status = meta.get("status", "unknown")
    progress_pct: float | None = None
    current_node: str | None = None

    node_stats = meta.get("node_stats")
    num_nodes = meta.get("num_nodes")
    if node_stats and isinstance(node_stats, list):
        completed = len(node_stats)
        total = num_nodes if isinstance(num_nodes, int) and num_nodes > 0 else completed
        progress_pct = round(completed / total * 100, 1)
        last = node_stats[-1]
        if isinstance(last, dict):
            current_node = last.get("node_type")
    elif status == "completed":
        progress_pct = 100.0

    return {
        "status": status,
        "progress_pct": progress_pct,
        "current_node": current_node,
    }


# ── Checkpoints ───────────────────────────────────────────────────────────────

@router.get("/{run_id}/checkpoints", summary="List checkpoints for a run")
def list_checkpoints(run_id: str):
    """Return a list of checkpoint directory names for a run."""
    run_path = _run_dir(run_id)
    checkpoints_dir = run_path / "checkpoints"
    if not checkpoints_dir.exists():
        return []
    return [
        entry.name
        for entry in sorted(checkpoints_dir.iterdir())
        if entry.is_dir()
    ]


@router.get("/{run_id}/checkpoints/{node_id}", summary="Get a checkpoint manifest")
def get_checkpoint_manifest(run_id: str, node_id: str):
    """Return the manifest.json content for a specific checkpoint node."""
    run_path = _run_dir(run_id)
    checkpoints_dir = run_path / "checkpoints"
    if not checkpoints_dir.exists():
        raise HTTPException(status_code=404, detail="No checkpoints for this run")

    # Exact match first, then prefix match for backward compat
    checkpoint_dir: Path | None = None
    exact = checkpoints_dir / node_id
    if exact.is_dir():
        checkpoint_dir = exact
    else:
        for entry in checkpoints_dir.iterdir():
            if entry.is_dir() and entry.name.startswith(node_id):
                checkpoint_dir = entry
                break

    if checkpoint_dir is None:
        raise HTTPException(status_code=404, detail=f"Checkpoint '{node_id}' not found")

    manifest_path = checkpoint_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="manifest.json not found")

    try:
        return json.loads(manifest_path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read manifest: {exc}")


@router.get("/{run_id}/checkpoints/{node_id}/samples", summary="Get checkpoint samples")
def get_checkpoint_samples(
    run_id: str,
    node_id: str,
    n: int = Query(10, ge=1, le=100),
):
    """Return the first n sample entries from a checkpoint manifest."""
    manifest = get_checkpoint_manifest(run_id, node_id)
    samples = manifest.get("samples", [])
    if not isinstance(samples, list):
        samples = []
    return samples[:n]


# ── Artifacts ─────────────────────────────────────────────────────────────────

@router.get("/{run_id}/artifacts", summary="List artifacts for a run")
def list_run_artifacts(run_id: str):
    """Return all artifacts registered for a specific run."""
    _run_dir(run_id)  # raises 404 if run not found
    from app.core.artifact_store import ArtifactStore
    records = ArtifactStore().list(run_id=run_id)
    return [r.model_dump(mode="json") for r in records]


# ── Provenance ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/provenance", summary="Get provenance summary for a run")
def get_run_provenance(run_id: str):
    """Return a provenance summary including artifacts and provenance records for a run."""
    _run_dir(run_id)  # raises 404 if run not found
    from app.core.artifact_store import ArtifactStore
    from app.core.provenance import ProvenanceStore
    artifacts = ArtifactStore().list(run_id=run_id)
    provenance_records = ProvenanceStore().find_by_run(run_id)
    return {
        "run_id": run_id,
        "artifact_count": len(artifacts),
        "artifacts": [r.model_dump(mode="json") for r in artifacts],
        "provenance_records": [p.model_dump(mode="json") for p in provenance_records],
    }
