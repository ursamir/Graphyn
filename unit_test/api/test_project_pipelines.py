# unit_test/api/test_project_pipelines.py
"""Tests for project-owned pipeline CRUD and secret policy on validate."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

_VALID_IR = {
    "schema_version": "1.0",
    "metadata": {"name": "demo", "seed": 42},
    "nodes": [],
    "edges": [],
}

_SECRET_IR = {
    "schema_version": "1.0",
    "metadata": {"name": "leak", "seed": 42},
    "nodes": [
        {
            "id": "n1",
            "node_type": "http_request",
            "config": {"api_key": "sk-live-secret", "url": "https://example.com"},
        }
    ],
    "edges": [],
}


@pytest.fixture
def project_home(tmp_path, api_client):
    """Point ProjectManager project root at a temp dir and create one project."""
    from app.domain.project_manager import ProjectManager

    real = ProjectManager()
    proj = tmp_path / "acme"
    proj.mkdir()
    (proj / "project.json").write_text(
        json.dumps({"name": "acme", "status": "draft", "versions": []}),
        encoding="utf-8",
    )

    def _require(name: str) -> Path:
        if name != "acme":
            raise FileNotFoundError(f"Project '{name}' not found")
        return proj

    with patch("app.api.routers.projects._pm") as pm:
        pm._require_project.side_effect = _require
        yield tmp_path, "acme"


class TestProjectPipelines:
    def test_list_empty(self, api_client, project_home):
        tmp, name = project_home
        resp = api_client.get(f"/api/v1/projects/{name}/pipelines")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_put_get_list_delete(self, api_client, project_home):
        tmp, name = project_home
        put = api_client.put(
            f"/api/v1/projects/{name}/pipelines/main",
            json=_VALID_IR,
        )
        assert put.status_code == 200
        body = put.json()
        assert body["metadata"]["project"] == name
        path = tmp / name / "pipelines" / "main.graph.json"
        assert path.is_file()

        got = api_client.get(f"/api/v1/projects/{name}/pipelines/main")
        assert got.status_code == 200
        assert got.json()["metadata"]["project"] == name

        listed = api_client.get(f"/api/v1/projects/{name}/pipelines")
        assert listed.status_code == 200
        items = listed.json()
        assert len(items) == 1
        assert items[0]["name"] == "main"
        assert items[0]["node_count"] == 0

        deleted = api_client.delete(f"/api/v1/projects/{name}/pipelines/main")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert api_client.get(f"/api/v1/projects/{name}/pipelines/main").status_code == 404

    def test_put_rejects_path_escape_name(self, api_client, project_home):
        _, name = project_home
        resp = api_client.put(
            f"/api/v1/projects/{name}/pipelines/../evil",
            json=_VALID_IR,
        )
        assert resp.status_code in (404, 422)

    def test_put_rejects_inline_secret(self, api_client, project_home):
        _, name = project_home
        resp = api_client.put(
            f"/api/v1/projects/{name}/pipelines/leak",
            json=_SECRET_IR,
        )
        assert resp.status_code == 422
        assert "secret" in resp.json()["detail"].lower() or "Inline" in resp.json()["detail"]


class TestValidateSecretPolicy:
    def test_validate_rejects_inline_api_key(self, api_client):
        resp = api_client.post("/api/v1/pipelines/validate", json=_SECRET_IR)
        assert resp.status_code == 422
        body = resp.json()
        assert body.get("valid") is False
        assert "secret" in str(body.get("error", "")).lower() or "Inline" in str(body.get("error", ""))
