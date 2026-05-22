# unit_test/api/test_artifacts_router.py
"""Tests for /api/v1/artifacts router (Req 24 criteria 5–12)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_artifact_record(artifact_id: str = "art-001", run_id: str = "run-001"):
    """Return a minimal mock ArtifactRecord."""
    record = MagicMock()
    record.artifact_id = artifact_id
    record.run_id = run_id
    record.node_id = "node-1"
    record.node_type = "clean"
    record.artifact_type = "generic"
    record.content_hash = "abc123"
    record.model_dump.return_value = {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "node_id": "node-1",
        "node_type": "clean",
        "artifact_type": "generic",
        "content_hash": "abc123",
    }
    return record


def _make_store(records=None):
    """Return a mock ArtifactStore."""
    store = MagicMock()
    store.list.return_value = records or []
    return store


class TestListArtifacts:
    def test_returns_200_with_json_array(self, api_client):
        """GET /api/v1/artifacts returns 200 with a JSON array.

        Validates: Req 24 criteria 5
        """
        store = _make_store()
        with patch("app.core.artifact_store.ArtifactStore", return_value=store):
            resp = api_client.get("/api/v1/artifacts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_run_id_filter_passed_to_store(self, api_client):
        """GET /api/v1/artifacts?run_id=r1 passes run_id filter to ArtifactStore.list().

        Validates: Req 24 criteria 6
        """
        store = _make_store()
        with patch("app.core.artifact_store.ArtifactStore", return_value=store):
            api_client.get("/api/v1/artifacts?run_id=r1")
        store.list.assert_called_once_with(run_id="r1", node_type=None, artifact_type=None)

    def test_returns_artifact_records(self, api_client):
        """GET /api/v1/artifacts returns serialized artifact records."""
        record = _make_artifact_record()
        store = _make_store(records=[record])
        with patch("app.core.artifact_store.ArtifactStore", return_value=store):
            resp = api_client.get("/api/v1/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["artifact_id"] == "art-001"


class TestGetArtifact:
    def test_valid_id_returns_200(self, api_client):
        """GET /api/v1/artifacts/{valid_id} returns 200 with artifact record.

        Validates: Req 24 criteria 7
        """
        record = _make_artifact_record("art-001")
        store = MagicMock()
        store.get.return_value = record
        with patch("app.core.artifact_store.ArtifactStore", return_value=store):
            resp = api_client.get("/api/v1/artifacts/art-001")
        assert resp.status_code == 200
        assert resp.json()["artifact_id"] == "art-001"

    def test_not_found_returns_404(self, api_client):
        """GET /api/v1/artifacts/{valid_id} returns 404 when ArtifactNotFoundError raised.

        Validates: Req 24 criteria 8
        """
        from app.core.artifact_store import ArtifactNotFoundError

        store = MagicMock()
        store.get.side_effect = ArtifactNotFoundError("not found")
        with patch("app.core.artifact_store.ArtifactStore", return_value=store):
            resp = api_client.get("/api/v1/artifacts/art-missing")
        assert resp.status_code == 404

    def test_invalid_id_returns_400(self, api_client):
        """GET /api/v1/artifacts/bad!id returns 400 for invalid characters.

        Validates: Req 24 criteria 9
        """
        resp = api_client.get("/api/v1/artifacts/bad!id")
        assert resp.status_code == 400

    def test_invalid_id_with_spaces_returns_400(self, api_client):
        """GET /api/v1/artifacts/{id with spaces} returns 400."""
        resp = api_client.get("/api/v1/artifacts/bad%20id")
        assert resp.status_code == 400


class TestGetArtifactLineage:
    def test_returns_200_with_lineage_dict(self, api_client):
        """GET /api/v1/artifacts/{id}/lineage returns 200 with lineage dict (never 404).

        Validates: Req 24 criteria 10
        """
        lineage = {"artifact_id": "art-001", "inputs": [], "run_id": "run-001"}
        prov_store = MagicMock()
        prov_store.get_lineage.return_value = lineage
        with patch("app.core.provenance.ProvenanceStore", return_value=prov_store):
            resp = api_client.get("/api/v1/artifacts/art-001/lineage")
        assert resp.status_code == 200
        body = resp.json()
        assert "artifact_id" in body

    def test_lineage_never_returns_404_for_unknown(self, api_client):
        """GET /api/v1/artifacts/{id}/lineage returns 200 even for unknown artifact."""
        # ProvenanceStore.get_lineage returns error node dict, never raises
        error_lineage = {
            "artifact_id": "unknown-art",
            "inputs": [],
            "error": "no_provenance_record",
        }
        prov_store = MagicMock()
        prov_store.get_lineage.return_value = error_lineage
        with patch("app.core.provenance.ProvenanceStore", return_value=prov_store):
            resp = api_client.get("/api/v1/artifacts/unknown-art/lineage")
        assert resp.status_code == 200


class TestReplayArtifact:
    def test_artifact_not_found_returns_404(self, api_client):
        """POST /api/v1/artifacts/{id}/replay returns 404 when artifact not found.

        Validates: Req 24 criteria 11
        """
        from app.core.artifact_store import ArtifactNotFoundError

        art_store = MagicMock()
        art_store.get.side_effect = ArtifactNotFoundError("not found")
        with patch("app.core.artifact_store.ArtifactStore", return_value=art_store):
            resp = api_client.post("/api/v1/artifacts/art-missing/replay")
        assert resp.status_code == 404

    def test_missing_graph_json_returns_422(self, api_client, tmp_path):
        """POST /api/v1/artifacts/{id}/replay returns 422 when graph.json is missing.

        Validates: Req 24 criteria 12
        """
        record = _make_artifact_record("art-001", run_id="run-001")
        art_store = MagicMock()
        art_store.get.return_value = record

        # Point runs_dir to tmp_path — no graph.json exists there
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        (runs_dir / "run-001").mkdir()

        with (
            patch("app.core.artifact_store.ArtifactStore", return_value=art_store),
            patch("app.core.config.runs_dir", return_value=runs_dir),
        ):
            resp = api_client.post("/api/v1/artifacts/art-001/replay")
        assert resp.status_code == 422
