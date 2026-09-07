# app/api/routers/experiments.py
"""
Bounded Context:  REST API Layer
Responsibility:   MLflow-shaped experiment list / detail / compare endpoints.
Owns:             GET /experiments, GET /experiments/compare, GET /experiments/{name}.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain aggregation logic — delegate to app.core.experiments.
Dependencies:     fastapi, app.core.experiments.
Reason To Change: Experiment board response schema changes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("", summary="List experiments with runs")
def list_experiments_endpoint():
    """Aggregate experiments from run dirs (experiment.json or meta+metrics)."""
    from app.core.experiments import list_experiments

    return list_experiments()


@router.get("/compare", summary="Compare selected runs")
def compare_experiments(
    run_ids: str = Query(
        ...,
        description="Comma-separated run_ids (2–5 recommended) for side-by-side compare",
    ),
):
    """Return aligned param/metric keys plus per-run rows for a comparison table."""
    from app.core.experiments import compare_runs

    ids = [part.strip() for part in run_ids.split(",") if part.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Provide at least one run_id")
    if len(ids) > 20:
        raise HTTPException(status_code=400, detail="Too many run_ids (max 20)")
    return compare_runs(ids)


@router.get("/{name}", summary="Get one experiment by name")
def get_experiment_endpoint(name: str):
    """Return a single experiment block ``{experiment_name, runs}``."""
    from app.core.experiments import get_experiment

    block = get_experiment(name)
    if block is None:
        raise HTTPException(status_code=404, detail=f"Experiment not found: {name}")
    return block
