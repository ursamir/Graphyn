# unit_test/mcp/test_handler_provenance.py
"""Tests for app/mcp/handlers/provenance.py — Req 12."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.handlers.provenance import (
    list_artifacts_handler,
    get_artifact_lineage_handler,
    replay_run_handler,
)


class TestListArtifacts:
    def test_returns_artifacts_list(self, tmp_workspace):
        """list_artifacts returns dict with artifacts list and count."""
        mock_store = MagicMock()
        mock_store.list.return_value = []
        with patch("app.core.artifact_store.ArtifactStore", return_value=mock_store):
            result = list_artifacts_handler({})
        assert "artifacts" in result
        assert "count" in result
        assert isinstance(result["artifacts"], list)
        assert result["count"] == 0

    def test_run_id_filter_forwarded(self, tmp_workspace):
        """run_id filter is forwarded to ArtifactStore.list()."""
        mock_store = MagicMock()
        mock_store.list.return_value = []
        with patch("app.core.artifact_store.ArtifactStore", return_value=mock_store):
            list_artifacts_handler({"run_id": "run-001"})
        mock_store.list.assert_called_once_with(
            run_id="run-001", node_type=None, artifact_type=None
        )

    def test_store_error_returns_error_dict(self):
        """ArtifactStore exception returns error dict."""
        mock_store = MagicMock()
        mock_store.list.side_effect = RuntimeError("store failure")
        with patch("app.core.artifact_store.ArtifactStore", return_value=mock_store):
            result = list_artifacts_handler({})
        assert result.get("error") is True
        assert result.get("error_type") == "store_error"


class TestGetArtifactLineage:
    def test_returns_lineage_dict(self):
        """get_artifact_lineage returns lineage dict for known artifact."""
        lineage = {"artifact_id": "art-001", "inputs": [], "run_id": "run-001"}
        mock_store = MagicMock()
        mock_store.get_lineage.return_value = lineage
        with patch("app.core.provenance.ProvenanceStore", return_value=mock_store):
            result = get_artifact_lineage_handler({"artifact_id": "art-001"})
        assert result.get("artifact_id") == "art-001"

    def test_missing_artifact_id_returns_error(self):
        """Missing artifact_id returns error_type=missing_argument."""
        result = get_artifact_lineage_handler({})
        assert result.get("error") is True
        assert result.get("error_type") == "missing_argument"

    def test_unknown_artifact_returns_error_node(self):
        """Unknown artifact returns error node dict (not an exception)."""
        error_node = {
            "artifact_id": "unknown",
            "inputs": [],
            "error": "no_provenance_record",
        }
        mock_store = MagicMock()
        mock_store.get_lineage.return_value = error_node
        with patch("app.core.provenance.ProvenanceStore", return_value=mock_store):
            result = get_artifact_lineage_handler({"artifact_id": "unknown"})
        assert result.get("artifact_id") == "unknown"


class TestReplayRun:
    def test_missing_run_id_returns_error(self):
        """Missing run_id returns error_type=missing_argument."""
        result = replay_run_handler({})
        assert result.get("error") is True
        assert result.get("error_type") == "missing_argument"

    def test_unknown_run_id_returns_error(self, tmp_workspace):
        """Unknown run_id returns error_type=unknown_run_id."""
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = replay_run_handler({"run_id": "nonexistent-run"})
        assert result.get("error") is True
        assert result.get("error_type") == "unknown_run_id"

    def test_missing_graph_json_returns_error(self, tmp_workspace):
        """Run dir exists but no graph.json returns error_type=graph_not_found."""
        runs_dir = tmp_workspace / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "run-001").mkdir()

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = replay_run_handler({"run_id": "run-001"})
        assert result.get("error") is True
        assert result.get("error_type") == "graph_not_found"

    def test_valid_run_returns_new_run_id(self, tmp_workspace):
        """Valid run with graph.json returns new run_id and status=started."""
        from app.core.ir.loader import CURRENT_IR_VERSION
        runs_dir = tmp_workspace / "runs"
        runs_dir.mkdir(parents=True)
        run_dir = runs_dir / "run-001"
        run_dir.mkdir()
        graph = {
            "schema_version": CURRENT_IR_VERSION,
            "metadata": {"name": "test", "seed": 0},
            "nodes": [{"id": "n0", "node_type": "audio_conditioner", "config": {}}],
            "edges": [],
        }
        (run_dir / "graph.json").write_text(json.dumps(graph))

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
            result = replay_run_handler({"run_id": "run-001"})

        assert "run_id" in result
        assert result.get("status") == "started"
        assert result["run_id"] != "run-001"  # new run_id
