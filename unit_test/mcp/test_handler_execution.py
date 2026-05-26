# unit_test/mcp/test_handler_execution.py
"""Tests for app/mcp/handlers/execution.py — Req 12."""
from __future__ import annotations

from unittest.mock import patch

from app.mcp.handlers.execution import execute_pipeline_handler
from app.mcp.handlers.graph import generate_graph_handler
from app.core.ir.loader import CURRENT_IR_VERSION


def _valid_graph():
    """Return a valid GraphIR dict for a single audio_conditioner node.

    Falls back to a minimal valid IR dict when the node type is not registered
    (e.g. when GRAPHYN_SKIP_PLUGIN_LOAD=1 is set in the test environment).
    """
    result = generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})
    if result.get("error"):
        # Fallback: minimal valid IR that doesn't require any registered node type
        # for load_ir() structural validation (node type is checked at execution time)
        return {
            "schema_version": CURRENT_IR_VERSION,
            "metadata": {"name": "test", "seed": 0},
            "nodes": [{"id": "n0", "node_type": "audio_conditioner", "config": {}}],
            "edges": [],
        }
    return result


class TestExecutePipeline:
    def test_valid_graph_returns_run_id(self):
        """Valid graph returns run_id and status=started."""
        graph = _valid_graph()
        # patch_threads autouse fixture already patches ThreadPoolExecutor.submit
        result = execute_pipeline_handler({"graph": graph})
        assert "run_id" in result
        assert result["run_id"]
        assert result.get("status") == "started"

    def test_invalid_graph_returns_valid_false(self):
        """Invalid graph returns valid=False with errors."""
        result = execute_pipeline_handler({"graph": {"bad": "data"}})
        assert result.get("valid") is False
        assert "errors" in result
        assert len(result["errors"]) > 0

    def test_missing_graph_returns_error(self):
        """Missing graph argument returns error."""
        result = execute_pipeline_handler({})
        assert result.get("valid") is False or result.get("error") is True

    def test_use_cache_forwarded(self):
        """use_cache parameter is forwarded to backend.execute."""
        graph = _valid_graph()
        captured = {}

        def fake_execute(g, use_cache=True, **kwargs):
            captured["use_cache"] = use_cache

        from unittest.mock import MagicMock
        import app.mcp.handlers.execution as _exec_mod

        mock_backend = MagicMock()
        mock_backend.execute.side_effect = fake_execute

        def sync_submit(fn, *args, **kwargs):
            fn(*args, **kwargs)

        with patch("app.mcp.handlers.execution._get_backend", return_value=mock_backend):
            with patch.object(_exec_mod._PIPELINE_EXECUTOR, "submit", sync_submit):
                execute_pipeline_handler({"graph": graph, "use_cache": False})

        assert captured.get("use_cache") is False

    def test_use_cache_defaults_to_true(self):
        """use_cache defaults to True when not specified."""
        graph = _valid_graph()
        captured = {}

        def fake_execute(g, use_cache=True, **kwargs):
            captured["use_cache"] = use_cache

        from unittest.mock import MagicMock
        import app.mcp.handlers.execution as _exec_mod

        mock_backend = MagicMock()
        mock_backend.execute.side_effect = fake_execute

        def sync_submit(fn, *args, **kwargs):
            fn(*args, **kwargs)

        with patch("app.mcp.handlers.execution._get_backend", return_value=mock_backend):
            with patch.object(_exec_mod._PIPELINE_EXECUTOR, "submit", sync_submit):
                execute_pipeline_handler({"graph": graph})

        assert captured.get("use_cache") is True

    def test_returns_unique_run_ids(self):
        """Each call returns a different run_id."""
        graph = _valid_graph()
        result1 = execute_pipeline_handler({"graph": graph})
        result2 = execute_pipeline_handler({"graph": graph})
        assert result1.get("run_id") != result2.get("run_id")
