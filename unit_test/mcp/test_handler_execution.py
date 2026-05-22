# unit_test/mcp/test_handler_execution.py
"""Tests for app/mcp/handlers/execution.py — Req 12."""
from __future__ import annotations

from unittest.mock import patch

from app.mcp.handlers.execution import execute_pipeline_handler
from app.mcp.handlers.graph import generate_graph_handler


def _valid_graph():
    """Return a valid GraphIR dict for a single audio_conditioner node."""
    return generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})


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
        """use_cache parameter is forwarded to run_pipeline_ir."""
        graph = _valid_graph()
        captured = {}

        def fake_run(g, use_cache=True, **kwargs):
            captured["use_cache"] = use_cache

        # Patch run_pipeline_ir AND make executor.submit call it synchronously
        import concurrent.futures
        from unittest.mock import MagicMock

        real_submit = concurrent.futures.ThreadPoolExecutor.submit

        def sync_submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)

        with patch("app.mcp.handlers.execution.run_pipeline_ir", fake_run):
            with patch.object(concurrent.futures.ThreadPoolExecutor, "submit", sync_submit):
                execute_pipeline_handler({"graph": graph, "use_cache": False})

        assert captured.get("use_cache") is False

    def test_use_cache_defaults_to_true(self):
        """use_cache defaults to True when not specified."""
        graph = _valid_graph()
        captured = {}

        def fake_run(g, use_cache=True, **kwargs):
            captured["use_cache"] = use_cache

        import concurrent.futures

        def sync_submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)

        with patch("app.mcp.handlers.execution.run_pipeline_ir", fake_run):
            with patch.object(concurrent.futures.ThreadPoolExecutor, "submit", sync_submit):
                execute_pipeline_handler({"graph": graph})

        assert captured.get("use_cache") is True

    def test_returns_unique_run_ids(self):
        """Each call returns a different run_id."""
        graph = _valid_graph()
        result1 = execute_pipeline_handler({"graph": graph})
        result2 = execute_pipeline_handler({"graph": graph})
        assert result1.get("run_id") != result2.get("run_id")
