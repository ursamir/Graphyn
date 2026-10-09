"""Data-store fixes — model registry gate/run checks + dataset versions.

Regressions: register_model accepted nonexistent runs and publish_alias
created empty run dirs; POST /models stage=prod bypassed request→approve;
registry RMW unlocked; dataset manifest shared one ``.json.tmp``; the
dataset delete guard ignored run graph.json.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest


_REAL_THREAD_START = threading.Thread.start  # captured at collection time


@pytest.fixture(autouse=True)
def patch_threads():
    """Real threads: these tests exercise concurrency.

    Overrides conftest's no-op patch and also guards against another test
    having leaked a patched ``Thread.start`` (restored afterwards unchanged).
    """
    saved = threading.Thread.start
    threading.Thread.start = _REAL_THREAD_START
    try:
        yield
    finally:
        threading.Thread.start = saved


def _seed_run(ws: Path, run_id: str, *, status: str = "succeeded", slug: str = "demo",
              artifacts: bool = True) -> None:
    d = ws / "runs" / run_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"run_id": run_id, "status": status}))
    if artifacts:
        art = ws / "artifacts" / slug / "runs" / run_id
        art.mkdir(parents=True)
        (art / "model.bin").write_bytes(b"w")


# ── model registry ─────────────────────────────────────────────────────────


def test_register_nonexistent_run_rejected_and_no_dir_created(tmp_workspace: Path):
    from app.core.mlops.model_registry import ModelRunNotFound, register_model

    with pytest.raises(ModelRunNotFound):
        register_model("m", run_id="ghost", slug="demo")
    assert not (tmp_workspace / "artifacts" / "demo" / "runs" / "ghost").exists()


def test_register_failed_run_rejected(tmp_workspace: Path):
    from app.core.mlops.model_registry import ModelRunNotSucceeded, register_model

    _seed_run(tmp_workspace, "r-failed", status="failed")
    with pytest.raises(ModelRunNotSucceeded):
        register_model("m", run_id="r-failed", slug="demo")


def test_register_run_without_artifacts_rejected(tmp_workspace: Path):
    from app.core.mlops.model_registry import ModelRunNotFound, register_model

    _seed_run(tmp_workspace, "r-noart", artifacts=False)
    with pytest.raises(ModelRunNotFound):
        register_model("m", run_id="r-noart", slug="demo")
    assert not (tmp_workspace / "artifacts" / "demo" / "runs" / "r-noart").exists()


def test_publish_alias_never_creates_run_dir(tmp_workspace: Path):
    from app.core.paths.workspace_paths import publish_alias

    with pytest.raises(FileNotFoundError):
        publish_alias("demo", "nope", "staging")
    assert not (tmp_workspace / "artifacts" / "demo" / "runs" / "nope").exists()


def test_legacy_completed_status_is_accepted(tmp_workspace: Path):
    from app.core.mlops.model_registry import register_model

    _seed_run(tmp_workspace, "r-old", status="completed")
    rec = register_model("m", run_id="r-old", slug="demo")
    assert rec["stages"]["staging"]["run_id"] == "r-old"


def test_direct_prod_rejected_but_approve_path_works(tmp_workspace: Path):
    from app.core.mlops.model_registry import (
        ProdRequiresApproval,
        approve_prod,
        register_model,
        request_prod,
    )

    _seed_run(tmp_workspace, "r1")
    with pytest.raises(ProdRequiresApproval):
        register_model("m", run_id="r1", slug="demo", stage="prod")
    register_model("m", run_id="r1", slug="demo", stage="staging")
    request_prod("m", actor="alice")
    done = approve_prod("m", actor="bob")
    assert done["stages"]["prod"]["run_id"] == "r1"
    assert done["pending_prod"] is None


def test_concurrent_register_keeps_every_model(tmp_workspace: Path):
    from app.core.mlops.model_registry import list_models, register_model

    n = 8
    for i in range(n):
        _seed_run(tmp_workspace, f"r{i}")
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def go(i: int) -> None:
        barrier.wait()
        try:
            register_model(f"model{i}", run_id=f"r{i}", slug="demo", stage="latest")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert {m["name"] for m in list_models()} == {f"model{i}" for i in range(n)}


def test_models_api_status_codes(api_client, tmp_workspace: Path):
    _seed_run(tmp_workspace, "ok-run")
    _seed_run(tmp_workspace, "run-running", status="running")
    base = {"name": "api-m", "slug": "demo"}

    r = api_client.post("/api/v1/models", json={**base, "run_id": "missing"})
    assert r.status_code == 404
    r = api_client.post("/api/v1/models", json={**base, "run_id": "run-running"})
    assert r.status_code == 409
    r = api_client.post("/api/v1/models", json={**base, "run_id": "ok-run", "stage": "prod"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "prod_requires_approval"
    r = api_client.post("/api/v1/models", json={**base, "run_id": "ok-run"})
    assert r.status_code == 200


# ── dataset versions ───────────────────────────────────────────────────────


def test_concurrent_write_manifest_no_tmp_collision(tmp_path: Path):
    from app.core.mlops.dataset_versions import read_manifest, write_manifest

    vdir = tmp_path / "v1"
    vdir.mkdir()
    (vdir / "a.wav").write_bytes(b"abc")
    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def go(_i: int) -> None:
        barrier.wait()
        try:
            for _ in range(20):
                write_manifest(vdir)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    man = read_manifest(vdir, ensure=False)
    assert [f["path"] for f in man["files"]] == ["a.wav"]
    assert not list(vdir.glob("*.tmp")) and not list(vdir.glob(".*.tmp"))


def test_find_references_scans_run_graph_json(tmp_path: Path):
    from app.core.mlops.dataset_versions import find_references

    run = tmp_path / "runs" / "r-graph"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"run_id": "r-graph", "status": "succeeded"}))
    (run / "graph.json").write_text(json.dumps({
        "nodes": [{"id": "ingest", "type": "dataset_ingest",
                   "config": {"path": "workspace/datasets/output/proj/v3"}}],
    }))
    refs = find_references("proj", "v3", base_dir=tmp_path)
    assert {"kind": "run", "id": "r-graph"} in refs
    assert find_references("proj", "v4", base_dir=tmp_path) == []
