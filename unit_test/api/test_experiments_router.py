"""API tests for /api/v1/experiments."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def test_list_experiments_empty(api_client, tmp_workspace: Path):
    with patch("app.core.config.runs_dir", return_value=tmp_workspace / "runs"):
        # list_experiments imports runs_dir inside; patch via collect path
        with patch("app.core.experiments.list_experiments", return_value=[]) as mock_list:
            resp = api_client.get("/api/v1/experiments")
    assert resp.status_code == 200
    assert resp.json() == []
    mock_list.assert_called_once()


def test_get_experiment_404(api_client):
    with patch("app.core.experiments.get_experiment", return_value=None):
        resp = api_client.get("/api/v1/experiments/nope")
    assert resp.status_code == 404


def test_get_experiment_ok(api_client):
    fake = {"experiment_name": "asr", "runs": [{"run_id": "r1", "metrics": {}}]}
    with patch("app.core.experiments.get_experiment", return_value=fake):
        resp = api_client.get("/api/v1/experiments/asr")
    assert resp.status_code == 200
    assert resp.json()["experiment_name"] == "asr"


def test_compare_requires_run_ids(api_client):
    resp = api_client.get("/api/v1/experiments/compare")
    assert resp.status_code == 422  # missing query


def test_compare_ok(api_client):
    fake = {
        "run_ids": ["a", "b"],
        "missing_run_ids": [],
        "param_keys": ["lr"],
        "metric_keys": ["accuracy"],
        "runs": [
            {"run_id": "a", "parameters": {"lr": 0.1}, "metrics": {"accuracy": 0.9}},
            {"run_id": "b", "parameters": {"lr": 0.2}, "metrics": {"accuracy": 0.8}},
        ],
    }
    with patch("app.core.experiments.compare_runs", return_value=fake) as mock_cmp:
        resp = api_client.get("/api/v1/experiments/compare?run_ids=a,b")
    assert resp.status_code == 200
    body = resp.json()
    assert body["param_keys"] == ["lr"]
    mock_cmp.assert_called_once()


def test_compare_does_not_collide_with_name_route(api_client):
    """Static /compare must not be captured by /{name}."""
    with patch("app.core.experiments.compare_runs", return_value={"run_ids": [], "missing_run_ids": [], "param_keys": [], "metric_keys": [], "runs": []}):
        resp = api_client.get("/api/v1/experiments/compare?run_ids=x")
    assert resp.status_code == 200
