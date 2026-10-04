"""Run record (prove.json v2) environment + lineage fixes.

- container detection / image facts / git fallback (env, BUILD_INFO.json)
- per isolated-plugin venv libraries (no symlink-follow into the host env;
  cached per venv + site-packages mtime)
- external inputs are named (node + config key, incl. path literals inside
  python_code sources) and never include the run's own outputs
- input_artifact_hashes exclude artifacts the run produced
- model lineage: declared payload ``lineage.model`` and registered-model
  artifact paths consumed as inputs
- run-level headline metrics = best path's
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core.runs import audit_record as ar


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(root))
    from app.core.runs.audit_hashing import clear_hash_caches

    clear_hash_caches()
    return root


# ── environment ──────────────────────────────────────────────────────────────


def _no_container(monkeypatch):
    monkeypatch.setattr(ar.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ar, "_read_text", lambda p: "")
    for var in ("KUBERNETES_SERVICE_HOST", "container"):
        monkeypatch.delenv(var, raising=False)


def test_detect_container_dockerenv_and_mountinfo(monkeypatch):
    cid = "77306ee04d68a75a257391099ed6593950e40ea34c5057b7d7155157d89e3425"
    mountinfo = (
        f"947 928 259:2 /var/lib/docker/containers/{cid}/hostname /etc/hostname rw - ext4 /dev/x rw\n"
        "100 90 0:1 / /var/lib/docker/overlay2/" + "a" * 64 + "/merged rw - overlay overlay rw\n"
    )
    monkeypatch.setattr(ar.os.path, "exists", lambda p: p == "/.dockerenv")
    monkeypatch.setattr(ar, "_read_text", lambda p: mountinfo if p.endswith("mountinfo") else "0::/\n")
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("container", raising=False)
    info = ar.detect_container()
    assert info["in_container"] is True and info["runtime"] == "docker"
    assert info["container_id"] == cid


def test_host_mountinfo_with_other_containers_is_not_a_container(monkeypatch):
    # The docker HOST's mountinfo lists other containers' shm/overlay mounts.
    mountinfo = (
        "100 90 0:1 / /var/lib/docker/overlay2/" + "a" * 64 + "/merged rw - overlay overlay rw\n"
        "101 90 0:2 / /var/lib/docker/containers/" + "b" * 64 + "/mounts/shm rw - tmpfs shm rw\n"
    )
    monkeypatch.setattr(ar.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ar, "_read_text", lambda p: mountinfo if p.endswith("mountinfo") else "0::/init.scope\n")
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("container", raising=False)
    assert ar.detect_container()["in_container"] is False


def test_cgroup_v1_and_hostname_fallback(monkeypatch):
    cid = "c" * 64
    monkeypatch.setattr(ar.os.path, "exists", lambda p: False)
    monkeypatch.setattr(
        ar, "_read_text",
        lambda p: f"12:pids:/kubepods/burstable/pod1/{cid}\n" if p == "/proc/1/cgroup" else "",
    )
    monkeypatch.delenv("container", raising=False)
    info = ar.detect_container()
    assert info["in_container"] and info["runtime"] == "kubernetes" and info["container_id"] == cid

    monkeypatch.setattr(ar.os.path, "exists", lambda p: p == "/.dockerenv")
    monkeypatch.setattr(ar, "_read_text", lambda p: "0::/\n")
    monkeypatch.setenv("HOSTNAME", "77306ee04d68")
    info = ar.detect_container()
    assert info["container_id"] == "77306ee04d68"


def test_environment_image_and_git_from_env(monkeypatch):
    _no_container(monkeypatch)
    monkeypatch.setenv("GRAPHYN_IMAGE", "graphyn-api:1.4")
    monkeypatch.setenv("GRAPHYN_IMAGE_DIGEST", "sha256:abc")
    monkeypatch.setenv("GRAPHYN_GIT_SHA", "deadbeefcafe")
    env = ar.capture_environment(refresh=True)
    try:
        assert env["image"] == "graphyn-api:1.4@sha256:abc"
        assert env["image_name"] == "graphyn-api:1.4" and env["image_tag"] == "1.4"
        assert env["container_image_digest"] == "sha256:abc"
        assert env["git_commit"] == "deadbeefcafe" and env["git_source"] == "env:GRAPHYN_GIT_SHA"
    finally:
        ar.capture_environment(refresh=True)


def test_container_without_image_env_still_labelled(monkeypatch):
    monkeypatch.setattr(ar.os.path, "exists", lambda p: p == "/.dockerenv")
    monkeypatch.setattr(ar, "_read_text", lambda p: "0::/\n")
    for var in ("GRAPHYN_IMAGE", "GRAPHYN_IMAGE_DIGEST", "KUBERNETES_SERVICE_HOST", "container"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOSTNAME", "77306ee04d68")
    monkeypatch.setattr(ar, "build_info", lambda: {})
    env = ar.capture_environment(refresh=True)
    try:
        assert env["container"]["in_container"] is True
        assert env["image"].startswith("docker container 77306ee04d68")
    finally:
        ar.capture_environment(refresh=True)


def test_git_and_image_from_build_info(tmp_path, monkeypatch):
    info = tmp_path / "BUILD_INFO.json"
    info.write_text(json.dumps({"git_sha": "0123abcd", "image": "graphyn-api:local"}))
    monkeypatch.setenv("GRAPHYN_BUILD_INFO", str(info))
    monkeypatch.delenv("GRAPHYN_GIT_SHA", raising=False)
    monkeypatch.delenv("GRAPHYN_IMAGE", raising=False)
    monkeypatch.delenv("GRAPHYN_IMAGE_DIGEST", raising=False)
    _no_container(monkeypatch)
    assert ar._git_commit_info() == ("0123abcd", "BUILD_INFO.json")
    env = ar.capture_environment(refresh=True)
    try:
        assert env["git_commit"] == "0123abcd" and env["image"] == "graphyn-api:local"
        assert env["build_info"]["git_sha"] == "0123abcd"
    finally:
        ar.capture_environment(refresh=True)


def _fake_venv(root: Path, pkgs: dict[str, str], *, symlink_python: bool = True) -> Path:
    sp = root / "lib" / "python3.12" / "site-packages"
    sp.mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.9\n")
    for name, ver in pkgs.items():
        (sp / f"{name}-{ver}.dist-info").mkdir()
    (root / "bin").mkdir()
    py = root / "bin" / "python"
    if symlink_python:
        host = root.parent / "hostpy" / "bin" / "python3"
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text("")
        hsp = host.parent.parent / "lib" / "python3.12" / "site-packages"
        hsp.mkdir(parents=True, exist_ok=True)
        (hsp / "numpy-1.0.0.dist-info").mkdir(exist_ok=True)
        os.symlink(host, py)
    else:
        py.write_text("")
    return py


def test_venv_environment_reads_venv_not_symlink_target(tmp_path):
    py = _fake_venv(tmp_path / "venv-trainer", {"tensorflow": "2.21.0", "keras": "3.15.1", "numpy": "2.5.3",
                                                "some_dep": "1.0"})
    env = ar.venv_environment(py)
    assert env["libraries"]["tensorflow"] == "2.21.0"
    assert env["libraries"]["numpy"] == "2.5.3"  # venv's, not the host's 1.0.0
    assert "some-dep" not in env["libraries"] and env["package_count"] == 4
    assert env["python"] == "3.12.9" and env["freeze_hash"].startswith("sha256:")
    # cached until site-packages changes
    sp = tmp_path / "venv-trainer" / "lib" / "python3.12" / "site-packages"
    (sp / "onnx-1.17.0.dist-info").mkdir()
    os.utime(sp, ns=(1, 2))
    env2 = ar.venv_environment(py)
    assert env2["libraries"]["onnx"] == "1.17.0" and env2["freeze_hash"] != env["freeze_hash"]


def test_plugin_environments_from_impls(tmp_path):
    py = _fake_venv(tmp_path / "v", {"tensorflow": "2.21.0"}, symlink_python=False)
    impls = {
        "trainer": {"plugin": "trainer", "version": "1.2.0", "runtime": "isolated", "venv_python": str(py)},
        "evaluator": {"plugin": "trainer", "version": "1.2.0", "runtime": "isolated", "venv_python": str(py)},
        "python_code": {"plugin": "python-code", "runtime": "inprocess"},
    }
    envs = ar.plugin_environments(impls)
    assert list(envs) == ["trainer"]
    assert envs["trainer"]["libraries"] == {"tensorflow": "2.21.0"}
    assert envs["trainer"]["plugin_version"] == "1.2.0"
    full = ar.run_environment(impls)
    assert "plugin_environments" in full and "libraries" in full


# ── external inputs ──────────────────────────────────────────────────────────


def test_write_keys():
    for k in ("output_path", "output_dir", "out_dir", "out_file", "export_path", "package_output_path",
              "dest", "save_dir", "output"):
        assert ar.is_write_key(k), k
    for k in ("path", "model_path", "input_dir", "labels_path", "data_dir", "source", "manifest_path"):
        assert not ar.is_write_key(k), k


def _package_graph(model: str, out: str) -> dict:
    return {
        "schema_version": "1.1",
        "metadata": {"name": "edge-deploy"},
        "nodes": [
            {"id": "model_ref", "node_type": "python_code", "label": "Model path",
             "config": {"source": f'output = {{\n  "model_path": "{model}",\n  "labels": ["yes"]\n}}\n'}},
            {"id": "deployment_packager_0", "node_type": "deployment_packager", "label": "Deployment Packager",
             "config": {"output_path": out, "package_output_path": f"{out}/edge_model.tar.gz",
                        "package_name": "edge_model"}},
            {"id": "other", "node_type": "x", "config": {"archive": f"{out}/edge_model.tar.gz"}},
        ],
        "edges": [],
    }


def test_external_inputs_named_and_exclude_outputs(ws):
    model = ws / "artifacts" / "kws" / "runs" / "src123" / "trainer" / "model.keras"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"MODEL")
    out = ws / "artifacts" / "edge-deploy" / "runs" / "pkg1" / "deployment_packager_0"
    out.mkdir(parents=True)
    (out / "edge_model.tar.gz").write_bytes(b"OLD-PACKAGE")  # left over / own output
    graph = _package_graph(
        "workspace/artifacts/kws/runs/src123/trainer/model.keras",
        "workspace/artifacts/edge-deploy/runs/pkg1/deployment_packager_0",
    )
    rows = ar.collect_external_inputs(graph, "pkg1")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["node_id"] == "model_ref" and row["key"] == "source:model_path"
    assert row["label"] == "Model path · source:model_path"
    assert row["path"].endswith("model.keras") and row["kind"] == "file"
    # Not run-scoped output dir but still under this graph's output location.
    graph2 = _package_graph(
        "workspace/artifacts/kws/runs/src123/trainer/model.keras",
        "workspace/artifacts/edge-deploy/packages",
    )
    pkgs = ws / "artifacts" / "edge-deploy" / "packages"
    pkgs.mkdir(parents=True)
    (pkgs / "edge_model.tar.gz").write_bytes(b"PREVIOUS")
    rows2 = ar.collect_external_inputs(graph2, "pkg2")
    assert [r["key"] for r in rows2] == ["source:model_path"]


def test_broad_output_root_does_not_swallow_inputs(ws):
    data = ws / "artifacts" / "kws" / "dataset"
    data.mkdir(parents=True)
    (data / "a.wav").write_bytes(b"x")
    graph = {"nodes": [
        {"id": "r", "node_type": "reader", "config": {"data_dir": "workspace/artifacts/kws/dataset"}},
        {"id": "w", "node_type": "writer", "config": {"output_dir": "workspace/artifacts"}},
    ]}
    rows = ar.collect_external_inputs(graph, "r1")
    assert [r["key"] for r in rows] == ["data_dir"]


def test_input_artifact_hashes_exclude_own_outputs():
    produced = [{"artifact_id": "a1", "content_hash": "h-out"}]
    assert ar._input_artifact_hashes({}, produced) == []
    assert ar._input_artifact_hashes({"input_artifact_hashes": ["h-in", "h-out"]}, produced) == ["h-in"]


# ── model lineage ────────────────────────────────────────────────────────────


def _register(ws: Path, name: str, stage: str, run_id: str, artifact: str) -> None:
    reg = ws / "artifacts" / "_registry" / "models.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(reg.read_text()) if reg.is_file() else {"models": {}}
    data["models"].setdefault(name, {"stages": {}})["stages"][stage] = {
        "run_id": run_id, "slug": "kws", "path": artifact, "artifact_path": artifact, "node_id": "trainer",
    }
    reg.write_text(json.dumps(data))


def test_model_lineage_declared_and_from_inputs(ws):
    model = ws / "artifacts" / "kws" / "runs" / "src123" / "trainer" / "model.keras"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"MODEL")
    rel = "workspace/artifacts/kws/runs/src123/trainer/model.keras"
    _register(ws, "kws-dscnn", "staging", "src123", rel)
    _register(ws, "other", "staging", "zzz", "workspace/artifacts/other/model.keras")

    inputs = ar.collect_external_inputs(_package_graph(rel, "workspace/artifacts/edge-deploy/x"), "p")
    lin = ar.resolve_model_lineage({"source_run_id": "src123"}, inputs)
    assert lin["source_run_id"] == "src123"
    assert [(m["name"], m["stage"], m["match"]) for m in lin["models"]] == [("kws-dscnn", "staging", "input_path")]
    assert lin["models"][0]["model_hash"] == inputs[0]["content_hash"]

    lin2 = ar.resolve_model_lineage(
        {"lineage_request": {"model": {"name": "kws-dscnn", "version": "staging"}}}, []
    )
    m = lin2["models"][0]
    assert (m["name"], m["stage"], m["match"], m["run_id"]) == ("kws-dscnn", "staging", "declared", "src123")
    assert m["model_hash"] and m["artifact_path"] == rel

    unknown = ar.resolve_model_lineage({"lineage_request": {"model": {"name": "nope", "version": "v3"}}}, [])
    assert unknown["models"][0]["resolved"] is False and unknown["models"][0]["version"] == "v3"
    assert ar.resolve_model_lineage({}, []) is None


def test_build_record_carries_lineage_and_model_version(ws):
    model = ws / "artifacts" / "kws" / "m.keras"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"M")
    _register(ws, "kws", "prod", "src1", "workspace/artifacts/kws/m.keras")
    meta = {"lineage_request": {"model": {"name": "kws", "stage": "prod"}}, "external_inputs": [],
            "node_implementations": {"x": {"plugin": None}}, "environment_info": {"python": "3"}}
    run_dir = ws / "runs" / "r1"
    run_dir.mkdir(parents=True)
    rec = ar.build_record(run_dir, run_id="r1", status="succeeded", meta=meta, graph={"nodes": []})
    assert rec["lineage"]["models"][0]["name"] == "kws"
    assert rec["model_version"]["stage"] == "prod" and rec["model_version"]["model_hash"]
    assert rec["environment"]["plugin_environments"] == {}


def test_sanitize_lineage_request():
    from app.core.execution.graph_prepare import sanitize_lineage_request

    assert sanitize_lineage_request({"model": {"name": "kws", "version": "staging", "x": 1}}) == {
        "model": {"name": "kws", "version": "staging"}
    }
    assert sanitize_lineage_request({"model": "kws"}) == {"model": {"name": "kws"}}
    assert sanitize_lineage_request({"model": {"name": "../etc"}}) is None
    assert sanitize_lineage_request("nope") is None


# ── headline metrics ─────────────────────────────────────────────────────────


def test_headline_metrics_picks_best_path():
    from app.core.runs.run_summary import apply_headline_metrics, headline_metrics

    summary = {
        "primary_metric": {"name": "accuracy", "value": 0.91},
        "best_path_id": "B",
        "paths": [
            {"path_id": "A", "label": "Path A · DS-CNN", "metrics": {"accuracy": 0.80, "loss": 0.5}},
            {"path_id": "B", "label": "Path B · MobileNet", "metrics": {"accuracy": 0.91, "loss": 0.3}},
        ],
    }
    head = headline_metrics(summary)
    assert head["path_id"] == "B" and head["metrics"]["accuracy"] == 0.91
    assert [p["best"] for p in head["metrics_by_path"]] == [False, True]
    row = apply_headline_metrics({"metrics": {"accuracy": 0.80, "loss": 0.5}}, summary)
    assert row["metrics"]["accuracy"] == 0.91
    assert row["metrics_first_found"]["accuracy"] == 0.80
    assert row["metrics_path"] == {"path_id": "B", "label": "Path B · MobileNet"}

    # no best_path_id → loss is lower-is-better
    loss_only = {"paths": [
        {"path_id": "A", "label": "A", "metrics": {"val_loss": 0.4}},
        {"path_id": "B", "label": "B", "metrics": {"val_loss": 0.2}},
    ]}
    assert headline_metrics(loss_only)["path_id"] == "B"
    # single path: metrics untouched
    single = {"best_path_id": "A", "paths": [{"path_id": "A", "label": "A", "metrics": {"accuracy": 0.7}}]}
    assert apply_headline_metrics({"metrics": {"accuracy": 0.7, "cm": [[1]]}}, single)["metrics"]["cm"] == [[1]]
    assert headline_metrics(None) is None


def test_persist_run_identity_stores_lineage_request():
    from app.core.execution.graph_prepare import persist_run_identity

    written: dict = {}

    class _RM:
        def _write_meta_field(self, k, v):
            written[k] = v

    persist_run_identity(_RM(), actor="ui-user", trigger="ui",
                         payload={"lineage": {"model": {"name": "kws", "version": "staging"}}})
    assert written["lineage_request"] == {"model": {"name": "kws", "version": "staging"}}
    written.clear()
    persist_run_identity(_RM(), actor="a", trigger="api", payload={"lineage": {"model": {"name": "a b"}}})
    assert "lineage_request" not in written


def test_ship_trigger_and_top_level_lineage_with_stage_and_version(ws):
    from app.core.execution.graph_prepare import normalize_trigger, persist_run_identity

    assert normalize_trigger("ship") == "ship" and normalize_trigger("Ship") == "ship"
    written: dict = {}

    class _RM:
        def _write_meta_field(self, k, v):
            written[k] = v

    # Ship wizard package-run payload: graph + top-level trigger / lineage.
    payload = {"schema_version": "1.1", "nodes": [], "edges": [], "trigger": "ship",
               "source_run_id": "src123",
               "lineage": {"model": {"name": "kws", "stage": "staging", "version": "3"}}}
    persist_run_identity(_RM(), actor="ui", trigger=payload["trigger"], payload=payload)
    assert written["trigger"] == "ship"
    assert written["lineage_request"] == {"model": {"name": "kws", "stage": "staging", "version": "3"}}

    model = ws / "artifacts" / "kws" / "m.keras"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"M")
    _register(ws, "kws", "staging", "src123", "workspace/artifacts/kws/m.keras")
    lin = ar.resolve_model_lineage({**written, "source_run_id": "src123"}, [])
    m = lin["models"][0]
    assert (m["name"], m["stage"], m["match"], m["requested_version"]) == ("kws", "staging", "declared", "3")
    assert m["model_hash"] and lin["source_run_id"] == "src123"
