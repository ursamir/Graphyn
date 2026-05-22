# unit_test/api/test_ingest_router.py
"""Tests for /api/v1/ingest router (Req 24 criteria 19–22)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_svc(job_id: str = "job-001"):
    """Return a mock IngestionService."""
    svc = MagicMock()
    svc.start_url_job.return_value = job_id
    svc.start_hf_job.return_value = job_id
    job = MagicMock()
    job.job_id = job_id
    svc.get_job.return_value = job
    svc.stream_job.return_value = iter([])
    return svc


class TestUrlIngest:
    def test_empty_urls_returns_422(self, api_client):
        """POST /api/v1/ingest/url with urls=[] returns 422.

        Validates: Req 24 criteria 19
        """
        resp = api_client.post(
            "/api/v1/ingest/url",
            json={"urls": [], "label": "test"},
        )
        assert resp.status_code == 422

    def test_valid_body_returns_200_with_job_id(self, api_client):
        """POST /api/v1/ingest/url with valid body returns 200 with job_id.

        Validates: Req 24 criteria 20
        """
        svc = _make_svc("job-abc")
        with patch("app.api.routers.ingest._svc", svc):
            resp = api_client.post(
                "/api/v1/ingest/url",
                json={"urls": ["http://example.com/audio.wav"], "label": "test"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert body["job_id"] == "job-abc"

    def test_missing_label_returns_422(self, api_client):
        """POST /api/v1/ingest/url without label returns 422."""
        resp = api_client.post(
            "/api/v1/ingest/url",
            json={"urls": ["http://example.com/audio.wav"]},
        )
        assert resp.status_code == 422

    def test_start_url_job_called_with_correct_args(self, api_client):
        """POST /api/v1/ingest/url calls start_url_job with urls and label."""
        svc = _make_svc()
        with patch("app.api.routers.ingest._svc", svc):
            api_client.post(
                "/api/v1/ingest/url",
                json={"urls": ["http://example.com/a.wav"], "label": "speech"},
            )
        svc.start_url_job.assert_called_once_with(
            ["http://example.com/a.wav"], "speech"
        )


class TestStreamUrlJob:
    def test_unknown_job_id_returns_404(self, api_client):
        """GET /api/v1/ingest/url/{job_id}/stream returns 404 for unknown job_id.

        Validates: Req 24 criteria 21
        """
        svc = MagicMock()
        svc.get_job.side_effect = KeyError("unknown")
        with patch("app.api.routers.ingest._svc", svc):
            resp = api_client.get("/api/v1/ingest/url/unknown-job/stream")
        assert resp.status_code == 404

    def test_known_job_id_returns_streaming_response(self, api_client):
        """GET /api/v1/ingest/url/{job_id}/stream returns 200 for known job_id."""
        svc = _make_svc("job-001")
        with patch("app.api.routers.ingest._svc", svc):
            resp = api_client.get("/api/v1/ingest/url/job-001/stream")
        assert resp.status_code == 200


class TestHuggingFaceIngest:
    def test_empty_repo_id_returns_422(self, api_client):
        """POST /api/v1/ingest/huggingface with empty repo_id returns 422.

        Validates: Req 24 criteria 22
        """
        resp = api_client.post(
            "/api/v1/ingest/huggingface",
            json={"repo_id": "", "split": "train"},
        )
        assert resp.status_code == 422

    def test_missing_repo_id_returns_422(self, api_client):
        """POST /api/v1/ingest/huggingface without repo_id returns 422."""
        resp = api_client.post(
            "/api/v1/ingest/huggingface",
            json={"split": "train"},
        )
        assert resp.status_code == 422

    def test_valid_body_returns_200_with_job_id(self, api_client):
        """POST /api/v1/ingest/huggingface with valid body returns 200 with job_id."""
        svc = _make_svc("hf-job-001")
        with patch("app.api.routers.ingest._svc", svc):
            resp = api_client.post(
                "/api/v1/ingest/huggingface",
                json={"repo_id": "mozilla-foundation/common_voice_11_0", "split": "train"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert body["job_id"] == "hf-job-001"
