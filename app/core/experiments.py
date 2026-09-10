# app/core/experiments.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Aggregate MLflow-shaped experiment boards from run dirs
                  (experiment.json and/or meta + metrics.json).
Owns:             list_experiments(), get_experiment(), compare_runs().
Public Surface:   Same helpers used by the /api/v1/experiments router.
Must NOT:         Import from app.api; require the mlflow package.
Dependencies:     runs_dir config, workspace_paths.read_metrics_json, stdlib.
Reason To Change: Experiment board schema evolves or new metric sources appear.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PREFERRED_METRIC_KEYS = ("accuracy", "loss", "val_accuracy", "val_loss", "f1", "precision", "recall")


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("experiments: skip corrupt %s (%s)", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _load_meta(run_path: Path) -> dict[str, Any]:
    return _safe_load_json(run_path / "meta.json") or {}


def _load_graph(run_path: Path) -> dict[str, Any]:
    return _safe_load_json(run_path / "graph.json") or {}


def _graph_display_name(graph: dict[str, Any]) -> str | None:
    meta = graph.get("metadata")
    if isinstance(meta, dict):
        name = meta.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _hydrate_metrics(meta: dict[str, Any], run_path: Path) -> dict[str, Any]:
    """Prefer meta.metrics; else metrics.json under artifacts or the run dir."""
    existing = meta.get("metrics")
    if isinstance(existing, dict) and existing:
        return dict(existing)

    from app.core.workspace_paths import (
        artifact_fs_path,
        artifact_layout,
        artifact_slug,
        read_metrics_json,
        slug_from_artifacts_posix,
    )

    metrics: dict[str, Any] | None = None
    artifacts = meta.get("artifacts_dir")
    if isinstance(artifacts, str) and artifacts.strip():
        metrics = read_metrics_json(artifact_fs_path(artifacts))
        if metrics is None:
            slug = slug_from_artifacts_posix(artifacts)
            run_id = str(meta.get("run_id") or run_path.name)
            if slug:
                try:
                    metrics = read_metrics_json(
                        artifact_fs_path(artifact_layout(slug, run_id)["run_dir"])
                    )
                except Exception:
                    metrics = None
    if metrics is None:
        name = meta.get("graph_name")
        run_id = str(meta.get("run_id") or run_path.name)
        if isinstance(name, str) and name.strip():
            try:
                metrics = read_metrics_json(
                    artifact_fs_path(artifact_layout(artifact_slug(name), run_id)["run_dir"])
                )
            except Exception:
                metrics = None
    if metrics is None:
        metrics = read_metrics_json(run_path)
    return dict(metrics) if isinstance(metrics, dict) else {}


def _run_row_from_dir(run_path: Path) -> tuple[str, dict[str, Any]] | None:
    """Return (experiment_name, run_summary) or None if nothing usable."""
    if not run_path.is_dir():
        return None

    meta = _load_meta(run_path)
    exp = _safe_load_json(run_path / "experiment.json")

    # Skip empty dirs with neither meta nor experiment.json
    if not meta and not exp:
        return None

    run_id = str(
        (exp or {}).get("run_id")
        or meta.get("run_id")
        or run_path.name
    )

    graph = _load_graph(run_path)
    graph_name_fallback = _graph_display_name(graph)
    graph_params = _as_dict(graph.get("parameters"))
    graph_tags = _as_list((graph.get("metadata") or {}).get("tags") if isinstance(graph.get("metadata"), dict) else [])

    if exp:
        experiment_name = str(exp.get("experiment_name") or "default").strip() or "default"
        parameters = _as_dict(exp.get("parameters"))
        metrics = _as_dict(exp.get("metrics"))
        if not metrics:
            metrics = _hydrate_metrics(meta, run_path)
        tags = _as_list(exp.get("tags"))
        created_at = (
            exp.get("timestamp")
            or meta.get("created_at")
            or meta.get("started_at")
            or None
        )
    else:
        experiment_name = str(meta.get("experiment_name") or "default").strip() or "default"
        parameters = _as_dict(meta.get("parameters") or meta.get("params"))
        metrics = _hydrate_metrics(meta, run_path)
        tags = _as_list(meta.get("tags"))
        created_at = meta.get("created_at") or meta.get("started_at") or None

    if not parameters and graph_params:
        parameters = graph_params
    if not tags and graph_tags:
        tags = graph_tags

    graph_name = (
        meta.get("graph_name")
        or (exp or {}).get("graph_name")
        or graph_name_fallback
        or None
    )
    if isinstance(graph_name, str):
        graph_name = graph_name.strip() or None

    row = {
        "run_id": run_id,
        "status": str(meta.get("status") or (exp or {}).get("status") or "unknown"),
        "created_at": created_at,
        "graph_name": graph_name,
        "parameters": parameters,
        "metrics": metrics,
        "tags": tags,
    }
    return experiment_name, row


def collect_run_rows(runs_root: Path | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Scan runs_dir and return (experiment_name, row) pairs. Skips corrupt files."""
    if runs_root is None:
        from app.core.config import runs_dir

        runs_root = runs_dir()
    if not runs_root.exists():
        return []

    rows: list[tuple[str, dict[str, Any]]] = []
    try:
        entries = sorted(
            (e for e in runs_root.iterdir() if e.is_dir()),
            key=lambda e: e.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        logger.warning("experiments: cannot list %s (%s)", runs_root, exc)
        return []

    for entry in entries:
        try:
            parsed = _run_row_from_dir(entry)
        except Exception as exc:
            logger.warning("experiments: skip %s (%s)", entry, exc)
            continue
        if parsed is None:
            continue
        rows.append(parsed)
    return rows


def list_experiments(runs_root: Path | None = None) -> list[dict[str, Any]]:
    """Return ``[{experiment_name, runs}, ...]`` sorted by name (default first)."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for name, row in collect_run_rows(runs_root):
        buckets.setdefault(name, []).append(row)

    def _sort_key(name: str) -> tuple[int, str]:
        return (0 if name == "default" else 1, name.lower())

    out: list[dict[str, Any]] = []
    for name in sorted(buckets.keys(), key=_sort_key):
        runs = buckets[name]
        # newest first within experiment
        runs.sort(
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )
        out.append({"experiment_name": name, "runs": runs})
    return out


def get_experiment(name: str, runs_root: Path | None = None) -> dict[str, Any] | None:
    target = (name or "").strip() or "default"
    for block in list_experiments(runs_root):
        if block["experiment_name"] == target:
            return block
    return None


def compare_runs(run_ids: list[str], runs_root: Path | None = None) -> dict[str, Any]:
    """Align param/metric keys across selected runs for a comparison table."""
    wanted = [r.strip() for r in run_ids if isinstance(r, str) and r.strip()]
    by_id: dict[str, dict[str, Any]] = {}
    for _name, row in collect_run_rows(runs_root):
        rid = str(row.get("run_id") or "")
        if rid and rid not in by_id:
            by_id[rid] = {**row, "experiment_name": _name}

    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for rid in wanted:
        row = by_id.get(rid)
        if row is None:
            missing.append(rid)
            continue
        selected.append(row)

    param_keys: set[str] = set()
    metric_keys: set[str] = set()
    for row in selected:
        param_keys.update(_as_dict(row.get("parameters")).keys())
        metric_keys.update(_as_dict(row.get("metrics")).keys())

    preferred = [k for k in PREFERRED_METRIC_KEYS if k in metric_keys]
    rest = sorted(k for k in metric_keys if k not in preferred)
    ordered_metrics = preferred + rest

    return {
        "run_ids": [r["run_id"] for r in selected],
        "missing_run_ids": missing,
        "param_keys": sorted(param_keys),
        "metric_keys": ordered_metrics,
        "runs": selected,
    }


def preferred_metric_columns(runs: list[dict[str, Any]]) -> list[str]:
    """Union of metric keys with preferred ones first (for UI tables)."""
    keys: set[str] = set()
    for row in runs:
        keys.update(_as_dict(row.get("metrics")).keys())
    preferred = [k for k in PREFERRED_METRIC_KEYS if k in keys]
    rest = sorted(k for k in keys if k not in preferred)
    return preferred + rest
