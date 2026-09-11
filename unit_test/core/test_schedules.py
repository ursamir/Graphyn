# unit_test/core/test_schedules.py
"""Tests for app.core.schedules (always-on lite)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.schedules import (
    create_schedule,
    delete_schedule,
    list_schedules,
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
        lambda project, pipeline: "run-abc",
    )
    fired = tick_due_schedules(base_dir=tmp_path)
    assert len(fired) == 1
    assert fired[0]["last_run_id"] == "run-abc"
    assert fired[0]["id"] == item["id"]
