from __future__ import annotations

# app/api/routers/artifacts.py
"""Artifacts API — /api/v1/artifacts endpoints.

Provides artifact discovery, lineage, and replay endpoints.
All data access is delegated to ArtifactStore and ProvenanceStore.

Requirements: req-05 §1
"""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

# Regex for valid artifact IDs: alphanumeric, hyphens, underscores only
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Single shared executor for non-blocking replay.
# NEW-13: max_workers=1 means concurrent replay requests queue silently —
# only one replay runs at a time. Increase if concurrent replays are needed.
_replay_executor = ThreadPoolExecutor(max_workers=1)


def _validate_artifact_id(artifact_id: str) -> None:
    """Raise HTTP 400 if artifact_id contains invalid characters.

    Requirements: req-05 §2
    """
    if not _ARTIFACT_ID_RE.match(artifact_id):
        raise HTTPException(status_code=400, detail="Invalid artifact_id")


# ── GET /artifacts ─────────────────────────────────────────────────────────────

@router.get("", summary="List artifacts")
def list_artifacts(
    run_id: Optional[str] = Query(None, description="Filter by run ID"),
    node_type: Optional[str] = Query(None, description="Filter by node type"),
    artifact_type: Optional[str] = Query(None, description="Filter by artifact type"),
):
    """Return all artifacts matching the provided filters, sorted by created_at descending.

    Requirements: req-05 §1.3 (GET /api/v1/artifacts)
    """
    from app.core.artifact_store import ArtifactStore

    store = ArtifactStore()
    records = store.list(run_id=run_id, node_type=node_type, artifact_type=artifact_type)
    return [r.model_dump(mode="json") for r in records]


# ── GET /artifacts/{artifact_id} ───────────────────────────────────────────────

@router.get("/{artifact_id}", summary="Get an artifact by ID")
def get_artifact(artifact_id: str):
    """Return the ArtifactRecord for the given artifact_id.

    Returns HTTP 400 for invalid ID characters.
    Returns HTTP 404 if the artifact is not found.

    Requirements: req-05 §1.3 (GET /api/v1/artifacts/{artifact_id}), req-05 §2
    """
    _validate_artifact_id(artifact_id)

    from app.core.artifact_store import ArtifactNotFoundError, ArtifactStore

    store = ArtifactStore()
    try:
        record = store.get(artifact_id)
    except ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return record.model_dump(mode="json")


# ── GET /artifacts/{artifact_id}/lineage ───────────────────────────────────────

@router.get("/{artifact_id}/lineage", summary="Get artifact lineage tree")
def get_artifact_lineage(artifact_id: str):
    """Return the full upstream lineage tree rooted at artifact_id.

    Never returns HTTP 404 — missing provenance records are represented as
    error nodes in the tree (per req-02 §4).

    Requirements: req-05 §1.3 (GET /api/v1/artifacts/{artifact_id}/lineage)
    """
    _validate_artifact_id(artifact_id)

    from app.core.provenance import ProvenanceStore

    store = ProvenanceStore()
    return store.get_lineage(artifact_id)


# ── POST /artifacts/{artifact_id}/replay ──────────────────────────────────────

@router.post("/{artifact_id}/replay", summary="Replay the run that produced an artifact")
def replay_artifact(artifact_id: str):
    """Trigger an asynchronous replay of the run that produced artifact_id.

    Steps:
    1. Load provenance record to find the original run_id.
    2. Load workspace/runs/{run_id}/graph.json via load_ir_from_file().
    3. Create a new RunManager (new run_id).
    4. Submit run_pipeline_ir() to a ThreadPoolExecutor (non-blocking).
    5. Return {"run_id": new_run_id, "status": "started"}.

    Returns HTTP 404 if artifact_id is not found.
    Returns HTTP 422 if graph.json is missing for the original run.

    Requirements: req-05 §1.3 (POST /api/v1/artifacts/{artifact_id}/replay),
                  req-05 §4
    """
    _validate_artifact_id(artifact_id)

    import os

    from app.core.artifact_store import ArtifactNotFoundError, ArtifactStore
    from app.core.ir.loader import load_ir_from_file
    from app.core.run_journal import RunManager

    # Step 1: resolve artifact → provenance → run_id
    artifact_store = ArtifactStore()
    try:
        artifact_record = artifact_store.get(artifact_id)
    except ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")

    original_run_id = artifact_record.run_id

    # Step 2: locate and load graph.json for the original run
    from app.core.config import runs_dir as _runs_dir
    graph_path = _runs_dir() / original_run_id / "graph.json"
    if not graph_path.exists():
        raise HTTPException(
            status_code=422,
            detail="graph.json not found for original run",
        )

    try:
        graph = load_ir_from_file(str(graph_path))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to load graph.json: {exc}",
        )

    # Step 3: create a new RunManager (new run_id)
    new_run_mgr = RunManager()
    new_run_id = new_run_mgr.run_id

    # Step 4: submit replay via Pipeline.run_with_manager() (V1.md §3.1)
    from app.core.sdk import Pipeline, PipelineNode

    def _do_replay():
        try:
            nodes = [PipelineNode(n.node_type, dict(n.config)) for n in graph.nodes]
            replay_pipeline = Pipeline(
                nodes=nodes,
                seed=graph.metadata.seed,
                name=graph.metadata.name,
                description=graph.metadata.description,
            )
            replay_pipeline.run(run_manager=new_run_mgr)
        except Exception as exc:
            new_run_mgr.mark_failed(str(exc))

    _replay_executor.submit(_do_replay)

    # Step 5: return immediately
    return {"run_id": new_run_id, "status": "started"}
