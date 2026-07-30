# unit_test/api/test_runs_router.py
"""Tests for /api/v1/runs router (Req 11)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


class TestListRuns:
    def test_returns_200_with_list(self, api_client, tmp_path, monkeypatch):
        """GET /api/v1/runs returns 200 with a list."""
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.get("/api/v1/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_empty_list_when_no_runs(self, api_client, tmp_path):
        """GET /api/v1/runs returns [] when runs directory is empty."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.get("/api/v1/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_runs_from_meta_json(self, api_client, tmp_path):
        """GET /api/v1/runs returns runs that have meta.json files."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run-abc123"
        run_dir.mkdir()
        meta = {"run_id": "run-abc123", "status": "completed", "created_at": "2024-01-01T00:00:00+00:00"}
        (run_dir / "meta.json").write_text(json.dumps(meta))
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.get("/api/v1/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["run_id"] == "run-abc123"


class TestGetRun:
    def test_nonexistent_run_returns_404(self, api_client, tmp_path):
        """GET /api/v1/runs/nonexistent returns 404."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.get("/api/v1/runs/nonexistent")
        assert resp.status_code == 404

    def test_existing_run_returns_200(self, api_client, tmp_path):
        """GET /api/v1/runs/{run_id} returns 200 for an existing run."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "abc123"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps({"run_id": "abc123", "status": "completed"}))
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.get("/api/v1/runs/abc123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "abc123"


class _DummyArtifactStore:
    def list(self, run_id=None):
        return []


class _DummyProvenanceStore:
    def find_by_run(self, run_id):
        return []


class TestRunDebugReport:
    def test_debug_report_returns_expected_fields(self, api_client, tmp_path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "abc123"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps({"run_id": "abc123", "status": "failed"}))
        (run_dir / "logs.json").write_text(
            json.dumps(
                [
                    {"level": "INFO", "message": "started"},
                    {"level": "ERROR", "message": "node failure"},
                ]
            )
        )
        (run_dir / "checkpoints").mkdir()

        with (
            patch("app.api.routers.runs._get_runs_root", return_value=runs_dir),
            patch("app.core.artifact_store.ArtifactStore", return_value=_DummyArtifactStore()),
            patch("app.core.provenance.ProvenanceStore", return_value=_DummyProvenanceStore()),
        ):
            resp = api_client.get("/api/v1/runs/abc123/debug-report")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["run_id"] == "abc123"
        assert "status" in payload
        assert "artifact_count" in payload
        assert payload["error_count"] >= 1
