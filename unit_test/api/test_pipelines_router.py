# unit_test/api/test_pipelines_router.py
"""Tests for /api/v1/pipelines router (Req 11, Req 24)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Minimal valid IR JSON ─────────────────────────────────────────────────────

_VALID_IR = {
    "schema_version": "1.0",
    "metadata": {"name": "test", "seed": 42},
    "nodes": [],
    "edges": [],
}


# ── Validate endpoint ─────────────────────────────────────────────────────────

class TestValidatePipeline:
    def test_valid_ir_json_returns_200(self, api_client):
        """POST /api/v1/pipelines/validate with valid IR JSON returns 200."""
        from app.core.ir.models import GraphIR, IRMetadata

        mock_graph = MagicMock(spec=GraphIR)
        mock_graph.nodes = []
        mock_graph.metadata = IRMetadata(name="test", seed=42)

        with patch("app.core.ir.loader.load_ir", return_value=mock_graph):
            resp = api_client.post("/api/v1/pipelines/validate", json=_VALID_IR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True

    def test_invalid_ir_json_returns_422(self, api_client):
        """POST /api/v1/pipelines/validate with invalid IR JSON returns 422."""
        with patch(
            "app.core.ir.loader.load_ir",
            side_effect=ValueError("bad schema"),
        ):
            resp = api_client.post("/api/v1/pipelines/validate", json=_VALID_IR)

        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False

    def test_yaml_input_returns_deprecation_header(self, api_client):
        """YAML input to /validate returns X-Deprecation-Warning header."""
        yaml_payload = {"yaml": "pipeline:\n  seed: 42\n  nodes: []\n"}

        mock_registry = MagicMock()
        with (
            patch("app.api.routers.pipelines.get_registry", return_value=mock_registry),
            patch("app.api.routers.pipelines.validate_pipeline", return_value=None),
        ):
            resp = api_client.post("/api/v1/pipelines/validate", json=yaml_payload)

        assert resp.status_code == 200
        assert "X-Deprecation-Warning" in resp.headers

    def test_malformed_yaml_returns_error(self, api_client):
        """POST /api/v1/pipelines/validate with malformed YAML returns 422."""
        yaml_payload = {"yaml": ": bad: yaml: ["}
        mock_registry = MagicMock()
        with patch("app.api.routers.pipelines.get_registry", return_value=mock_registry):
            resp = api_client.post("/api/v1/pipelines/validate", json=yaml_payload)
        # Same HTTP contract as invalid IR — 422 + valid=False
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False


# ── Streaming run ─────────────────────────────────────────────────────────────

class TestRunStream:
    def test_run_stream_exposes_run_id_header_and_first_event(self, api_client):
        """POST /pipelines/run returns X-Run-Id and run_started before node events."""
        from app.core.ir.models import GraphIR, IRMetadata

        mock_graph = MagicMock(spec=GraphIR)
        mock_graph.nodes = []
        mock_graph.edges = []
        mock_graph.metadata = IRMetadata(name="test", seed=42)

        def _fake_execute(graph, logger=None, run_manager=None, **kwargs):
            if logger is not None:
                logger.pipeline_start(0, run_id=getattr(run_manager, "run_id", None))
                logger.pipeline_done(getattr(run_manager, "run_id", "x"), 0.01)
            return {}

        with (
            patch("app.api.routers.pipelines._build_graph_from_payload", return_value=(mock_graph, None)),
            patch("app.api.routers.pipelines._stamp_graph_project", return_value=(mock_graph, {})),
            patch("app.core.runtime_backend.get_backend") as gb,
        ):
            backend = MagicMock()
            backend.execute.side_effect = _fake_execute
            gb.return_value = backend
            resp = api_client.post("/api/v1/pipelines/run", json=_VALID_IR)

        assert resp.status_code == 200
        run_id = resp.headers.get("X-Run-Id")
        assert run_id
        lines = [ln for ln in resp.text.splitlines() if ln.strip()]
        assert lines, "expected NDJSON body"
        first = json.loads(lines[0])
        assert first.get("type") == "run_started"
        assert first.get("run_id") == run_id
        assert any(json.loads(ln).get("run_id") == run_id for ln in lines)

class TestTemplates:
    def test_list_templates_returns_list(self, api_client, tmp_path, monkeypatch):
        """GET /api/v1/pipelines/templates returns a list."""
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.get("/api/v1/pipelines/templates")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_template(self, api_client, tmp_path):
        """POST /api/v1/pipelines/templates creates a template."""
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.post(
                "/api/v1/pipelines/templates",
                json={"name": "my-template", "yaml": json.dumps(_VALID_IR)},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["saved"] is True
        assert body["name"] == "my-template"

    def test_get_template_by_name(self, api_client, tmp_path):
        """GET /api/v1/pipelines/templates/{name} returns the template."""
        # Create the template file first
        (tmp_path / "my-template.graph.json").write_text(json.dumps(_VALID_IR))
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.get("/api/v1/pipelines/templates/my-template")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "my-template"

    def test_get_nonexistent_template_returns_404(self, api_client, tmp_path):
        """GET /api/v1/pipelines/templates/{name} returns 404 for unknown template."""
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.get("/api/v1/pipelines/templates/nonexistent")
        assert resp.status_code == 404

    def test_list_versions_legacy_flat_returns_200(self, api_client, tmp_path):
        """Legacy flat templates must not 404 on /versions."""
        (tmp_path / "audio-quality-check.graph.json").write_text(json.dumps(_VALID_IR))
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.get("/api/v1/pipelines/templates/audio-quality-check/versions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "audio-quality-check"
        assert body["versions"] == []
        assert body["storage"] == "legacy_flat"
        assert body["latest_version"] is None

    def test_list_versions_missing_returns_404(self, api_client, tmp_path):
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.get("/api/v1/pipelines/templates/missing/versions")
        assert resp.status_code == 404

    def test_list_examples_returns_graph_irs(self, api_client):
        resp = api_client.get("/api/v1/pipelines/examples")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        assert "id" in body[0] and "source" in body[0]

    def test_sync_examples_writes_templates(self, api_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.core.example_templates.templates_dir",
            lambda: tmp_path,
        )
        resp = api_client.post("/api/v1/pipelines/templates/sync-examples")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count_written"] >= 1
        assert any(tmp_path.glob("ex-*.graph.json")) or any(tmp_path.glob("*.graph.json"))

    def test_delete_template(self, api_client, tmp_path):
        """DELETE /api/v1/pipelines/templates/{name} deletes the template."""
        (tmp_path / "to-delete.graph.json").write_text(json.dumps(_VALID_IR))
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.delete("/api/v1/pipelines/templates/to-delete")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is True

    def test_delete_nonexistent_template_returns_404(self, api_client, tmp_path):
        """DELETE /api/v1/pipelines/templates/{name} returns 404 for unknown template."""
        with patch("app.api.routers.pipelines._templates_dir", return_value=tmp_path):
            resp = api_client.delete("/api/v1/pipelines/templates/nonexistent")
        assert resp.status_code == 404
