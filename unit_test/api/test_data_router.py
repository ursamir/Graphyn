# unit_test/api/test_data_router.py
"""Tests for /api/v1/data router (Req 24 criteria 13–18)."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch


class TestListInputDatasets:
    def test_returns_200_with_json_array(self, api_client, tmp_path):
        """GET /api/v1/data/inputs returns 200 with a JSON array.

        Validates: Req 24 criteria 13
        """
        input_root = tmp_path / "datasets" / "input"
        input_root.mkdir(parents=True)
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.get("/api/v1/data/inputs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_empty_list_when_no_labels(self, api_client, tmp_path):
        """GET /api/v1/data/inputs returns [] when input directory is empty."""
        input_root = tmp_path / "datasets" / "input"
        input_root.mkdir(parents=True)
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.get("/api/v1/data/inputs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_label_entries(self, api_client, tmp_path):
        """GET /api/v1/data/inputs returns label entries with file_count."""
        input_root = tmp_path / "datasets" / "input"
        label_dir = input_root / "speech"
        label_dir.mkdir(parents=True)
        (label_dir / "sample.wav").write_bytes(b"RIFF")
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.get("/api/v1/data/inputs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["label"] == "speech"
        assert "file_count" in data[0]


class TestGetInputDataset:
    def test_missing_label_returns_404(self, api_client, tmp_path):
        """GET /api/v1/data/inputs/{label} returns 404 when label dir doesn't exist.

        Validates: Req 24 criteria 14
        """
        input_root = tmp_path / "datasets" / "input"
        input_root.mkdir(parents=True)
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.get("/api/v1/data/inputs/nonexistent-label")
        assert resp.status_code == 404

    def test_existing_label_returns_200(self, api_client, tmp_path):
        """GET /api/v1/data/inputs/{label} returns 200 for an existing label."""
        input_root = tmp_path / "datasets" / "input"
        label_dir = input_root / "speech"
        label_dir.mkdir(parents=True)
        (label_dir / "sample.wav").write_bytes(b"RIFF")
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.get("/api/v1/data/inputs/speech")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestListOutputDatasets:
    def test_returns_200_with_json_array(self, api_client, tmp_path):
        """GET /api/v1/data/outputs returns 200 with a JSON array.

        Validates: Req 24 criteria 15
        """
        output_root = tmp_path / "datasets" / "output"
        output_root.mkdir(parents=True)
        with patch("app.api.routers.data.OUTPUT_ROOT", output_root):
            resp = api_client.get("/api/v1/data/outputs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_empty_list_when_no_projects(self, api_client, tmp_path):
        """GET /api/v1/data/outputs returns [] when output directory is empty."""
        output_root = tmp_path / "datasets" / "output"
        output_root.mkdir(parents=True)
        with patch("app.api.routers.data.OUTPUT_ROOT", output_root):
            resp = api_client.get("/api/v1/data/outputs")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetOutputDataset:
    def test_missing_dataset_returns_404(self, api_client, tmp_path):
        """GET /api/v1/data/outputs/{project}/{version} returns 404 when dataset doesn't exist.

        Validates: Req 24 criteria 16
        """
        output_root = tmp_path / "datasets" / "output"
        output_root.mkdir(parents=True)
        with patch("app.api.routers.data.OUTPUT_ROOT", output_root):
            resp = api_client.get("/api/v1/data/outputs/myproject/v1")
        assert resp.status_code == 404

    def test_existing_dataset_returns_200(self, api_client, tmp_path):
        """GET /api/v1/data/outputs/{project}/{version} returns 200 for existing dataset."""
        output_root = tmp_path / "datasets" / "output"
        dataset_dir = output_root / "myproject" / "v1"
        dataset_dir.mkdir(parents=True)
        with patch("app.api.routers.data.OUTPUT_ROOT", output_root):
            resp = api_client.get("/api/v1/data/outputs/myproject/v1")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMergeDatasets:
    def test_empty_sources_returns_422(self, api_client, tmp_path):
        """POST /api/v1/data/merge with empty sources returns 422.

        Validates: Req 24 criteria 17
        """
        output_root = tmp_path / "datasets" / "output"
        output_root.mkdir(parents=True)
        with patch("app.api.routers.data.OUTPUT_ROOT", output_root):
            resp = api_client.post(
                "/api/v1/data/merge",
                json={"sources": [], "target_project": "merged", "target_version": "v1"},
            )
        assert resp.status_code == 422

    def test_valid_merge_returns_200(self, api_client, tmp_path):
        """POST /api/v1/data/merge with valid sources returns 200."""
        output_root = tmp_path / "datasets" / "output"
        src_dir = output_root / "proj-a" / "v1"
        src_dir.mkdir(parents=True)
        (src_dir / "sample.wav").write_bytes(b"RIFF")
        with patch("app.api.routers.data.OUTPUT_ROOT", output_root):
            resp = api_client.post(
                "/api/v1/data/merge",
                json={
                    "sources": [{"project": "proj-a", "version": "v1"}],
                    "target_project": "merged",
                    "target_version": "v1",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "files_copied" in body


class TestUploadFile:
    def test_unsupported_extension_returns_400(self, api_client, tmp_path):
        """POST /api/v1/data/inputs/upload with unsupported extension returns 400.

        Validates: Req 24 criteria 18
        """
        input_root = tmp_path / "datasets" / "input"
        input_root.mkdir(parents=True)
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.post(
                "/api/v1/data/inputs/upload",
                files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
            )
        assert resp.status_code == 400

    def test_supported_extension_returns_200(self, api_client, tmp_path):
        """POST /api/v1/data/inputs/upload with .wav file returns 200."""
        input_root = tmp_path / "datasets" / "input"
        input_root.mkdir(parents=True)
        with patch("app.api.routers.data.INPUT_ROOT", input_root):
            resp = api_client.post(
                "/api/v1/data/inputs/upload",
                files={"file": ("audio.wav", io.BytesIO(b"RIFF"), "audio/wav")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "file_path" in body
        assert "filename" in body
