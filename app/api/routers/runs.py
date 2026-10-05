# app/api/routers/runs.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for run history, status, checkpoints,
                  artifacts, and provenance.
Owns:             Route definitions for GET /runs, GET /runs/{run_id}
                  (logs with a consistent ``error`` field + ``node_order``;
                  rows/detail carry ``display_name``, ``summary``,
                  ``regression`` from app.core.runs.run_summary; ``metrics``
                  is the BEST path's for multi-path runs, plus
                  ``metrics_path`` / ``metrics_by_path``),
                  GET /runs/{run_id}/models (model files for Ship/register),
                  GET /runs/{run_id}/graph,
                  GET /runs/{run_id}/status,
                  GET /runs/{run_id}/checkpoints/**,
                  GET /runs/{run_id}/artifacts,
                  GET /runs/{run_id}/outputs (?with_meta=1, ?node_id=&limit=&offset=),
                  GET /runs/{run_id}/outputs/zip (audited as run.outputs_zip),
                  POST /runs/{run_id}/promote,
                  DELETE /runs/{run_id} (archive; ?purge=true + X-Confirm-Purge),
                  POST /runs/{run_id}/restore, GET|POST /runs/{run_id}/verify
                  (each call recorded in runs/<id>/verify.json + audit
                  ``run.verified``), GET /runs/{run_id}/verify/history,
                  GET /runs/compare/diff (2–5 runs; app.core.runs.run_diff),
                  POST /runs/{run_id}/replay; GET /runs/{run_id} adds
                  ``record`` (sealed prove.json), ``record_status``,
                  ``pipeline_drift``, ``last_verify`` (also on list rows). Every {run_id} accepts a unique
                  prefix >= 8 chars (app.api.run_ids; ambiguous → 409).
                  GET /runs/{run_id}/provenance.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain run persistence logic — delegate to RunJournal,
                  ArtifactStore, and ProvenanceStore.
Dependencies:     fastapi, app.core.runs.run_journal, app.core.runs.run_nodes,
                  app.core.runs.run_summary, app.core.runs.audit_record,
                  run_archive, run_replay, run_resolve, run_cleanup,
                  app.core.runs.verify_log, app.core.runs.run_diff,
                  app.api.actor (token-bound identity),
                  app.core.artifacts.artifact_store,
                  app.core.config, stdlib (json, pathlib, re).
Reason To Change: New run history endpoint added, or response schema changes.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response
from app.core.config import runs_dir as _runs_dir

# ASCII-only run_id: must start with alphanumeric, hyphens allowed in body.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")

router = APIRouter(prefix="/runs", tags=["runs"])


def _get_runs_root() -> Path:
    """Return the runs directory, resolved from GRAPHYN_PROJECT_DIR."""
    return _runs_dir()


def _run_dir(run_id: str) -> Path:
    """Return the run directory path, raising 400/404/409 as appropriate.

    Accepts the full run id or a unique prefix of >= 8 characters
    (``app.api.run_ids`` → ``app.core.runs.run_resolve``): unknown → 404
    ``run_not_found``, ambiguous prefix → 409 ``run_id_ambiguous`` (with the
    candidate ids), invalid → 400. The resolved path must stay within the
    runs root (SEC-7). Callers use ``path.name`` as the canonical full id.
    """
    from app.api.run_ids import run_dir_http

    return run_dir_http(run_id, runs_root=_get_runs_root())


def _load_meta(run_path: Path) -> dict:
    meta_file = run_path / "meta.json"
    if not meta_file.exists():
        return {}
    try:
        data = json.loads(meta_file.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _enrich_run_summary(meta: dict, run_path: Path) -> dict:
    from app.core.runs.run_status import normalize_status
    from app.core.paths.workspace_paths import (
        artifact_fs_path,
        artifact_layout,
        artifact_slug,
        read_metrics_json,
        read_metrics_tree,
        slug_from_artifacts_posix,
    )
    from app.core.runs.run_project import infer_project_from_graph_file, normalize_project_name, normalize_version_tag

    out = dict(meta)
    if "status" in out:
        out["status"] = normalize_status(out.get("status"))
        # G5: a running run blocked on a human approval gate is shown as
        # awaiting_approval (durable meta status stays "running").
        from app.core.runs.gates import awaiting_approval_overlay

        out.update(awaiting_approval_overlay(run_path, out["status"]))
    run_id = str(out.get("run_id") or run_path.name)
    need_graph_name = not (
        isinstance(out.get("graph_name"), str) and str(out.get("graph_name")).strip()
    )
    need_project = not normalize_project_name(out.get("project"))
    need_version = not normalize_version_tag(out.get("version_tag"))
    inferred = None
    graph = None
    if need_graph_name or need_project or need_version:
        inferred = infer_project_from_graph_file(run_path)
        if need_project and inferred.get("project"):
            out["project"] = inferred["project"]
        if need_version and inferred.get("version_tag"):
            out["version_tag"] = inferred["version_tag"]
        if need_graph_name:
            try:
                from app.core.runs.run_outputs import load_run_graph

                graph = load_run_graph(run_path)
                gmeta = graph.get("metadata") if isinstance(graph, dict) else None
                if isinstance(gmeta, dict) and gmeta.get("name"):
                    out["graph_name"] = str(gmeta["name"]).strip()
            except Exception:
                pass
    slug = None
    artifacts = out.get("artifacts_dir")
    if isinstance(artifacts, str) and artifacts.strip():
        slug = slug_from_artifacts_posix(artifacts)
    if not slug:
        name = out.get("graph_name")
        if isinstance(name, str) and name.strip():
            slug = artifact_slug(name)
    if slug and not artifacts:
        out["artifacts_dir"] = artifact_layout(slug, run_id)["run_dir"]
    if not isinstance(out.get("metrics"), dict):
        metrics = None
        art = out.get("artifacts_dir")
        if isinstance(art, str) and art.strip():
            metrics = read_metrics_tree(artifact_fs_path(art))
        if metrics is None:
            metrics = read_metrics_json(run_path)
        if metrics:
            out["metrics"] = metrics
    return out


def _run_slug_and_artifacts(run_id: str, run_path: Path, meta: dict) -> tuple[str | None, str | None]:
    from app.core.paths.workspace_paths import artifact_layout, artifact_slug, slug_from_artifacts_posix
    from app.core.runs.run_outputs import load_run_graph

    artifacts = meta.get("artifacts_dir") if isinstance(meta.get("artifacts_dir"), str) else None
    slug = slug_from_artifacts_posix(artifacts) if artifacts else None
    if not slug:
        name = meta.get("graph_name")
        if isinstance(name, str) and name.strip():
            slug = artifact_slug(name)
    if not slug:
        graph = load_run_graph(run_path)
        gmeta = graph.get("metadata") if isinstance(graph, dict) else None
        if isinstance(gmeta, dict) and gmeta.get("name"):
            slug = artifact_slug(str(gmeta["name"]))
    if slug and not artifacts:
        artifacts = artifact_layout(slug, run_id)["run_dir"]
    return slug, artifacts


# ── List runs ─────────────────────────────────────────────────────────────────

@router.get("", summary="List all pipeline runs")
def list_runs(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
    project: str | None = Query(
        None,
        description="Hard filter: only runs whose meta.project (or inferred graph stamp) equals this name",
    ),
    include_archived: bool = Query(
        False, description="Include archived runs (hidden by default; rows carry archived=true)"
    ),
):
    """Return a summary list of pipeline runs, newest first, with pagination.

    Use limit/offset for large run histories. Default: first 50 runs.
    When ``project`` is set, return only runs scoped to that project (Phase 2).
    """
    from app.api.store_guard import ensure_store_readable
    from app.core.runs.run_listing import list_runs as _list_runs

    ensure_store_readable()
    # Shared lister (app.core.runs.run_listing): created_at desc + run_id tiebreak,
    # per-entry error isolation — same order as MCP list_runs / CLI runs list.
    page = _list_runs(
        _get_runs_root(), limit=limit, offset=offset, project=project,
        include_archived=include_archived,
    )
    # No per-row regression on the list — detail GET attaches it.
    return [
        _with_results(_enrich_run_summary(meta, entry), entry, include_regression=False)
        for entry, meta in page.rows
    ]


@router.get("/compare/diff", summary="What changed between 2–5 runs")
def compare_diff(
    ids: str = Query(..., description="Comma-separated run ids (full or unique prefix >= 8), 2–5"),
    all: bool = Query(False, description="Include equal rows (default: differences only)"),
):
    """Settings / data / code / environment / metrics diff of the given runs.

    Uses each run's logical graph snapshot and sealed record (prove.json).
    Every section row carries per-run ``values`` in ``runs`` order. See
    docs/API_REFERENCE.md for the response shape.
    """
    from app.api.run_ids import run_dir_http
    from app.core.runs.run_diff import MAX_RUNS, MIN_RUNS, diff_runs

    raw = [x.strip() for x in (ids or "").split(",") if x.strip()]
    dirs: list[Path] = []
    for rid in raw:
        path = run_dir_http(rid, runs_root=_get_runs_root())
        if path not in dirs:
            dirs.append(path)
    if not (MIN_RUNS <= len(dirs) <= MAX_RUNS):
        raise HTTPException(
            status_code=422,
            detail={"code": "bad_run_count", "message": f"Pass {MIN_RUNS}-{MAX_RUNS} distinct run ids", "count": len(dirs)},
        )
    return diff_runs(dirs, include_all=bool(all))


def _with_results(row: dict, run_path: Path, *, include_regression: bool = True) -> dict:
    """Attach ``display_name`` / ``summary`` / ``regression`` (cached, best-effort).

    List views pass ``include_regression=False`` — sibling scans are O(n) per row.
    """
    from app.core.runs.run_summary import run_summary_fields

    run_id = str(row.get("run_id") or run_path.name)
    try:
        fields = run_summary_fields(run_id, run_path, row, include_regression=include_regression)
    except Exception:
        fields = {"display_name": row.get("graph_name") or run_id, "summary": None, "regression": None}
    out = dict(row)
    out.update(fields)
    try:
        from app.core.runs.verify_log import last_verify

        out["last_verify"] = last_verify(run_path)
    except Exception:
        out["last_verify"] = None
    try:
        from app.core.runs.run_summary import apply_headline_metrics

        # Run-level ``metrics`` = best path's (same pick as the results banner).
        out = apply_headline_metrics(out, fields.get("summary"))
    except Exception:
        pass
    return out


def _pipeline_drift(run_path: Path, meta: dict, record: dict | None) -> dict | None:
    """Current saved pipeline (same name/env) vs the run's graph hash (best-effort)."""
    try:
        from app.core.runs.audit_record import _semantic_hash, logical_graph_for_run, pipeline_drift

        ref = (record or {}).get("pipeline_version") if isinstance(record, dict) else None
        if not isinstance(ref, dict):
            ref = meta.get("pipeline_ref") if isinstance(meta.get("pipeline_ref"), dict) else None
        if not ref:
            return None
        run_hash = str((record or {}).get("graph_hash") or meta.get("graph_hash") or "")
        logical = logical_graph_for_run(run_path)
        sem = _semantic_hash(logical) if isinstance(logical, dict) else None
        return pipeline_drift(ref, run_hash, sem)
    except Exception:
        return None


# ── Get run ───────────────────────────────────────────────────────────────────

@router.get("/{run_id}", summary="Get a run's config and logs")
def get_run(run_id: str):
    """Return the config YAML and log entries for a specific run."""
    from app.api.store_guard import ensure_store_readable

    ensure_store_readable()
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)

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

    meta: dict = _load_meta(run_path)
    meta = _with_results(_enrich_run_summary(meta, run_path), run_path)
    slug, artifacts_dir = _run_slug_and_artifacts(run_id, run_path, meta)
    is_latest = False
    if slug:
        from app.core.paths.workspace_paths import latest_run_id
        is_latest = latest_run_id(slug) == run_id
    if artifacts_dir:
        meta.setdefault("artifacts_dir", artifacts_dir)

    from app.core.runs.run_nodes import normalize_log_errors, run_node_order

    node_order: list[dict] = []
    try:
        from app.core.runs.run_outputs import load_run_graph

        node_order = run_node_order(load_run_graph(run_path), meta)
    except Exception:
        node_order = []

    from app.core.runs.audit_record import load_record

    record = load_record(run_path)
    from app.core.runs.verify_log import last_verify

    return {
        "run_id": run_id,
        "meta": meta,
        # Latest recorded verification (runs/<id>/verify.json) or null.
        "last_verify": last_verify(run_path),
        # Sealed audit record (prove.json); null until the run is terminal.
        "record": record,
        "record_status": "sealed" if record is not None else "pending",
        "pipeline_drift": _pipeline_drift(run_path, meta, record),
        "config_yaml": config_yaml,
        "logs": normalize_log_errors(logs),
        "is_latest": is_latest,
        "artifacts_dir": artifacts_dir,
        # Graph nodes in execution order (incl. nodes that never ran).
        "node_order": node_order,
        # UX results (also under meta.*): human title, per-path metrics +
        # models, best path, dataset used, regression vs best previous run.
        "display_name": meta.get("display_name"),
        "summary": meta.get("summary"),
        "regression": meta.get("regression"),
        "node_progress": meta.get("node_progress") if isinstance(meta.get("node_progress"), dict) else {},
    }


# ── Run models (Ship / register) ──────────────────────────────────────────────

@router.get("/{run_id}/models", summary="List model files produced by a run")
def list_run_models(run_id: str):
    """Model artifacts (keras / SavedModel / tflite / onnx / pt) of a run.

    Each row: ``{path, name, node_id, node_type, path_id, path_label, kind
    (trained|compiled_untrained|optimized), format, size_bytes, created_at,
    metrics, labels, labels_source, suggested_name}``. ``path`` is
    workspace-relative (``workspace/artifacts/...``) and can be passed to
    Ship / edge_optimizer / POST /models as-is.
    """
    from app.core.runs.run_summary import run_insights

    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
    meta = _enrich_run_summary(_load_meta(run_path), run_path)
    ins = run_insights(run_id, run_path, meta)
    summary = ins.get("summary") or {}
    return {
        "run_id": run_id,
        "display_name": ins.get("display_name"),
        "status": ins.get("status"),
        "best_path_id": summary.get("best_path_id"),
        "primary_metric": summary.get("primary_metric"),
        "models": ins.get("models") or [],
    }


@router.delete("/{run_id}", summary="Archive a run (default) or purge it (admin)")
def delete_run_endpoint(
    run_id: str,
    request: Request,
    purge: bool = Query(
        False,
        description="Hard delete (journal + artifacts). Requires header X-Confirm-Purge: <full run_id>.",
    ),
):
    """Archive by default — the run is hidden from ``GET /runs`` but its
    journal, sealed record and artifacts stay (``?include_archived=1`` shows
    it; ``POST /runs/{id}/restore`` un-archives). Audited as ``run.archive``.

    ``?purge=true`` hard-deletes the journal dir and
    ``artifacts/<slug>/runs/<run_id>`` (retargeting ``latest/``) and needs
    ``X-Confirm-Purge`` equal to the full run id (428 otherwise). Audited as
    ``run.purge`` with the run's ``record_hash``. Returns 409 when the run is
    pending / running / paused.
    """
    from app.api.actor import resolve_actor

    run_path = _run_dir(run_id)
    run_id = run_path.name
    actor = resolve_actor(request)
    if not purge:
        from app.core.runs.run_archive import RunActiveError, archive_run

        try:
            return archive_run(run_path, actor=actor)
        except RunActiveError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    confirm = (request.headers.get("x-confirm-purge") or "").strip()
    if confirm != run_id:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "confirm_required",
                "message": (
                    "Purge permanently deletes the run journal and artifacts. "
                    f"Send header X-Confirm-Purge: {run_id} to confirm."
                ),
            },
        )
    from app.core.runs.audit_record import load_record
    from app.core.runs.run_cleanup import RunInProgressError, delete_run

    record = load_record(run_path) or {}
    meta = _load_meta(run_path)
    try:
        result = delete_run(run_id, require_finished=True)
    except RunInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action="run.purge",
            resource_type="run",
            resource_id=run_id,
            meta={
                "record_hash": record.get("record_hash"),
                "graph_hash": record.get("graph_hash") or meta.get("graph_hash"),
                "graph_name": meta.get("graph_name"),
                "project": meta.get("project"),
                "status": meta.get("status"),
            },
        )
    except Exception:
        pass
    out = dict(result) if isinstance(result, dict) else {"result": result}
    out.update({"purged": True, "record_hash": record.get("record_hash")})
    return out


@router.post("/{run_id}/restore", summary="Un-archive a run")
def restore_run_endpoint(run_id: str, request: Request):
    """Remove the archive flag (audited as ``run.restore``)."""
    from app.api.actor import resolve_actor
    from app.core.runs.run_archive import restore_run

    run_path = _run_dir(run_id)
    return restore_run(run_path, actor=resolve_actor(request))


# ── Audit: verify / replay ────────────────────────────────────────────────────

@router.get("/{run_id}/verify", summary="Verify a run's sealed audit record")
@router.post("/{run_id}/verify", summary="Verify a run's sealed audit record (recorded)")
def verify_run_endpoint(run_id: str, request: Request):
    """Re-hash the graph snapshot, external inputs (current content), stored
    output folders, the record hash and its position in the project chain.

    ``status``: ``pass`` | ``changed`` (inputs/outputs differ now) | ``fail``
    (tamper / hash mismatch) | ``unsealed`` (no prove.json yet). Per-check
    rows: ``{check, status, expected, actual, target?, node_id?, details?}``.

    Every call (GET or POST) is recorded: appended to ``runs/<id>/verify.json``
    and audited as ``run.verified`` with the caller's token-bound actor. Added
    fields: ``checked_at``, ``actor``, ``actor_verified``, ``claimed_actor``,
    ``summary`` ``{passed, total, failed, changed, missing, skipped}``,
    ``history_count``. The sealed record itself is never modified.
    """
    from app.api.actor import resolve_identity
    from app.core.runs.audit_record import verify_run
    from app.core.runs.verify_log import record_verification

    run_path = _run_dir(run_id)
    result = verify_run(run_path, meta=_load_meta(run_path))
    ident = resolve_identity(request)
    entry = record_verification(
        run_path,
        result,
        actor=ident["actor"],
        actor_verified=bool(ident["actor_verified"]),
        claimed_actor=ident.get("claimed_actor"),
    )
    out = dict(result)
    out.update({
        "checked_at": entry["checked_at"],
        "actor": entry["actor"],
        "actor_verified": entry["actor_verified"],
        "claimed_actor": entry["claimed_actor"],
        "summary": entry["summary"],
        "history_count": entry.get("history_count"),
    })
    return out


@router.get("/{run_id}/verify/history", summary="Past verifications of a run")
def verify_history_endpoint(run_id: str, limit: int = Query(50, ge=1, le=200)):
    """Newest-first verification history from ``runs/<id>/verify.json``."""
    from app.core.runs.verify_log import load_verify_history

    run_path = _run_dir(run_id)
    hist = load_verify_history(run_path)
    return {"run_id": run_path.name, "total": len(hist), "history": list(reversed(hist))[:limit]}


@router.post("/{run_id}/replay", summary="Replay a run from its stored graph")
def replay_run_endpoint(run_id: str, request: Request, body: dict | None = Body(None)):
    """Start a new run from the run's logical graph snapshot (same seed/config).

    Body: ``{"check_inputs": false, "force": false}``. With ``check_inputs``
    the replay is refused (409 ``inputs_changed`` + per-input diff) when a
    recorded external input hash changed, unless ``force``. The new run's
    meta / record carry ``replay_of`` and ``trigger: "replay"``; audited as
    ``run.replay``.
    """
    from app.api.actor import resolve_actor
    from app.core.runs.run_replay import (
        InputsChanged,
        ReplayGraphMissing,
        ReplayInputsUnavailable,
        start_replay,
    )

    payload = body if isinstance(body, dict) else {}
    run_path = _run_dir(run_id)
    try:
        return start_replay(
            run_path,
            actor=resolve_actor(request),
            check_inputs=bool(payload.get("check_inputs")),
            force=bool(payload.get("force")),
        )
    except InputsChanged as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "inputs_changed", "message": str(exc), "changes": exc.changes},
        )
    except ReplayGraphMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ReplayInputsUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "replay_inputs_unavailable", "message": str(exc)})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Replay failed: {exc}")


# ── Run graph IR ──────────────────────────────────────────────────────────────

@router.get("/{run_id}/graph", summary="Get the Graph IR used for a run")
def get_run_graph(run_id: str):
    """Return the Graph IR JSON stored in the run journal (``graph.json``).

    Same journal path used by artifact replay and run outputs. Returns the
    raw Graph IR document for Builder / Open-in-Builder deep links.
    """
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
    graph_path = run_path / "graph.json"
    if not graph_path.is_file():
        raise HTTPException(status_code=404, detail="graph.json not found for run")
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to load graph.json: {exc}",
        )
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Invalid graph.json")
    return data


# ── Run status ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/status", summary="Get a run's status")
def get_run_status(run_id: str):
    """Return the status of a specific run."""
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
    meta_file = run_path / "meta.json"
    if not meta_file.exists():
        return {"status": "unknown"}
    try:
        meta = json.loads(meta_file.read_text())
    except Exception:
        return {"status": "unknown"}

    from app.core.runs.run_status import normalize_status

    status = normalize_status(meta.get("status", "unknown"))
    progress_pct: float | None = None
    current_node: str | None = None

    node_stats = meta.get("node_stats")
    num_nodes = meta.get("num_nodes")
    if node_stats and isinstance(node_stats, list) and isinstance(num_nodes, int) and num_nodes > 0:
        completed = len(node_stats)
        progress_pct = round(completed / num_nodes * 100, 1)
        last = node_stats[-1]
        if isinstance(last, dict):
            current_node = last.get("node_type")
    elif node_stats and isinstance(node_stats, list):
        # num_nodes absent or zero — cannot compute meaningful progress;
        # return None rather than silently reporting 100%.
        last = node_stats[-1]
        if isinstance(last, dict):
            current_node = last.get("node_type")
    elif status in ("completed", "succeeded"):
        progress_pct = 100.0

    node_progress = meta.get("node_progress")
    from app.core.runs.gates import awaiting_approval_overlay

    overlay = awaiting_approval_overlay(run_path, status)
    return {
        **overlay,
        "status": overlay.get("status", status),
        "progress_pct": progress_pct,
        "current_node": current_node,
        # Latest node_progress event per node_id (live training progress).
        "node_progress": node_progress if isinstance(node_progress, dict) else {},
    }


# ── Checkpoints ───────────────────────────────────────────────────────────────

@router.get("/{run_id}/checkpoints", summary="List checkpoints for a run")
def list_checkpoints(run_id: str):
    """Return a list of checkpoint directory names for a run."""
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
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
    run_id = run_path.name  # full id (prefix resolution)
    checkpoints_dir = run_path / "checkpoints"
    if not checkpoints_dir.exists():
        raise HTTPException(status_code=404, detail="No checkpoints for this run")

    # Exact match first, then prefix match for backward compat
    checkpoint_dir: Path | None = None
    exact = checkpoints_dir / node_id
    if exact.is_dir():
        checkpoint_dir = exact
    else:
        for entry in sorted(checkpoints_dir.iterdir()):
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


# ── Downloadable outputs ──────────────────────────────────────────────────────

@router.get("/{run_id}/outputs", summary="List downloadable output files for a run")
def list_run_outputs(
    run_id: str,
    response: Response,
    with_meta: bool = Query(
        False,
        description=(
            "Return {items, truncated, max_items, truncated_by_node, inputs_by_node} "
            "instead of a bare list; truncated_by_node maps node_id -> {shown, total}; "
            "inputs_by_node counts source-node input files that are not outputs."
        ),
    ),
    node_id: str | None = Query(
        None, description="Page every file of one node: {node_id, items, total, offset, limit, has_more}"
    ),
    limit: int = Query(200, ge=1, le=1000, description="Page size (node_id mode)"),
    offset: int = Query(0, ge=0, description="Page offset (node_id mode)"),
):
    """Return files from the run dir, artifact records, graph output_path, and legacy Example 6.

    Default response is a bare list (backwards compatible) with an
    ``X-Graphyn-Outputs-Truncated: true|false`` header. Large audio data dirs
    are summarized and the list is capped at 400 entries (run-level files,
    then models / metrics / small summaries, then bulk files, round-robin per
    node; ingest input files are not outputs); pass
    ``with_meta=1`` for per-node ``{shown, total}`` or ``node_id=`` to page.
    """
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
    from app.core.runs.run_outputs import (
        list_node_output_files,
        list_run_output_files_detail,
        list_run_outputs_truncated_hint,
    )

    if node_id:
        return list_node_output_files(run_id, run_path, node_id, limit=limit, offset=offset)
    if with_meta:
        return list_run_output_files_detail(run_id, run_path)
    entries, truncated = list_run_outputs_truncated_hint(run_id, run_path)
    response.headers["X-Graphyn-Outputs-Truncated"] = "true" if truncated else "false"
    return entries


@router.get("/{run_id}/outputs/zip", summary="Download run outputs as a zip")
def download_run_outputs_zip(run_id: str, request: Request):
    """Zip output files under ``<node_id>/<filename>`` (``run/`` when unattributed).

    Uses a higher prioritised file cap than the UI listing. Headers:
    ``X-Graphyn-Outputs-Zip-Truncated`` when the listing or byte budget omitted
    files; ``X-Graphyn-Outputs-Zip-Count`` is the number of members packed.
    """
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
    from app.core.runs.run_outputs import list_run_output_files_for_zip, pack_outputs_zip

    entries, list_capped = list_run_output_files_for_zip(run_id, run_path)
    payload, byte_capped, packed = pack_outputs_zip(entries)
    filename = f"{run_id}-outputs.zip"
    truncated = bool(list_capped or byte_capped)
    from app.api.download_audit import audit_bytes_download

    audit_bytes_download(
        request,
        action="run.outputs_zip",
        resource_type="run",
        resource_id=run_id,
        payload=payload,
        extra={"file": filename, "files": packed, "truncated": truncated},
    )
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Graphyn-Outputs-Zip-Truncated": "true" if truncated else "false",
            "X-Graphyn-Outputs-Zip-Count": str(packed),
        },
    )


@router.post("/{run_id}/promote", summary="Promote a run to an artifact alias")
def promote_run(run_id: str, request: Request, body: dict | None = Body(None)):
    """Point workspace/artifacts/<slug>/<alias> at this run (default alias=latest)."""
    from app.api.actor import resolve_actor
    from app.core.paths.workspace_paths import (
        artifact_fs_path,
        artifact_layout,
        publish_alias,
    )

    payload = body if isinstance(body, dict) else {}
    alias = str(payload.get("alias") or "latest").strip().lower() or "latest"

    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)
    meta = _enrich_run_summary(_load_meta(run_path), run_path)
    slug, artifacts_dir = _run_slug_and_artifacts(run_id, run_path, meta)
    if not slug:
        raise HTTPException(status_code=409, detail="Run has no artifact slug")
    layout = artifact_layout(slug, run_id)
    run_art = artifact_fs_path(layout["run_dir"])

    def _dir_has_file(root: Path) -> bool:
        """True when *root* contains any non-dot file (stops at the first hit)."""
        try:
            if not root.exists():
                return False
            for _dirpath, _dirnames, filenames in os.walk(root):
                if any(not name.startswith(".") for name in filenames):
                    return True
        except OSError:
            return False
        return False

    has_files = _dir_has_file(run_art)
    if not has_files and artifacts_dir:
        has_files = _dir_has_file(artifact_fs_path(str(artifacts_dir)))
    if not has_files:
        raise HTTPException(status_code=409, detail="Run has no artifacts to promote")
    try:
        pointer = publish_alias(slug, run_id, alias)
    except FileNotFoundError as exc:
        # publish_alias no longer creates a missing run artifact dir.
        raise HTTPException(status_code=404, detail=str(exc) or "Run artifacts not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="run.promote",
            resource_type="run",
            resource_id=run_id,
            meta={"slug": slug, "alias": alias, "path": pointer},
        )
    except Exception:
        pass
    return {"slug": slug, "run_id": run_id, "alias": alias, "path": pointer, "latest": pointer}


# ── Artifacts ─────────────────────────────────────────────────────────────────

@router.get("/{run_id}/artifacts", summary="List artifacts for a run")
def list_run_artifacts(run_id: str):
    """Return all artifacts registered for a specific run."""
    from app.api.store_guard import ensure_store_readable, raise_http_store_corrupt
    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.persist.store_integrity import StoreCorrupt

    ensure_store_readable()
    run_id = _run_dir(run_id).name  # 404 / unique-prefix resolution
    try:
        records = ArtifactStore().list(run_id=run_id)
    except StoreCorrupt as exc:
        raise_http_store_corrupt(exc=exc)
    return [r.model_dump(mode="json") for r in records]


# ── Provenance ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/provenance", summary="Get provenance summary for a run")
def get_run_provenance(run_id: str):
    """Return a provenance summary including artifacts and provenance records for a run."""
    run_id = _run_dir(run_id).name  # 404 / unique-prefix resolution
    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.artifacts.provenance import ProvenanceStore
    artifacts = ArtifactStore().list(run_id=run_id)
    provenance_records = ProvenanceStore().find_by_run(run_id)
    return {
        "run_id": run_id,
        "artifact_count": len(artifacts),
        "artifacts": [r.model_dump(mode="json") for r in artifacts],
        "provenance_records": [p.model_dump(mode="json") for p in provenance_records],
    }


@router.get("/{run_id}/debug-report", summary="Get consolidated run debug report")
def get_run_debug_report(run_id: str):
    """Return a compact operator-focused debug report for one run."""
    run_path = _run_dir(run_id)
    run_id = run_path.name  # full id (prefix resolution)

    status = get_run_status(run_id)
    checkpoints = list_checkpoints(run_id)

    logs_file = run_path / "logs.json"
    log_entries: list[dict] = []
    if logs_file.exists():
        try:
            parsed = json.loads(logs_file.read_text())
            if isinstance(parsed, list):
                log_entries = [e for e in parsed if isinstance(e, dict)]
        except Exception:
            log_entries = []

    error_logs = [
        e
        for e in log_entries
        if str(e.get("level", "")).upper() in {"ERROR", "CRITICAL"}
        or "error" in str(e.get("message", "")).lower()
    ]

    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.artifacts.provenance import ProvenanceStore

    artifacts = ArtifactStore().list(run_id=run_id)
    provenance_records = ProvenanceStore().find_by_run(run_id)

    meta: dict = {}
    meta_file = run_path / "meta.json"
    if meta_file.exists():
        try:
            parsed = json.loads(meta_file.read_text())
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}

    node_stats = meta.get("node_stats") if isinstance(meta.get("node_stats"), list) else []

    return {
        "run_id": run_id,
        "status": status,
        "node_stats": node_stats,
        "nodes_executed": len(node_stats) if node_stats else len({a.node_id for a in artifacts if getattr(a, "node_id", None)}),
        "checkpoint_count": len(checkpoints),
        "checkpoints": checkpoints[:50],
        "artifact_count": len(artifacts),
        "provenance_count": len(provenance_records),
        "error_count": len(error_logs),
        "recent_errors": error_logs[-10:],
        "paths": {
            "run_dir": str(run_path),
            "meta_json": str(run_path / "meta.json"),
            "logs_json": str(logs_file),
            "checkpoints_dir": str(run_path / "checkpoints"),
        },
    }
