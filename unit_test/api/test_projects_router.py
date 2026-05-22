# unit_test/api/test_projects_router.py
"""Tests for /api/v1/projects router (Req 24 criteria 23–26)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_pm(projects=None):
    """Return a mock ProjectManager."""
    pm = MagicMock()
    pm.list_all.return_value = projects or []
    pm.create.return_value = {
        "name": "test-proj",
        "status": "draft",
        "versions": [],
        "created_at": "2024-01-01T00:00:00+00:00",
    }
    pm.delete.return_value = None
    pm.get_taxonomy.return_value = []
    return pm


class TestListProjects:
    def test_returns_200_with_json_array(self, api_client):
        """GET /api/v1/projects returns 200 with a JSON array.

        Validates: Req 24 criteria 23
        """
        pm = _make_pm()
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_empty_list_when_no_projects(self, api_client):
        """GET /api/v1/projects returns [] when no projects exist."""
        pm = _make_pm(projects=[])
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_project_entries(self, api_client):
        """GET /api/v1/projects returns project metadata entries."""
        projects = [{"name": "proj-a", "status": "draft"}]
        pm = _make_pm(projects=projects)
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "proj-a"


class TestCreateProject:
    def test_create_project_returns_200_with_metadata(self, api_client):
        """POST /api/v1/projects with name returns 200 with project metadata.

        Validates: Req 24 criteria 24
        """
        pm = _make_pm()
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.post("/api/v1/projects", json={"name": "test-proj"})
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body
        assert body["name"] == "test-proj"

    def test_create_project_calls_pm_create(self, api_client):
        """POST /api/v1/projects calls ProjectManager.create with the project name."""
        pm = _make_pm()
        with patch("app.api.routers.projects._pm", pm):
            api_client.post("/api/v1/projects", json={"name": "my-project"})
        pm.create.assert_called_once_with("my-project")

    def test_duplicate_project_returns_422(self, api_client):
        """POST /api/v1/projects with duplicate name returns 422."""
        pm = _make_pm()
        pm.create.side_effect = ValueError("Project already exists")
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.post("/api/v1/projects", json={"name": "existing-proj"})
        assert resp.status_code == 422


class TestDeleteProject:
    def test_wrong_confirm_returns_422(self, api_client):
        """DELETE /api/v1/projects/{name} with wrong confirm returns 422.

        Validates: Req 24 criteria 25
        """
        import json as _json

        pm = _make_pm()
        pm.delete.side_effect = ValueError("confirm does not match project name")
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.request(
                "DELETE",
                "/api/v1/projects/my-project",
                json={"confirm": "wrong-name"},
            )
        assert resp.status_code == 422

    def test_correct_confirm_returns_200(self, api_client):
        """DELETE /api/v1/projects/{name} with correct confirm returns 200."""
        pm = _make_pm()
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.request(
                "DELETE",
                "/api/v1/projects/my-project",
                json={"confirm": "my-project"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] == "my-project"


class TestGetTaxonomy:
    def test_nonexistent_project_returns_404(self, api_client):
        """GET /api/v1/projects/{name}/taxonomy returns 404 when project doesn't exist.

        Validates: Req 24 criteria 26
        """
        pm = _make_pm()
        pm.get_taxonomy.side_effect = FileNotFoundError("Project not found")
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects/nonexistent-proj/taxonomy")
        assert resp.status_code == 404

    def test_existing_project_returns_200(self, api_client):
        """GET /api/v1/projects/{name}/taxonomy returns 200 for existing project."""
        pm = _make_pm()
        pm.get_taxonomy.return_value = [{"name": "speech", "children": []}]
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects/my-project/taxonomy")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
