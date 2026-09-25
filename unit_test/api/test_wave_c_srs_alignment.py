# unit_test/api/test_wave_c_srs_alignment.py
"""Wave C SRS alignment: prove capture, drain, store_corrupt helper, SDK transitions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestProveCapture:
    def test_succeeded_run_writes_required_prove_fields(self, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.prove import REQUIRED_PROVE_FIELDS, load_prove_capture, required_fields_present
        from app.core.run_journal import RunManager

        runs = tmp_workspace / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        rm = RunManager(base_dir=str(runs))
        rm.save_graph_ir(
            {
                "schema_version": "1.2",
                "metadata": {"name": "wave-c-prove", "seed": 42},
                "nodes": [],
                "edges": [],
            }
        )
        rm._write_meta_field("actor", "tester")
        rm._write_meta_field("trigger", "api")
        rm._write_meta_field("environment", "draft")
        rm.save_metadata({"graph_name": "wave-c-prove", "dataset_versions": []})

        prove_path = Path(rm.base_path) / "prove.json"
        assert prove_path.exists(), "prove.json must be written on succeeded save_metadata"
        rec = load_prove_capture(rm.base_path)
        assert rec is not None
        missing = required_fields_present(rec)
        assert missing == [], f"missing prove fields: {missing}"
        data = rec.model_dump(mode="json")
        for key in REQUIRED_PROVE_FIELDS:
            assert key in data
        assert data["graph_hash"]
        assert data["seed"] == 42
        assert data["actor"] == "tester"
        assert data["trigger"] == "api"
        assert data["graphyn_version"]
        assert data["runtime_version"]
        assert isinstance(data["dataset_versions"], list)
        assert isinstance(data["plugin_version"], dict)
        assert isinstance(data["node_implementation_versions"], dict)

    def test_provenance_optional_fields_roundtrip(self, tmp_workspace):
        from app.core.provenance import ProvenanceStore

        store = ProvenanceStore(base_dir=str(tmp_workspace))
        rec = store.record(
            artifact_id="art-wave-c",
            run_id="run-wave-c",
            node_id="n1",
            node_type="clean",
            graph_hash="abc",
            input_artifact_ids=[],
            plugin_versions={"demo": "1.0"},
            worker_id=None,
            actor="tester",
            dataset_refs=[],
        )
        assert rec.plugin_versions == {"demo": "1.0"}
        assert rec.actor == "tester"
        loaded = store.find_by_run("run-wave-c")
        assert loaded and loaded[0].plugin_versions == {"demo": "1.0"}


class TestShutdownDrain:
    def test_is_draining_refuses_new_async_run(self, api_client, monkeypatch, tmp_workspace):
        monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
        from app.core.shutdown import begin_drain, reset_drain_for_tests

        reset_drain_for_tests()
        begin_drain()
        try:
            resp = api_client.post(
                "/api/v1/pipelines/run-async",
                json={
                    "schema_version": "1.2",
                    "metadata": {"name": "x", "seed": 0},
                    "nodes": [],
                    "edges": [],
                },
            )
            assert resp.status_code == 503
            body = resp.json()
            detail = body.get("detail") or body.get("error") or body
            blob = json.dumps(detail)
            assert "draining" in blob.lower() or "shutting down" in blob.lower()
        finally:
            reset_drain_for_tests()

    def test_drain_active_runs_summary(self, tmp_workspace, monkeypatch):
        monkeypatch.setenv("GRAPHYN_SHUTDOWN_GRACE_S", "0")
        from app.core.shutdown import drain_active_runs, reset_drain_for_tests

        reset_drain_for_tests()
        summary = drain_active_runs(grace_seconds=0)
        assert "grace_seconds" in summary
        assert isinstance(summary["cancelled"], list)
        reset_drain_for_tests()


class TestStoreCorruptHelper:
    def test_artifacts_list_503_when_readiness_corrupt(self, api_client, monkeypatch):
        # Only monkeypatch — nested unittest.mock.patch + monkeypatch can restore the
        # mock *after* patch teardown and leak into later tests.
        monkeypatch.setattr(
            "app.core.store_integrity.readiness_store_corrupt",
            lambda: True,
        )
        resp = api_client.get("/api/v1/artifacts")
        assert resp.status_code == 503
        text = resp.text.lower()
        assert "store_corrupt" in text


class TestSdkPauseResume:
    def test_pause_without_run_raises_invalid_transition(self):
        from app.core.run_status import InvalidTransition
        from app.core.sdk import Pipeline

        p = Pipeline([], name="sdk-wave-c")
        with pytest.raises(InvalidTransition):
            p.pause()

    def test_resume_without_run_raises_invalid_transition(self):
        from app.core.run_status import InvalidTransition
        from app.core.sdk import Pipeline

        p = Pipeline([], name="sdk-wave-c-2")
        with pytest.raises(InvalidTransition):
            p.resume()


class TestPaginationDefaultOn:
    def test_parse_envelope_flag_default_and_escape(self):
        from app.api.pagination import parse_envelope_flag, maybe_envelope

        assert parse_envelope_flag(None) is True
        assert parse_envelope_flag("1") is True
        assert parse_envelope_flag("true") is True
        assert parse_envelope_flag("0") is False
        assert parse_envelope_flag("false") is False
        assert parse_envelope_flag("no") is False
        assert parse_envelope_flag("off") is False
        assert isinstance(maybe_envelope([1], envelope=True), dict)
        assert maybe_envelope([1], envelope=False) == [1]

    def test_projects_default_envelope_and_escape(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "app.core.store_integrity.readiness_store_corrupt",
            lambda: False,
        )
        env = api_client.get("/api/v1/projects")
        assert env.status_code == 200
        body = env.json()
        assert isinstance(body, dict)
        assert "items" in body
        bare = api_client.get("/api/v1/projects?envelope=0")
        assert bare.status_code == 200
        assert isinstance(bare.json(), list)


class TestStoreCorruptUniversal:
    def test_projects_list_503_when_readiness_corrupt(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "app.core.store_integrity.readiness_store_corrupt",
            lambda: True,
        )
        resp = api_client.get("/api/v1/projects")
        assert resp.status_code == 503
        assert "store_corrupt" in resp.text.lower()

    def test_runs_list_503_when_readiness_corrupt(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "app.core.store_integrity.readiness_store_corrupt",
            lambda: True,
        )
        resp = api_client.get("/api/v1/runs")
        assert resp.status_code == 503
        assert "store_corrupt" in resp.text.lower()

    def test_models_list_503_when_readiness_corrupt(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "app.core.store_integrity.readiness_store_corrupt",
            lambda: True,
        )
        resp = api_client.get("/api/v1/models")
        assert resp.status_code == 503
        assert "store_corrupt" in resp.text.lower()

    def test_plugins_list_503_when_readiness_corrupt(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "app.core.store_integrity.readiness_store_corrupt",
            lambda: True,
        )
        resp = api_client.get("/api/v1/plugins")
        assert resp.status_code == 503
        assert "store_corrupt" in resp.text.lower()

