# unit_test/core/test_run_cleanup_reconcile.py
"""Regression tests for abandoned RUNNING/QUEUED journal reconciliation."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.run_cleanup import cleanup_workspace, reconcile_abandoned_runs


def _write_run(ws: Path, run_id: str, *, status: str, age_hours: float) -> Path:
    run_dir = ws / "runs" / run_id
    run_dir.mkdir(parents=True)
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    meta = {
        "run_id": run_id,
        "created_at": created.isoformat(),
        "status": status,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    ts = time.time() - age_hours * 3600
    os.utime(run_dir, (ts, ts))
    return run_dir


def test_reconcile_marks_stale_running_failed(tmp_workspace: Path):
    zombie = _write_run(tmp_workspace, "zombie-run", status="running", age_hours=3)
    fresh = _write_run(tmp_workspace, "fresh-run", status="running", age_hours=0.1)
    done = _write_run(tmp_workspace, "done-run", status="completed", age_hours=5)

    result = reconcile_abandoned_runs(stale_after_hours=1.0)
    assert result["reconciled"] == 1
    assert "zombie-run" in result["reconciled_run_ids"]
    assert result["skipped_too_new"] >= 1

    zmeta = json.loads((zombie / "meta.json").read_text())
    assert zmeta["status"] == "failed"
    assert zmeta["error"] == "abandoned"
    assert zmeta["reason"] == "stale_reconciled"
    assert "reconciled_at" in zmeta
    assert zombie.exists()
    assert (zombie / "meta.json").exists()

    fmeta = json.loads((fresh / "meta.json").read_text())
    assert fmeta["status"] == "running"

    dmeta = json.loads((done / "meta.json").read_text())
    assert dmeta["status"] == "completed"


def test_reconcile_skips_active_registered_run(tmp_workspace: Path):
    from app.core import run_control

    run_dir = _write_run(tmp_workspace, "active-run", status="running", age_hours=5)

    class _Fake:
        run_id = "active-run"

    run_control._ACTIVE_RUNS["active-run"] = _Fake()  # type: ignore[assignment]
    try:
        result = reconcile_abandoned_runs(stale_after_hours=1.0)
        assert "active-run" not in result["reconciled_run_ids"]
        meta = json.loads((run_dir / "meta.json").read_text())
        assert meta["status"] == "running"
    finally:
        run_control._ACTIVE_RUNS.pop("active-run", None)


def test_reconcile_queued_and_cleanup_hook(tmp_workspace: Path):
    queued = _write_run(tmp_workspace, "queued-run", status="queued", age_hours=2)
    result = cleanup_workspace(
        older_than_days=30,
        delete_cache=False,
        delete_artifacts=False,
        keep_latest=True,
        reconcile_abandoned=True,
        stale_after_hours=1.0,
    )
    assert result["reconcile"]["reconciled"] >= 1
    meta = json.loads((queued / "meta.json").read_text())
    assert meta["status"] == "failed"
    assert meta["reason"] == "stale_reconciled"


def test_reconcile_dry_run_does_not_write(tmp_workspace: Path):
    run_dir = _write_run(tmp_workspace, "dry-run", status="running", age_hours=4)
    result = reconcile_abandoned_runs(stale_after_hours=1.0, dry_run=True)
    assert result["reconciled"] == 1
    assert result["dry_run"] is True
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["status"] == "running"
