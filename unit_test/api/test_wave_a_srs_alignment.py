# unit_test/api/test_wave_a_srs_alignment.py
"""Wave A SRS alignment: error envelope, idempotency, run SM, project GET, VAL schema."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestErrorEnvelope:
    def test_http_exception_uses_error_envelope(self, api_client):
        with patch("app.api.routers.run_control.get_active_run", return_value=None), \
             patch("app.api.routers.run_control._runs_dir", return_value=Path("/tmp/nonexistent-runs-xyz")):
            resp = api_client.post("/api/v1/runs/neverexisted999/pause")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
        err = body["error"]
        assert err["code"] in ("run_not_found", "not_found")
        assert "message" in err
        assert "request_id" in err
        assert isinstance(err["retryable"], bool)
        assert "X-Request-Id" in resp.headers
        assert resp.headers["X-Request-Id"] == err["request_id"]
        # Legacy dual-emit
        assert "detail" in body

    def test_client_request_id_propagated(self, api_client):
        resp = api_client.get(
            "/api/v1/projects/does-not-exist-wave-a",
            headers={"X-Request-Id": "client-rid-wave-a"},
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["request_id"] == "client-rid-wave-a"
        assert resp.headers["X-Request-Id"] == "client-rid-wave-a"


class TestIdempotency:
    def test_schedule_create_replay(self, api_client, tmp_workspace):
        from app.api import idempotency as idem

        idem._MEMORY.clear()
        body = {
            "name": "wave-a-sched",
            "project": "p1",
            "pipeline": "pipe1",
            "interval_minutes": 15,
        }
        with patch("app.core.schedules.create_schedule") as create:
            create.return_value = {"id": "sched-1", **body, "enabled": True}
            headers = {"Idempotency-Key": "wave-a-key-1", "X-Actor": "tester"}
            r1 = api_client.post("/api/v1/system/schedules", json=body, headers=headers)
            r2 = api_client.post("/api/v1/system/schedules", json=body, headers=headers)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()
        assert r2.headers.get("Idempotent-Replay") == "true"
        assert create.call_count == 1

    def test_idempotency_conflict_different_body(self, api_client, tmp_workspace):
        from app.api import idempotency as idem

        idem._MEMORY.clear()
        with patch("app.core.schedules.create_schedule") as create:
            create.return_value = {"id": "sched-2", "name": "a"}
            headers = {"Idempotency-Key": "wave-a-key-2", "X-Actor": "tester"}
            api_client.post(
                "/api/v1/system/schedules",
                json={
                    "name": "a",
                    "project": "p",
                    "pipeline": "q",
                    "interval_minutes": 10,
                },
                headers=headers,
            )
            r2 = api_client.post(
                "/api/v1/system/schedules",
                json={
                    "name": "b",
                    "project": "p",
                    "pipeline": "q",
                    "interval_minutes": 10,
                },
                headers=headers,
            )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "idempotency_conflict"


class TestRunStateMachine:
    def test_pause_on_succeeded_returns_409(self, api_client, tmp_workspace):
        runs = Path(tmp_workspace) / "runs" / "runterm1"
        runs.mkdir(parents=True)
        (runs / "meta.json").write_text(json.dumps({"run_id": "runterm1", "status": "succeeded"}))
        with patch("app.api.routers.run_control.get_active_run", return_value=None), \
             patch("app.api.routers.run_control._runs_dir", return_value=Path(tmp_workspace) / "runs"):
            resp = api_client.post("/api/v1/runs/runterm1/pause")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "invalid_transition"

    def test_resume_on_failed_returns_409(self, api_client, tmp_workspace):
        runs = Path(tmp_workspace) / "runs" / "runfail1"
        runs.mkdir(parents=True)
        (runs / "meta.json").write_text(json.dumps({"run_id": "runfail1", "status": "failed"}))
        with patch("app.api.routers.run_control.get_active_run", return_value=None), \
             patch("app.api.routers.run_control._runs_dir", return_value=Path(tmp_workspace) / "runs"):
            resp = api_client.post("/api/v1/runs/runfail1/resume")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "invalid_transition"

    def test_cancel_already_cancelled_idempotent(self, api_client, tmp_workspace):
        runs = Path(tmp_workspace) / "runs" / "runcancel1"
        runs.mkdir(parents=True)
        (runs / "meta.json").write_text(json.dumps({"run_id": "runcancel1", "status": "cancelled"}))
        with patch("app.api.routers.run_control.get_active_run", return_value=None), \
             patch("app.api.routers.run_control._runs_dir", return_value=Path(tmp_workspace) / "runs"):
            resp = api_client.post("/api/v1/runs/runcancel1/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cancelled"
        assert body.get("idempotent") is True

    def test_completed_legacy_maps_to_succeeded_on_read(self, api_client, tmp_workspace):
        runs_root = Path(tmp_workspace) / "runs"
        run_dir = runs_root / "runlegacy1"
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(
            json.dumps({"run_id": "runlegacy1", "status": "completed"})
        )
        with patch("app.api.routers.runs._runs_dir", return_value=runs_root):
            resp = api_client.get("/api/v1/runs/runlegacy1/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    def test_run_manager_starts_pending(self, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.run_journal import RunManager

        # Force re-read of project dir
        import app.core.run_journal as rj

        mgr = RunManager(base_dir=str(Path(tmp_workspace) / "runs"))
        meta = json.loads(Path(mgr.base_path, "meta.json").read_text())
        assert meta["status"] == "pending"
        mgr.mark_running()
        meta2 = json.loads(Path(mgr.base_path, "meta.json").read_text())
        assert meta2["status"] == "running"
        mgr.save_metadata({"num_nodes": 0})
        meta3 = json.loads(Path(mgr.base_path, "meta.json").read_text())
        assert meta3["status"] == "succeeded"


class TestProjectGetPut:
    def test_get_project(self, api_client):
        pm = MagicMock()
        pm.get.return_value = {
            "name": "alpha",
            "display_name": "Alpha",
            "description": "",
            "tags": [],
            "linked_input_labels": [],
            "favorite_pipelines": [],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "resource_version": "1",
        }
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects/alpha")
        assert resp.status_code == 200
        assert resp.json()["name"] == "alpha"
        pm.get.assert_called_once_with("alpha")

    def test_get_missing_project_404_envelope(self, api_client):
        pm = MagicMock()
        pm.get.side_effect = FileNotFoundError("Project 'nope' not found")
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.get("/api/v1/projects/nope")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_put_project(self, api_client):
        pm = MagicMock()
        pm.update.return_value = {
            "name": "alpha",
            "display_name": "Alpha Two",
            "updated_at": "2026-01-02T00:00:00+00:00",
            "resource_version": "2",
        }
        with patch("app.api.routers.projects._pm", pm):
            resp = api_client.put(
                "/api/v1/projects/alpha",
                json={"display_name": "Alpha Two", "tags": ["t1"]},
            )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Alpha Two"
        pm.update.assert_called_once()


class TestValidateSchema:
    def test_validate_unknown_node_returns_val_codes(self, api_client):
        payload = {
            "schema_version": "1.2",
            "metadata": {"name": "t", "seed": 1},
            "nodes": [
                {
                    "id": "n1",
                    "node_type": "definitely_not_a_real_node_type_xyz",
                    "config": {},
                }
            ],
            "edges": [],
        }
        resp = api_client.post("/api/v1/pipelines/validate", json=payload)
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False
        assert isinstance(body["errors"], list) and body["errors"]
        assert body["errors"][0]["code"] == "VAL-UNK-TYPE"
        assert body["errors"][0]["severity"] == "error"
        assert "warnings" in body
        assert "node_count" in body

    def test_validate_ok_shape(self, api_client):
        # Minimal graph that may still warn/err depending on registry; mock result
        result = {
            "valid": True,
            "node_count": 0,
            "edge_count": 0,
            "schema_version": "1.2",
            "errors": [],
            "warnings": [
                {
                    "code": "VAL-EMPTY",
                    "severity": "warning",
                    "message": "Graph has zero nodes",
                    "node_ids": [],
                    "edge_index": None,
                    "field": None,
                }
            ],
        }
        with patch("app.api.routers.pipelines._is_ir_payload", return_value=True), \
             patch("app.core.ir.loader.load_ir") as load_ir, \
             patch("app.core.ir.secret_policy.assert_no_inline_secrets"), \
             patch("app.core.workspace_paths.apply_output_rewire", side_effect=lambda g: g), \
             patch("app.core.validation.validate_graph_ir_result", return_value=result):
            load_ir.return_value = MagicMock(nodes=[], edges=[])
            resp = api_client.post(
                "/api/v1/pipelines/validate",
                json={"schema_version": "1.2", "nodes": [], "edges": [], "metadata": {"name": "x"}},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["warnings"][0]["code"] == "VAL-EMPTY"
