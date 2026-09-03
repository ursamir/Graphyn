# unit_test/api/test_outputs_router.py
"""Tests for path-jailed output download routes."""
from __future__ import annotations

import json
from unittest.mock import patch


def _isolate_jail(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    home = tmp_path / "graphyn-home"
    ws.mkdir()
    home.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    return ws, home


class TestDownloadJail:
    def test_rejects_etc_passwd(self, api_client, tmp_path, monkeypatch):
        _isolate_jail(tmp_path, monkeypatch)
        resp = api_client.get("/api/v1/outputs/file", params={"path": "/etc/passwd"})
        assert resp.status_code in (400, 403)

    def test_rejects_dotdot_traversal(self, api_client, tmp_path, monkeypatch):
        _isolate_jail(tmp_path, monkeypatch)
        resp = api_client.get("/api/v1/outputs/file", params={"path": "../../etc/passwd"})
        assert resp.status_code == 400

    def test_rejects_embedded_dotdot(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        (ws / "artifacts").mkdir()
        resp = api_client.get(
            "/api/v1/outputs/file",
            params={"path": str(ws / "artifacts" / ".." / ".." / "etc" / "passwd")},
        )
        assert resp.status_code == 400

    def test_downloads_json_under_project_dir(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        out = ws / "artifacts" / "speech-commands"
        out.mkdir(parents=True)
        target = out / "metrics.json"
        target.write_text('{"accuracy": 0.9}', encoding="utf-8")
        resp = api_client.get("/api/v1/outputs/file", params={"path": str(target)})
        assert resp.status_code == 200
        assert resp.json()["accuracy"] == 0.9

    def test_rejects_disallowed_extension(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        secret = ws / "notes.py"
        secret.write_text("print('nope')\n", encoding="utf-8")
        resp = api_client.get("/api/v1/outputs/file", params={"path": str(secret)})
        assert resp.status_code == 415


class TestListRunOutputs:
    def test_lists_graph_output_path_files(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        run_id = "abc123"
        run_dir = ws / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id, "status": "completed"}))
        art = ws / "artifacts" / "speech-commands"
        art.mkdir(parents=True)
        (art / "metrics.json").write_text("{}", encoding="utf-8")
        (art / "confusion_matrix.png").write_bytes(b"\x89PNG\r\n")
        graph = {
            "nodes": [
                {
                    "id": "trainer_0",
                    "node_type": "trainer",
                    "config": {"output_path": str(art)},
                }
            ]
        }
        (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
        with patch("app.core.artifact_store.ArtifactStore") as store_cls:
            store_cls.return_value.list.return_value = []
            resp = api_client.get(f"/api/v1/runs/{run_id}/outputs")
        assert resp.status_code == 200
        names = {row["name"] for row in resp.json()}
        assert "metrics.json" in names
        assert "confusion_matrix.png" in names
        assert all(row["kind"] == "file" for row in resp.json())

    def test_zip_contains_listed_json(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        run_id = "ziprun1"
        run_dir = ws / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id, "status": "completed"}))
        (run_dir / "graph.json").write_text("{}", encoding="utf-8")
        metrics = run_dir / "metrics.json"
        metrics.write_text('{"ok": true}', encoding="utf-8")
        with patch("app.core.artifact_store.ArtifactStore") as store_cls:
            store_cls.return_value.list.return_value = []
            resp = api_client.get(f"/api/v1/runs/{run_id}/outputs/zip")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/zip")
        assert len(resp.content) > 0


class TestOutputDirAndCsv:
    def test_lists_graph_output_dir_under_artifacts(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        run_id = "outdir1"
        run_dir = ws / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id, "status": "completed"}))
        art = ws / "artifacts" / "wake-word"
        art.mkdir(parents=True)
        (art / "features.json").write_text("{}", encoding="utf-8")
        graph = {
            "nodes": [
                {
                    "id": "exporter_0",
                    "node_type": "dataset_exporter",
                    "config": {"output_dir": "workspace/artifacts/wake-word"},
                }
            ]
        }
        (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
        with patch("app.core.artifact_store.ArtifactStore") as store_cls:
            store_cls.return_value.list.return_value = []
            resp = api_client.get(f"/api/v1/runs/{run_id}/outputs")
        assert resp.status_code == 200
        names = {row["name"] for row in resp.json()}
        assert "features.json" in names

    def test_csv_is_downloadable(self, api_client, tmp_path, monkeypatch):
        ws, _home = _isolate_jail(tmp_path, monkeypatch)
        target = ws / "artifacts" / "nightly-compliance"
        target.mkdir(parents=True)
        csv_path = target / "compliance.csv"
        csv_path.write_text("ok,1\n", encoding="utf-8")
        resp = api_client.get("/api/v1/outputs/file", params={"path": str(csv_path)})
        assert resp.status_code == 200
        assert b"ok" in resp.content

    def test_examples_output_stays_inside_jail(self, api_client, tmp_path, monkeypatch):
        _isolate_jail(tmp_path, monkeypatch)
        from app.core.example_templates import examples_dir

        out_dir = examples_dir() / "01_wake_word" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "jail_probe.json"
        target.write_text('{"jail": true}', encoding="utf-8")
        try:
            resp = api_client.get(
                "/api/v1/outputs/file",
                params={"path": "examples/01_wake_word/output/jail_probe.json"},
            )
            assert resp.status_code == 200
            assert resp.json()["jail"] is True
        finally:
            target.unlink(missing_ok=True)
