# unit_test/mcp/test_handler_artifacts.py
"""Tests for app/mcp/handlers/artifacts.py — Req 12."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mcp.handlers.artifacts import inspect_run_handler


class TestInspectRunNoRunId:
    def test_no_run_id_returns_runs_list(self, tmp_workspace):
        """inspect_run with no run_id returns {"runs": [...]}."""
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = inspect_run_handler({})
        assert "runs" in result
        assert isinstance(result["runs"], list)

    def test_no_run_id_empty_workspace_returns_empty_list(self, tmp_workspace):
        """No runs directory → returns {"runs": []}."""
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = inspect_run_handler({})
        assert result["runs"] == []

    def test_no_run_id_with_runs_returns_list(self, tmp_workspace):
        """Runs with meta.json are returned in the list."""
        runs_dir = tmp_workspace / "runs"
        runs_dir.mkdir(parents=True)
        run_dir = runs_dir / "run-abc"
        run_dir.mkdir()
        meta = {"run_id": "run-abc", "status": "completed", "created_at": "2024-01-01T00:00:00+00:00"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = inspect_run_handler({})

        assert len(result["runs"]) == 1
        assert result["runs"][0]["run_id"] == "run-abc"


class TestInspectRunWithRunId:
    def test_with_run_id_returns_meta(self, tmp_workspace):
        """inspect_run with run_id returns the meta.json contents."""
        runs_dir = tmp_workspace / "runs"
        runs_dir.mkdir(parents=True)
        run_dir = runs_dir / "run-xyz"
        run_dir.mkdir()
        meta = {"run_id": "run-xyz", "status": "running", "num_nodes": 2}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = inspect_run_handler({"run_id": "run-xyz"})

        assert result.get("run_id") == "run-xyz"
        assert result.get("status") == "running"

    def test_unknown_run_id_returns_error(self, tmp_workspace):
        """Unknown run_id returns error_type=unknown_run_id."""
        runs_dir = tmp_workspace / "runs"
        runs_dir.mkdir(parents=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = inspect_run_handler({"run_id": "nonexistent-run"})

        assert result.get("error") is True
        assert result.get("error_type") == "unknown_run_id"

    def test_status_only_returns_status(self, tmp_workspace):
        """status_only=True returns {"status": ...}."""
        runs_dir = tmp_workspace / "runs"
        runs_dir.mkdir(parents=True)
        run_dir = runs_dir / "run-s"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps({"status": "completed"}))

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = inspect_run_handler({"run_id": "run-s", "status_only": True})

        assert "status" in result
        assert result["status"] == "completed"
        # Should not contain other meta fields
        assert "run_id" not in result
