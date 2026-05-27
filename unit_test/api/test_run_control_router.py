# unit_test/api/test_run_control_router.py
"""Tests for /api/v1/runs/{run_id}/pause|resume|cancel endpoints (Req 24 criteria 1–4)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_active_run():
    """Return a mock active run object."""
    run = MagicMock()
    run.pause = MagicMock()
    run.resume = MagicMock()
    run.cancel = MagicMock()
    return run


class TestPauseRun:
    def test_pause_active_run_returns_200(self, api_client):
        """POST /api/v1/runs/{run_id}/pause with active run returns 200 with paused status.

        Validates: Req 24 criteria 1
        """
        run = _make_active_run()
        with patch("app.api.routers.run_control.get_active_run", return_value=run):
            resp = api_client.post("/api/v1/runs/run-abc/pause")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "run-abc"
        assert body["status"] == "paused"

    def test_pause_inactive_run_returns_404(self, api_client, tmp_path):
        """POST /api/v1/runs/{run_id}/pause with no active run returns 404 with error.

        When the run directory exists (run completed) → "run_not_active".
        When the run directory does not exist → "run_not_found".

        Validates: Req 24 criteria 2
        """
        # Case 1: run directory exists → run completed, not active
        run_dir = tmp_path / "run-xyz"
        run_dir.mkdir()
        with patch("app.api.routers.run_control.get_active_run", return_value=None), \
             patch("app.api.routers.run_control._runs_dir", return_value=tmp_path):
            resp = api_client.post("/api/v1/runs/run-xyz/pause")
        assert resp.status_code == 404
        detail = resp.json().get("detail", resp.json())
        assert detail.get("error") == "run_not_active"

        # Case 2: run directory does not exist → run never existed
        with patch("app.api.routers.run_control.get_active_run", return_value=None), \
             patch("app.api.routers.run_control._runs_dir", return_value=tmp_path):
            resp = api_client.post("/api/v1/runs/run-never/pause")
        assert resp.status_code == 404
        detail = resp.json().get("detail", resp.json())
        assert detail.get("error") == "run_not_found"

    def test_pause_calls_run_pause(self, api_client):
        """POST /api/v1/runs/{run_id}/pause calls run.pause()."""
        run = _make_active_run()
        with patch("app.api.routers.run_control.get_active_run", return_value=run):
            api_client.post("/api/v1/runs/run-abc/pause")
        run.pause.assert_called_once()


class TestResumeRun:
    def test_resume_active_run_returns_200(self, api_client):
        """POST /api/v1/runs/{run_id}/resume with active run returns 200 with running status.

        Validates: Req 24 criteria 3
        """
        run = _make_active_run()
        with patch("app.api.routers.run_control.get_active_run", return_value=run):
            resp = api_client.post("/api/v1/runs/run-abc/resume")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"

    def test_resume_inactive_run_returns_404(self, api_client):
        """POST /api/v1/runs/{run_id}/resume with no active run returns 404."""
        with patch("app.api.routers.run_control.get_active_run", return_value=None):
            resp = api_client.post("/api/v1/runs/run-xyz/resume")
        assert resp.status_code == 404

    def test_resume_calls_run_resume(self, api_client):
        """POST /api/v1/runs/{run_id}/resume calls run.resume()."""
        run = _make_active_run()
        with patch("app.api.routers.run_control.get_active_run", return_value=run):
            api_client.post("/api/v1/runs/run-abc/resume")
        run.resume.assert_called_once()


class TestCancelRun:
    def test_cancel_active_run_returns_200(self, api_client):
        """POST /api/v1/runs/{run_id}/cancel with active run returns 200 with cancelled status.

        Validates: Req 24 criteria 4
        """
        run = _make_active_run()
        with patch("app.api.routers.run_control.get_active_run", return_value=run):
            resp = api_client.post("/api/v1/runs/run-abc/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cancelled"

    def test_cancel_inactive_run_returns_404(self, api_client):
        """POST /api/v1/runs/{run_id}/cancel with no active run returns 404."""
        with patch("app.api.routers.run_control.get_active_run", return_value=None):
            resp = api_client.post("/api/v1/runs/run-xyz/cancel")
        assert resp.status_code == 404

    def test_cancel_calls_run_cancel(self, api_client):
        """POST /api/v1/runs/{run_id}/cancel calls run.cancel()."""
        run = _make_active_run()
        with patch("app.api.routers.run_control.get_active_run", return_value=run):
            api_client.post("/api/v1/runs/run-abc/cancel")
        run.cancel.assert_called_once()
