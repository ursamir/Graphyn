"""Mode B fixes — cleanup must not delete live data (aliases, model stages,
shared deduplicated artifacts), artifact store locking, blob TTL sweep."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.runs.run_cleanup import (
    RunInProgressError,
    RunProtectedError,
    cleanup_workspace,
    delete_run,
    protected_run_ids,
)


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    """Real threads needed for the concurrent-register test."""
    yield


@pytest.fixture
def ws(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(root))
    from app.core.distributed.queue import _reset_job_queue

    _reset_job_queue()
    yield root
    _reset_job_queue()


def _run(ws: Path, run_id: str, slug: str = "demo", age_days: float = 10) -> Path:
    d = ws / "runs" / run_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "completed",
        "graph_name": slug,
        "artifacts_dir": f"workspace/artifacts/{slug}/runs/{run_id}",
    }))
    art = ws / "artifacts" / slug / "runs" / run_id
    art.mkdir(parents=True)
    (art / "model.bin").write_bytes(b"weights")
    ts = time.time() - age_days * 86400
    os.utime(d, (ts, ts))
    os.utime(art, (ts, ts))
    return d


# ── 5. aliases / model stages protect runs ──────────────────────────────────


def test_prod_alias_protects_run_from_cleanup_and_delete(ws: Path):
    from app.core.paths.workspace_paths import publish_alias

    _run(ws, "prod-run")
    _run(ws, "old-run")
    publish_alias("demo", "prod-run", "prod")
    assert "prod-run" in protected_run_ids()

    res = cleanup_workspace(older_than_days=0, delete_artifacts=True, keep_latest=False,
                            reconcile_abandoned=False)
    assert res["runs_skipped_protected"] == 1
    assert (ws / "runs" / "prod-run").is_dir()
    assert (ws / "artifacts" / "demo" / "runs" / "prod-run" / "model.bin").is_file()
    assert not (ws / "runs" / "old-run").exists()

    with pytest.raises(RunProtectedError) as ei:
        delete_run("prod-run")
    assert isinstance(ei.value, RunInProgressError)  # → HTTP 409 in runs router
    delete_run("prod-run", force=True)
    assert not (ws / "runs" / "prod-run").exists()


def test_alias_json_pointer_fallback_is_protected(ws: Path):
    _run(ws, "staged")
    slug_dir = ws / "artifacts" / "demo"
    (slug_dir / "staging.json").write_text(json.dumps(
        {"run_id": "staged", "path": "workspace/artifacts/demo/runs/staged",
         "alias": "staging"}))
    assert protected_run_ids()["staged"] == ["alias:demo/staging"]


def test_model_registry_stage_protects_run(ws: Path):
    from app.core.mlops.model_registry import register_model

    _run(ws, "model-run")
    register_model("clf", run_id="model-run", slug="demo", stage="staging")
    reasons = protected_run_ids()["model-run"]
    assert "model:clf@staging" in reasons
    # Remove the alias link; the registry record alone still protects it.
    alias = ws / "artifacts" / "demo" / "staging"
    if alias.is_symlink():
        alias.unlink()
    assert "model:clf@staging" in protected_run_ids()["model-run"]
    cleanup_workspace(older_than_days=0, delete_artifacts=True, keep_latest=False,
                      reconcile_abandoned=False)
    assert (ws / "runs" / "model-run").is_dir()


def test_latest_is_not_protected_by_default(ws: Path):
    from app.core.paths.workspace_paths import publish_latest

    _run(ws, "latest-run")
    publish_latest("demo", "latest-run")
    assert "latest-run" not in protected_run_ids()
    assert "latest-run" in protected_run_ids(include_latest=True)


# ── 5. ArtifactStore: reference-counted purge / protected age cleanup ───────


def _store(ws: Path):
    from app.core.artifacts.artifact_store import ArtifactStore

    return ArtifactStore()


def test_purge_run_keeps_artifact_shared_by_another_run(ws: Path):
    store = _store(ws)
    rec_a, dedup_a = store.register("run-a", "n", "t", "generic", {"x": 1})
    rec_b, dedup_b = store.register("run-b", "n", "t", "generic", {"x": 1})
    assert not dedup_a and dedup_b and rec_a.artifact_id == rec_b.artifact_id
    aid = rec_a.artifact_id

    assert store.purge_run("run-a") == 0  # owner purged, run-b still references it
    assert (store.base / aid / "record.json").is_file()
    assert [r.artifact_id for r in store.list(run_id="run-b")] == [aid]

    assert store.purge_run("run-b") == 1  # last reference gone
    assert not (store.base / aid).exists()
    index = json.loads((store.base / "index.json").read_text())
    assert rec_a.content_hash not in index


def test_purge_non_owner_keeps_artifact_of_live_owner(ws: Path):
    store = _store(ws)
    rec, _ = store.register("owner", "n", "t", "generic", {"y": 2})
    store.register("borrower", "n", "t", "generic", {"y": 2})
    (store.base / "by_run" / "owner.json").unlink()  # lost membership file
    (ws / "runs" / "owner").mkdir(parents=True)  # owner journal still exists
    assert store.purge_run("borrower") == 0
    assert (store.base / rec.artifact_id).is_dir()


def _age_record(store, aid: str, days: int) -> None:
    path = store.base / aid / "record.json"
    data = json.loads(path.read_text())
    data["created_at"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    path.write_text(json.dumps(data))
    ts = time.time() - days * 86400
    for f in (store.base / "by_run").iterdir():
        os.utime(f, (ts, ts))


def test_age_cleanup_skips_artifacts_of_protected_runs(ws: Path):
    from app.core.paths.workspace_paths import publish_alias

    store = _store(ws)
    keep, _ = store.register("prod-run", "n", "t", "generic", {"p": 1})
    drop, _ = store.register("junk-run", "n", "t", "generic", {"j": 1})
    _age_record(store, keep.artifact_id, 90)
    _age_record(store, drop.artifact_id, 90)
    (ws / "artifacts" / "demo" / "runs" / "prod-run").mkdir(parents=True)
    publish_alias("demo", "prod-run", "prod")

    out = store.cleanup(older_than_days=30)
    assert out["entries_deleted"] == 1
    assert out["skipped_referenced"] == 1
    assert (store.base / keep.artifact_id).is_dir()
    assert not (store.base / drop.artifact_id).exists()


def test_age_cleanup_skips_recently_deduplicated_artifact(ws: Path):
    store = _store(ws)
    rec, _ = store.register("ancient", "n", "t", "generic", {"d": 1})
    _age_record(store, rec.artifact_id, 90)
    store.register("fresh", "n", "t", "generic", {"d": 1})  # dedup hit today
    assert store.cleanup(older_than_days=30)["entries_deleted"] == 0
    assert (store.base / rec.artifact_id).is_dir()


# ── 11. ArtifactStore single exclusive lock + unique temp names ─────────────


def test_concurrent_register_across_instances_loses_nothing(ws: Path):
    from app.core.artifacts.artifact_store import ArtifactStore

    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            s = ArtifactStore()  # separate instance → separate threading lock
            s.register(f"run-{i % 3}", f"n{i}", "t", "generic", {"i": i}, name="shared-name")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    s = ArtifactStore()
    index = json.loads((s.base / "index.json").read_text())
    assert len(index) == 24
    assert len(s.get_versions("shared-name")) == 24
    assert sum(len(s.list(run_id=f"run-{k}")) for k in range(3)) == 24
    assert not list(s.base.rglob("*.json.tmp"))


def test_index_writes_use_unique_temp_names(ws: Path, monkeypatch):
    store = _store(ws)
    seen: list[str] = []
    real = Path.replace

    def spy(self, target):
        seen.append(self.name)
        return real(self, target)

    monkeypatch.setattr(Path, "replace", spy)
    store.register("r", "n", "t", "generic", {"z": 1}, name="nm")
    assert seen
    assert all(not n.endswith(".json.tmp") for n in seen)
    assert len(set(seen)) == len(seen)


# ── 8. distributed blob TTL sweep in cleanup_workspace ──────────────────────


def test_cleanup_sweeps_old_blobs_but_keeps_active_job_refs(ws: Path, monkeypatch):
    from app.core.distributed.models import NodeJob
    from app.core.distributed.queue import get_job_queue
    from app.core.distributed.transfer import _safe_path, put_blob, uri_to_key

    monkeypatch.setenv("GRAPHYN_DISTRIBUTED_BLOB_TTL_S", "3600")
    old_orphan = put_blob(b"orphan")
    old_input = put_blob(b"active-input")
    old_output = put_blob(b"active-out", key="jobs/live-job/g0/out")
    fresh = put_blob(b"fresh")
    past = time.time() - 7200
    for uri in (old_orphan, old_input, old_output):
        os.utime(_safe_path(uri_to_key(uri)), (past, past))
    get_job_queue().enqueue(NodeJob(job_id="live-job", run_id="r", node_id="n",
                                    node_type="x", input_refs={"i": old_input}))

    res = cleanup_workspace(older_than_days=7, reconcile_abandoned=False)
    assert res["blobs_deleted"] == 1
    assert not _safe_path(uri_to_key(old_orphan)).exists()
    for uri in (old_input, old_output, fresh):
        assert _safe_path(uri_to_key(uri)).is_file()
