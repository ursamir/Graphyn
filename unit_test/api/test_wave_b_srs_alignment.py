# unit_test/api/test_wave_b_srs_alignment.py
"""Wave B SRS alignment: If-Match, audit schema, envelope, readiness, datasets, cancel-artifact."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


class TestIfMatch:
    def test_pipeline_put_if_match_mismatch_412(self, api_client, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.domain.project_manager import ProjectManager
        from app.core.project_pipelines import put_pipeline
        from app.core.ir.loader import CURRENT_IR_VERSION

        pm = ProjectManager()
        pm.create("waveb1")
        project_dir = pm._require_project("waveb1")
        graph = {
            "schema_version": CURRENT_IR_VERSION,
            "metadata": {"name": "p1", "seed": 0},
            "nodes": [],
            "edges": [],
        }
        put_pipeline(project_dir, "p1", graph, project_name="waveb1")
        resp = api_client.put(
            "/api/v1/projects/waveb1/pipelines/p1",
            json=graph,
            headers={"If-Match": '"999999999999"'},
        )
        assert resp.status_code == 412
        body = resp.json()
        assert body["error"]["code"] in ("precondition_failed", "version_conflict")

    def test_webhook_resource_version_roundtrip(self, api_client, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        # Clear webhook cache
        from app.core.webhook import WebhookService

        WebhookService._class_config_cache = None
        r1 = api_client.get("/api/v1/system/webhooks")
        assert r1.status_code == 200
        rv = r1.json().get("resource_version")
        assert rv is not None
        r2 = api_client.put(
            "/api/v1/system/webhooks",
            json={"url": "", "events": [], "resource_version": "bogus"},
        )
        assert r2.status_code in (409, 412)
        r3 = api_client.put(
            "/api/v1/system/webhooks",
            json={"url": "", "events": ["run.succeeded"]},
            headers={"If-Match": f'"{rv}"'},
        )
        assert r3.status_code == 200
        assert "resource_version" in r3.json() or "ETag" in r3.headers


class TestAuditSchema:
    def test_record_audit_has_timestamp_result_request_id(self, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.audit import list_audit, record_audit

        ev = record_audit(
            actor="tester",
            action="test.action",
            resource_type="test",
            resource_id="1",
            meta={"k": "v"},
            result="success",
            request_id="rid-wave-b",
            actor_kind="human",
            base_dir=tmp_workspace,
        )
        assert "timestamp" in ev
        assert ev.get("ts") == ev["timestamp"]
        assert ev["result"] == "success"
        assert ev["request_id"] == "rid-wave-b"
        assert ev["actor_kind"] == "human"
        listed = list_audit(limit=5, base_dir=tmp_workspace)
        assert listed
        assert "timestamp" in listed[0]
        assert "result" in listed[0]


class TestEnvelope:
    def test_nodes_envelope_default_on_and_escape(self, api_client):
        # P1: omitted query → envelope
        env = api_client.get("/api/v1/nodes?limit=5")
        assert env.status_code == 200
        body = env.json()
        assert "items" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body
        # Escape hatch: envelope=0 → bare array
        bare = api_client.get("/api/v1/nodes?envelope=0")
        assert bare.status_code == 200
        assert isinstance(bare.json(), list)
        # Explicit envelope=1 still works
        env1 = api_client.get("/api/v1/nodes?envelope=1&limit=5")
        assert env1.status_code == 200
        assert "items" in env1.json()


class TestReadiness:
    def test_ready_boolean_and_signals(self, api_client, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        resp = api_client.get("/api/v1/system/readiness")
        assert resp.status_code == 200
        body = resp.json()
        assert "ready" in body
        assert isinstance(body["ready"], bool)
        assert "status" in body
        checks = body.get("checks") or {}
        assert "store_corrupt" in checks
        assert "disk_full" in checks


class TestDatasetVersion:
    def test_force_delete_referenced_409(self, api_client, tmp_path, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.config import datasets_output_dir, runs_dir
        from app.core.dataset_versions import write_manifest

        out = datasets_output_dir() / "dsproj" / "v1"
        out.mkdir(parents=True)
        (out / "sample.txt").write_text("hello", encoding="utf-8")
        write_manifest(out)

        # Create a run meta that references the version
        rdir = runs_dir() / "runref1"
        rdir.mkdir(parents=True)
        (rdir / "meta.json").write_text(
            json.dumps(
                {
                    "run_id": "runref1",
                    "status": "succeeded",
                    "dataset_versions": [{"project": "dsproj", "version": "v1"}],
                }
            )
        )

        with patch("app.api.routers.data._output_root", return_value=datasets_output_dir()):
            resp = api_client.delete("/api/v1/data/outputs/dsproj/v1")
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] in ("conflict", "version_in_use")

        with patch("app.api.routers.data._output_root", return_value=datasets_output_dir()):
            resp2 = api_client.delete("/api/v1/data/outputs/dsproj/v1?force=true")
        assert resp2.status_code == 200

    def test_get_includes_content_hash(self, api_client, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.config import datasets_output_dir
        from app.core.dataset_versions import write_manifest

        out = datasets_output_dir() / "dsproj2" / "v1"
        out.mkdir(parents=True)
        (out / "a.txt").write_text("x", encoding="utf-8")
        write_manifest(out)
        with patch("app.api.routers.data._output_root", return_value=datasets_output_dir()):
            resp = api_client.get("/api/v1/data/outputs/dsproj2/v1")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("content_hash")
        assert "files" in body


class TestArtifactCommitAfterCancel:
    def test_register_artifact_forbidden_when_cancelled(self, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.run_journal import ArtifactCommitForbidden, RunManager

        mgr = RunManager(base_dir=str(Path(tmp_workspace) / "runs"))
        mgr.cancel()
        mgr.mark_cancelled()
        with pytest.raises(ArtifactCommitForbidden):
            mgr.register_artifact(
                node_id="n1",
                node_type="passthrough",
                artifact_type="json",
                data={"ok": True},
            )
