# unit_test/mcp/test_handler_run_control.py
"""Tests for app/mcp/handlers/run_control.py — Req 12."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.mcp.handlers.run_control import (
    handle_pause_run,
    handle_resume_run,
    handle_cancel_run,
)


class TestPauseRun:
    def test_inactive_run_returns_run_not_active(self):
        """pause inactive run returns error_type=run_not_active."""
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=None):
            result = handle_pause_run({"run_id": "nonexistent-run"})
        assert result.get("error") is True
        assert result.get("error_type") == "run_not_active"

    def test_active_run_returns_paused(self):
        """pause active run returns status=paused."""
        mock_run = MagicMock()
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=mock_run):
            result = handle_pause_run({"run_id": "run-abc"})
        assert result.get("status") == "paused"
        assert result.get("run_id") == "run-abc"
        mock_run.pause.assert_called_once()

    def test_error_dict_has_run_id(self):
        """Error dict includes the run_id."""
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=None):
            result = handle_pause_run({"run_id": "my-run"})
        assert result.get("run_id") == "my-run"


class TestResumeRun:
    def test_inactive_run_returns_run_not_active(self):
        """resume inactive run returns error_type=run_not_active."""
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=None):
            result = handle_resume_run({"run_id": "nonexistent-run"})
        assert result.get("error") is True
        assert result.get("error_type") == "run_not_active"

    def test_active_run_returns_running(self):
        """resume active run returns status=running."""
        mock_run = MagicMock()
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=mock_run):
            result = handle_resume_run({"run_id": "run-abc"})
        assert result.get("status") == "running"
        mock_run.resume.assert_called_once()


class TestCancelRun:
    def test_inactive_run_returns_run_not_active(self):
        """cancel inactive run returns error_type=run_not_active."""
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=None):
            result = handle_cancel_run({"run_id": "nonexistent-run"})
        assert result.get("error") is True
        assert result.get("error_type") == "run_not_active"

    def test_active_run_returns_cancelled(self):
        """cancel active run returns status=cancelled."""
        mock_run = MagicMock()
        with patch("app.mcp.handlers.run_control.get_active_run", return_value=mock_run):
            result = handle_cancel_run({"run_id": "run-abc"})
        assert result.get("status") == "cancelled"
        mock_run.cancel.assert_called_once()
