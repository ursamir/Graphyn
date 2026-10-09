"""DIST-ORPHAN-1: in-flight runs whose owning process died are failed with
``orphaned_by_restart`` (meta, journal event, audit) instead of staying
``running`` forever; live owners — this process, a fresh heartbeat, an alive
pid — are never touched. Covers Mode A (in-process RunManager) and Mode B
(queued/claimed remote jobs are cancelled)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.runs import orphans


def _run(root: Path, run_id: str, *, status="running", owner=None, created=None, hb_age=None) -> Path:
    d = root / run_id
    d.mkdir(parents=True)
    meta = {"run_id": run_id, "status": status, "created_at": (created or datetime.now(timezone.utc)).isoformat(),
            "actor": "alice", "project": "p1"}
    if owner is not None:
        meta["owner"] = owner
        (d / orphans.OWNER_FILE).write_text(json.dumps({"run_id": run_id, **owner}))
        if hb_age is not None:
            t = time.time() - hb_age
            os.utime(d / orphans.OWNER_FILE, (t, t))
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "logs.json").write_text(json.dumps([{"type": "node_start", "node_id": "train"}]))
    return d


@pytest.fixture()
def audit(monkeypatch):
    rows = []
    monkeypatch.setattr("app.core.trust.audit.record_audit", lambda **kw: rows.append(kw))
    monkeypatch.setattr("app.core.runs.audit_record.seal_run_record", lambda *a, **k: None)
    return rows


def _dead_same_host(pid_offset=0):
    st = orphans.owner_stamp()
    return {**st, "boot_id": "old-boot", "proc_start": "1"}  # same pid, different process start


def test_restarted_owner_same_host_is_orphaned(tmp_path, audit):
    d = _run(tmp_path, "r1", owner=_dead_same_host(), hb_age=2)  # heartbeat fresh, but pid reused
    res = orphans.sweep_orphaned_runs(detected_by="startup", runs_root=tmp_path)
    assert res["orphaned"] == ["r1"]
    meta = json.loads((d / "meta.json").read_text())
    assert meta["status"] == "failed"
    assert meta["error_type"] == "orphaned_by_restart" and meta["reason"] == "orphaned_by_restart"
    assert meta["error"].startswith("orphaned_by_restart: ")
    assert meta["orphan"]["detected_by"] == "startup" and meta["orphan"]["last_status"] == "running"
    assert meta["orphan"]["previous_owner"]["boot_id"] == "old-boot"
    ev = json.loads((d / "logs.json").read_text())[-1]
    assert ev["type"] == "error" and ev["error_type"] == "orphaned_by_restart"
    (row,) = audit
    assert row["action"] == "run.orphaned" and row["resource_id"] == "r1"
    assert row["error_code"] == "orphaned_by_restart" and row["result"] == "failure"
    assert row["meta"]["started_by"] == "alice"


def test_live_owners_are_left_alone(tmp_path, audit):
    other_host = {"boot_id": "b2", "host": "some-other-host", "pid": 4242, "proc_start": "9"}
    _run(tmp_path, "fresh-remote", owner=other_host, hb_age=5)
    live_here = {**orphans.owner_stamp(), "boot_id": "another-process"}  # this pid + start → alive
    _run(tmp_path, "same-pid-alive", owner=live_here, hb_age=1)
    _run(tmp_path, "done", status="succeeded", owner=_dead_same_host(), hb_age=999)
    res = orphans.sweep_orphaned_runs(runs_root=tmp_path)
    assert res["orphaned"] == [] and res["alive"] == 2 and audit == []


def test_stale_remote_heartbeat_and_dead_pid_are_orphans(tmp_path, audit, monkeypatch):
    monkeypatch.setenv("GRAPHYN_RUN_OWNER_STALE_S", "30")
    _run(tmp_path, "stale", owner={"boot_id": "b2", "host": "gone-host", "pid": 7, "proc_start": "1"}, hb_age=120)
    _run(tmp_path, "deadpid", owner={**orphans.owner_stamp(), "boot_id": "b3", "pid": 2 ** 22 + 11})
    res = orphans.sweep_orphaned_runs(runs_root=tmp_path)
    assert sorted(res["orphaned"]) == ["deadpid", "stale"]


def test_legacy_run_without_owner(tmp_path, audit):
    _run(tmp_path, "legacy-old", created=datetime.now(timezone.utc) - timedelta(hours=2))
    _run(tmp_path, "legacy-new", created=datetime.now(timezone.utc) + timedelta(seconds=5))
    assert orphans.sweep_orphaned_runs(runs_root=tmp_path)["orphaned"] == ["legacy-old"]


def test_cancel_requested_orphan_becomes_cancelled(tmp_path, audit):
    d = _run(tmp_path, "c1", status="running", owner=_dead_same_host())
    (d / "cancel_requested").write_text("x")
    orphans.sweep_orphaned_runs(runs_root=tmp_path)
    assert json.loads((d / "meta.json").read_text())["status"] == "cancelled"


def test_mode_a_run_manager_is_owned_and_heartbeated(tmp_path, audit, monkeypatch):
    monkeypatch.setenv("GRAPHYN_RUN_HEARTBEAT_S", "0.05")
    from app.core.runs.run_journal import RunManager

    rm = RunManager(base_dir=str(tmp_path))
    meta = json.loads((Path(rm.base_path) / "meta.json").read_text())
    assert meta["owner"]["boot_id"] == orphans.BOOT_ID and meta["owner"]["pid"] == os.getpid()
    owner_file = Path(rm.base_path) / orphans.OWNER_FILE
    old = time.time() - 100
    os.utime(owner_file, (old, old))
    assert orphans.heartbeat_once() >= 1 and time.time() - owner_file.stat().st_mtime < 5
    rm.mark_running()
    assert orphans.sweep_orphaned_runs(runs_root=tmp_path)["orphaned"] == []
    # Process "lost" the run (e.g. executor thread died without a terminal status)
    orphans.release_run(rm.run_id)
    assert orphans.sweep_orphaned_runs(runs_root=tmp_path)["orphaned"] == [rm.run_id]
    rm.mark_failed("late")  # first terminal status wins — no overwrite
    assert json.loads((Path(rm.base_path) / "meta.json").read_text())["error_type"] == "orphaned_by_restart"


def test_mode_b_orphan_cancels_remote_jobs(tmp_path, audit, monkeypatch):
    from app.core.distributed.models import NodeJob
    from app.core.distributed.queue import JobQueue

    q = JobQueue(lease_ttl_s=30, load_persisted=False)
    q.enqueue(NodeJob(job_id="jb1", run_id="rb", node_id="ff", node_type="feature_extractor"))
    q.enqueue(NodeJob(job_id="jb2", run_id="other", node_id="x", node_type="trainer"))
    monkeypatch.setattr("app.core.distributed.queue.get_job_queue", lambda: q)
    d = _run(tmp_path, "rb", owner=_dead_same_host())
    orphans.sweep_orphaned_runs(runs_root=tmp_path)
    assert q.get("jb1").status == "cancelled" and q.get("jb2").status == "pending"
    meta = json.loads((d / "meta.json").read_text())
    assert meta["orphan"]["cancelled_jobs"] == ["jb1"] and "1 queued/claimed remote job(s) were cancelled" in meta["error"]


def test_sweep_cycle_also_reclaims_expired_leases(tmp_path, monkeypatch):
    class _Q:
        def reclaim_expired_leases(self):
            return ["j9"]

        def active_jobs(self):
            return []

    monkeypatch.setattr("app.core.distributed.queue.get_job_queue", lambda: _Q())
    monkeypatch.setattr("app.core.config.runs_dir", lambda: tmp_path)
    assert orphans.run_sweep_cycle()["requeued_jobs"] == ["j9"]
