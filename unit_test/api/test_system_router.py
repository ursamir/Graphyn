# unit_test/api/test_system_router.py
"""Tests for /api/v1/system router."""
from __future__ import annotations

from datetime import timezone


class TestHealthCheck:
    def test_returns_200_with_status_and_timestamp(self, api_client):
        """GET /api/v1/system/health returns 200 with status and timestamp fields."""
        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "timestamp" in body

    def test_status_is_ok(self, api_client):
        """GET /api/v1/system/health returns status == 'ok'."""
        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_timestamp_is_utc(self, api_client):
        """GET /api/v1/system/health timestamp is UTC (ends with +00:00 or Z)."""
        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        timestamp = resp.json()["timestamp"]
        assert isinstance(timestamp, str)
        # UTC ISO 8601 ends with +00:00 or Z
        assert timestamp.endswith("+00:00") or timestamp.endswith("Z"), (
            f"Timestamp '{timestamp}' is not UTC (expected +00:00 or Z suffix)"
        )

    def test_timestamp_is_parseable_iso8601(self, api_client):
        """GET /api/v1/system/health timestamp is a valid ISO 8601 datetime string."""
        from datetime import datetime

        resp = api_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        timestamp = resp.json()["timestamp"]
        # Should parse without error
        dt = datetime.fromisoformat(timestamp)
        # Should be timezone-aware
        assert dt.tzinfo is not None


import json
import os
import time
from pathlib import Path


def _make_finished_run(ws: Path, run_id: str, *, age_days: float = 0, status: str = "completed", graph_name: str = "demo"):
    run_dir = ws / "runs" / run_id
    run_dir.mkdir(parents=True)
    meta = {
        "run_id": run_id,
        "status": status,
        "graph_name": graph_name,
        "artifacts_dir": f"workspace/artifacts/demo/runs/{run_id}",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta))
    (run_dir / "journal.txt").write_text("log")
    art = ws / "artifacts" / "demo" / "runs" / run_id
    art.mkdir(parents=True)
    (art / "out.txt").write_text("artifact")
    if age_days:
        ts = time.time() - age_days * 86400
        os.utime(run_dir, (ts, ts))
        os.utime(art, (ts, ts))
    return run_dir, art


class TestCleanup:
    def test_days_7_deletes_only_old_run_and_artifacts(self, api_client, tmp_workspace):
        old_dir, old_art = _make_finished_run(tmp_workspace, "old-run", age_days=10)
        new_dir, new_art = _make_finished_run(tmp_workspace, "new-run", age_days=0)
        resp = api_client.post(
            "/api/v1/system/cleanup",
            json={
                "older_than_days": 7,
                "delete_cache": False,
                "delete_artifacts": True,
                "keep_latest": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["runs_deleted"] == 1
        assert body["artifacts_deleted"] >= 1
        assert body["runs_skipped_too_new"] >= 1
        assert body["older_than_days"] == 7
        assert not old_dir.exists()
        assert not old_art.exists()
        assert new_dir.exists()
        assert new_art.exists()

    def test_days_0_keeps_latest_and_running(self, api_client, tmp_workspace):
        keep_dir, keep_art = _make_finished_run(tmp_workspace, "keep-latest")
        gone_dir, gone_art = _make_finished_run(tmp_workspace, "gone-run")
        run_dir, run_art = _make_finished_run(tmp_workspace, "live-run", status="running")
        from app.core.workspace_paths import publish_latest

        publish_latest("demo", "keep-latest")
        resp = api_client.post(
            "/api/v1/system/cleanup",
            json={
                "older_than_days": 0,
                "delete_cache": False,
                "delete_artifacts": True,
                "keep_latest": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["runs_deleted"] == 1
        assert body["runs_skipped_latest"] >= 1
        assert body["runs_skipped_running"] >= 1
        assert keep_dir.exists()
        assert keep_art.exists()
        assert not gone_dir.exists()
        assert not gone_art.exists()
        assert run_dir.exists()
        assert run_art.exists()

    def test_zero_deleted_reports_skipped_counts(self, api_client, tmp_workspace):
        _make_finished_run(tmp_workspace, "fresh-run")
        resp = api_client.post(
            "/api/v1/system/cleanup",
            json={"older_than_days": 7, "delete_cache": False, "delete_artifacts": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["runs_deleted"] == 0
        assert body["runs_skipped_too_new"] >= 1
        assert "runs_skipped_latest" in body
        assert "runs_skipped_running" in body

    def test_rejects_negative_days(self, api_client, tmp_workspace):
        resp = api_client.post("/api/v1/system/cleanup", json={"older_than_days": -1})
        assert resp.status_code == 422
