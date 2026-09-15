# unit_test/core/test_schedules.py
"""Tests for app.core.schedules (always-on lite)."""
from __future__ import annotations

import json
import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.schedules import (
    SchedulesDataError,
    create_schedule,
    delete_schedule,
    list_schedules,
    schedules_path,
    set_schedule_enabled,
    tick_due_schedules,
)


def test_create_list_delete_schedule(tmp_path: Path):
    item = create_schedule(
        name="hourly",
        project="demo",
        pipeline="main",
        interval_minutes=30,
        base_dir=tmp_path,
    )
    assert item["id"]
    assert item["enabled"] is True
    assert list_schedules(base_dir=tmp_path)[0]["name"] == "hourly"
    set_schedule_enabled(item["id"], False, base_dir=tmp_path)
    assert list_schedules(base_dir=tmp_path)[0]["enabled"] is False
    delete_schedule(item["id"], base_dir=tmp_path)
    assert list_schedules(base_dir=tmp_path) == []


def test_tick_skips_future(tmp_path: Path, monkeypatch):
    item = create_schedule(
        name="later",
        project="demo",
        pipeline="main",
        interval_minutes=60,
        base_dir=tmp_path,
    )
    # Force next_run_at into the future
    path = tmp_path / "schedules.json"
    import json

    data = json.loads(path.read_text())
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    data[0]["next_run_at"] = future
    path.write_text(json.dumps(data))

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("should not execute")

    monkeypatch.setattr("app.core.schedules._execute_pipeline", boom)
    fired = tick_due_schedules(base_dir=tmp_path)
    assert fired == []
    assert called["n"] == 0
    assert item["id"]


def test_tick_fires_due(tmp_path: Path, monkeypatch):
    item = create_schedule(
        name="due",
        project="demo",
        pipeline="main",
        interval_minutes=1,
        base_dir=tmp_path,
    )
    import json

    path = tmp_path / "schedules.json"
    data = json.loads(path.read_text())
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    data[0]["next_run_at"] = past
    path.write_text(json.dumps(data))

    monkeypatch.setattr(
        "app.core.schedules._execute_pipeline",
        lambda project, pipeline, env="prod": "run-abc",
    )
    fired = tick_due_schedules(base_dir=tmp_path)
    assert len(fired) == 1
    assert fired[0]["last_run_id"] == "run-abc"
    assert fired[0]["id"] == item["id"]


def test_corrupt_schedules_file_fails_closed(tmp_path: Path):
    path = schedules_path(tmp_path)
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(SchedulesDataError, match="corrupt"):
        list_schedules(base_dir=tmp_path)
    assert not path.is_file()
    assert len(list(tmp_path.glob("schedules.json.corrupt.*"))) == 1

    path.write_text("{still-bad", encoding="utf-8")
    with pytest.raises(SchedulesDataError, match="corrupt"):
        create_schedule(
            name="bad",
            project="demo",
            pipeline="main",
            base_dir=tmp_path,
        )
    assert not path.is_file()


def test_tick_claims_next_run_before_execute(tmp_path: Path, monkeypatch):
    """Claim-before-execute: next_run_at advances even if execute fails."""
    item = create_schedule(
        name="claim",
        project="demo",
        pipeline="main",
        interval_minutes=10,
        base_dir=tmp_path,
    )
    path = tmp_path / "schedules.json"
    data = json.loads(path.read_text())
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    data[0]["next_run_at"] = past
    path.write_text(json.dumps(data))

    monkeypatch.setattr(
        "app.core.schedules._execute_pipeline",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    tick_due_schedules(base_dir=tmp_path)
    stored = list_schedules(base_dir=tmp_path)[0]
    assert stored["id"] == item["id"]
    assert stored["last_error"] == "boom"
    nxt = datetime.fromisoformat(stored["next_run_at"])
    assert nxt > datetime.now(timezone.utc)


def _child_create_schedule(base_dir: str, out: multiprocessing.Queue) -> None:
    try:
        create_schedule(
            name="child",
            project="demo",
            pipeline="main",
            interval_minutes=5,
            base_dir=base_dir,
        )
        out.put("ok")
    except Exception as exc:
        out.put(f"err:{exc}")


@pytest.mark.skipif(
    not hasattr(__import__("fcntl"), "flock"),
    reason="fcntl flock required for cross-process schedule lock test",
)
def test_multiprocess_create_under_flock(tmp_path: Path):
    """Two processes creating schedules concurrently should not lose entries."""
    ctx = multiprocessing.get_context("spawn")
    out: multiprocessing.Queue = ctx.Queue()
    p = ctx.Process(target=_child_create_schedule, args=(str(tmp_path), out))
    p.start()
    create_schedule(
        name="parent",
        project="demo",
        pipeline="main",
        interval_minutes=5,
        base_dir=tmp_path,
    )
    p.join(timeout=30)
    assert p.exitcode == 0
    assert out.get(timeout=5) == "ok"
    names = {s["name"] for s in list_schedules(base_dir=tmp_path)}
    assert names == {"parent", "child"}
