"""F19 (F-15): /experiments/compare shows metrics recorded only per path."""
from __future__ import annotations

from app.core.runs.run_summary import apply_headline_metrics


def test_single_path_metrics_fill_empty_run_metrics():
    summary = {"paths": [{"path_id": "p0", "label": "trainer", "metrics": {"test_accuracy": 0.91}}],
               "best_path_id": "p0"}
    row = apply_headline_metrics({"run_id": "r1", "metrics": {}}, summary)
    assert row["metrics"] == {"test_accuracy": 0.91}
    assert row["metrics_by_path"][0]["best"] is True
    # existing finalize-time metrics are not overwritten for single-path runs
    row2 = apply_headline_metrics({"run_id": "r2", "metrics": {"loss": 0.2}}, summary)
    assert row2["metrics"] == {"loss": 0.2}


def test_compare_runs_uses_metrics_by_path(monkeypatch):
    import app.core.mlops.experiments as ex

    rows = [
        ("default", {"run_id": "a", "parameters": {"lr": 0.1}, "metrics": {},
                     "metrics_by_path": [{"path_id": "p0", "metrics": {"test_accuracy": 0.8}, "best": True}]}),
        ("default", {"run_id": "b", "parameters": {"lr": 0.2}, "metrics": {"test_accuracy": 0.9, "val_loss": 0.3}}),
    ]
    monkeypatch.setattr(ex, "collect_run_rows", lambda runs_root=None: rows)
    out = ex.compare_runs(["a", "b"])
    assert "test_accuracy" in out["metric_keys"] and "val_loss" in out["metric_keys"]
    assert out["runs"][0]["metrics"] == {"test_accuracy": 0.8}
