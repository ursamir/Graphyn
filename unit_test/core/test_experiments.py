"""Unit tests for experiment aggregation (Pillar B — Experiments board)."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.experiments import (
    compare_runs,
    get_experiment,
    list_experiments,
    preferred_metric_columns,
)


def _write_run(
    runs: Path,
    run_id: str,
    *,
    meta: dict | None = None,
    experiment: dict | None = None,
    metrics_json: dict | None = None,
) -> Path:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if experiment is not None:
        (run_dir / "experiment.json").write_text(json.dumps(experiment), encoding="utf-8")
    if metrics_json is not None:
        (run_dir / "metrics.json").write_text(json.dumps(metrics_json), encoding="utf-8")
    return run_dir


def test_list_experiments_from_experiment_json(tmp_workspace: Path):
    runs = tmp_workspace / "runs"
    _write_run(
        runs,
        "run-exp-1",
        meta={
            "run_id": "run-exp-1",
            "status": "completed",
            "graph_name": "train_demo",
            "created_at": "2026-09-07T10:00:00+00:00",
        },
        experiment={
            "run_id": "run-exp-1",
            "experiment_name": "asr_tune",
            "timestamp": "2026-09-07T10:00:01+00:00",
            "parameters": {"lr": 0.001, "epochs": 3},
            "metrics": {"accuracy": 0.91, "loss": 0.2},
            "tags": ["gpu"],
        },
    )
    _write_run(
        runs,
        "run-exp-2",
        meta={
            "run_id": "run-exp-2",
            "status": "completed",
            "graph_name": "train_demo",
            "created_at": "2026-09-07T11:00:00+00:00",
        },
        experiment={
            "run_id": "run-exp-2",
            "experiment_name": "asr_tune",
            "parameters": {"lr": 0.01, "epochs": 3},
            "metrics": {"accuracy": 0.88, "loss": 0.25},
        },
    )

    blocks = list_experiments(runs)
    assert len(blocks) == 1
    assert blocks[0]["experiment_name"] == "asr_tune"
    assert len(blocks[0]["runs"]) == 2
    ids = {r["run_id"] for r in blocks[0]["runs"]}
    assert ids == {"run-exp-1", "run-exp-2"}
    row = next(r for r in blocks[0]["runs"] if r["run_id"] == "run-exp-1")
    assert row["parameters"]["lr"] == 0.001
    assert row["metrics"]["accuracy"] == 0.91
    assert row["graph_name"] == "train_demo"
    assert row["tags"] == ["gpu"]


def test_fallback_meta_and_metrics_json(tmp_workspace: Path):
    runs = tmp_workspace / "runs"
    _write_run(
        runs,
        "run-metrics-only",
        meta={
            "run_id": "run-metrics-only",
            "status": "failed",
            "graph_name": "eval_only",
            "created_at": "2026-09-06T00:00:00+00:00",
            "parameters": {"batch": 8},
        },
        metrics_json={"accuracy": 0.5, "val_accuracy": 0.45},
    )

    blocks = list_experiments(runs)
    assert len(blocks) == 1
    assert blocks[0]["experiment_name"] == "default"
    run = blocks[0]["runs"][0]
    assert run["run_id"] == "run-metrics-only"
    assert run["status"] == "failed"
    assert run["metrics"]["accuracy"] == 0.5
    assert run["metrics"]["val_accuracy"] == 0.45
    assert run["parameters"]["batch"] == 8


def test_skips_corrupt_experiment_json(tmp_workspace: Path):
    runs = tmp_workspace / "runs"
    run_dir = runs / "run-corrupt"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": "run-corrupt",
                "status": "completed",
                "created_at": "2026-09-07T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "experiment.json").write_text("{not-json", encoding="utf-8")
    (run_dir / "metrics.json").write_text(json.dumps({"loss": 1.2}), encoding="utf-8")

    blocks = list_experiments(runs)
    assert len(blocks) == 1
    assert blocks[0]["experiment_name"] == "default"
    assert blocks[0]["runs"][0]["metrics"]["loss"] == 1.2


def test_skips_empty_dir(tmp_workspace: Path):
    runs = tmp_workspace / "runs"
    (runs / "empty-run").mkdir(parents=True)
    assert list_experiments(runs) == []


def test_get_experiment_and_compare(tmp_workspace: Path):
    runs = tmp_workspace / "runs"
    _write_run(
        runs,
        "a",
        meta={"run_id": "a", "status": "completed", "created_at": "2026-09-07T01:00:00+00:00"},
        experiment={
            "run_id": "a",
            "experiment_name": "cmp",
            "parameters": {"lr": 0.1},
            "metrics": {"accuracy": 0.9, "loss": 0.1},
        },
    )
    _write_run(
        runs,
        "b",
        meta={"run_id": "b", "status": "completed", "created_at": "2026-09-07T02:00:00+00:00"},
        experiment={
            "run_id": "b",
            "experiment_name": "cmp",
            "parameters": {"lr": 0.2},
            "metrics": {"accuracy": 0.8, "f1": 0.7},
        },
    )

    block = get_experiment("cmp", runs)
    assert block is not None
    assert len(block["runs"]) == 2
    assert get_experiment("missing", runs) is None

    cmp = compare_runs(["a", "b", "missing-x"], runs)
    assert cmp["run_ids"] == ["a", "b"]
    assert cmp["missing_run_ids"] == ["missing-x"]
    assert "lr" in cmp["param_keys"]
    assert cmp["metric_keys"][0] == "accuracy"  # preferred first
    assert "f1" in cmp["metric_keys"]
    assert "loss" in cmp["metric_keys"]

    cols = preferred_metric_columns(cmp["runs"])
    assert cols[0] == "accuracy"


def test_empty_runs_dir(tmp_workspace: Path):
    assert list_experiments(tmp_workspace / "runs") == []
