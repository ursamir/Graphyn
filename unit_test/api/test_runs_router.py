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


class TestPromoteRun:
    def test_promote_points_latest(self, api_client, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
        runs_dir = tmp_path / "runs"
        run_id = "prom1"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        art = tmp_path / "artifacts" / "speech-commands" / "runs" / run_id
        art.mkdir(parents=True)
        (art / "metrics.json").write_text('{"accuracy": 0.91}', encoding="utf-8")
        (run_dir / "meta.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "completed",
                    "graph_name": "speech_commands_e2e_train_ml",
                    "artifacts_dir": f"workspace/artifacts/speech-commands/runs/{run_id}",
                }
            )
        )
        (run_dir / "graph.json").write_text(
            json.dumps({"metadata": {"name": "speech_commands_e2e_train_ml"}, "nodes": []})
        )
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.post(f"/api/v1/runs/{run_id}/promote")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == run_id
        assert body["slug"] == "speech-commands"
        assert body["latest"] == "workspace/artifacts/speech-commands/latest"
        latest = tmp_path / "artifacts" / "speech-commands" / "latest"
        assert latest.is_symlink() or (latest / "latest.json").is_file() or (
            tmp_path / "artifacts" / "speech-commands" / "latest.json"
        ).is_file()
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            detail = api_client.get(f"/api/v1/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["is_latest"] is True
        assert detail.json()["artifacts_dir"] == f"workspace/artifacts/speech-commands/runs/{run_id}"

    def test_promote_missing_run_404(self, api_client, tmp_path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.post("/api/v1/runs/missing/promote")
        assert resp.status_code == 404

    def test_promote_no_artifacts_409(self, api_client, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
        runs_dir = tmp_path / "runs"
        run_id = "empty1"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(
            json.dumps({"run_id": run_id, "status": "completed", "graph_name": "demo"})
        )
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.post(f"/api/v1/runs/{run_id}/promote")
        assert resp.status_code == 409

    def test_list_includes_metrics(self, api_client, tmp_path, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
        runs_dir = tmp_path / "runs"
        run_id = "met1"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        art = tmp_path / "artifacts" / "speech-commands" / "runs" / run_id
        art.mkdir(parents=True)
        (art / "metrics.json").write_text('{"accuracy": 0.91, "loss": 0.2}', encoding="utf-8")
        (run_dir / "meta.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "completed",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "graph_name": "speech_commands_e2e_train_ml",
                    "artifacts_dir": f"workspace/artifacts/speech-commands/runs/{run_id}",
                }
            )
        )
        with patch("app.api.routers.runs._get_runs_root", return_value=runs_dir):
            resp = api_client.get("/api/v1/runs")
        assert resp.status_code == 200
        row = resp.json()[0]
        assert row["graph_name"] == "speech_commands_e2e_train_ml"
        assert row["status"] == "completed"
        assert row["created_at"]
        assert row["artifacts_dir"].endswith(f"runs/{run_id}")
        assert row["metrics"]["accuracy"] == 0.91
