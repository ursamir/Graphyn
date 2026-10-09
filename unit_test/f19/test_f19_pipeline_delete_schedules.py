"""F19 (F-04): deleting a project pipeline orphans only that pipeline's schedules."""
from __future__ import annotations

import json

from app.core.pipelines import schedules as sch


def test_disable_schedules_for_pipeline_only_matching(tmp_path):
    path = sch.schedules_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {"id": "a", "project": "p1", "pipeline": "x", "enabled": True, "cron": "* * * * *"},
        {"id": "b", "project": "p1", "pipeline": "y", "enabled": True, "cron": "* * * * *"},
        {"id": "c", "project": "p2", "pipeline": "x", "enabled": True, "cron": "* * * * *"},
    ]
    path.write_text(json.dumps(items), encoding="utf-8")
    changed = sch.disable_schedules_for_pipeline("p1", "x", base_dir=tmp_path)
    assert [c["id"] for c in changed] == ["a"]
    after = {i["id"]: i for i in sch.list_schedules(tmp_path)}
    assert after["a"]["enabled"] is False and after["a"]["orphaned"] is True
    assert after["b"]["enabled"] is True
    assert after["c"]["enabled"] is True


def test_disable_schedules_for_pipeline_no_file(tmp_path):
    assert sch.disable_schedules_for_pipeline("p", "x", base_dir=tmp_path) == []
    assert not sch.schedules_path(tmp_path).exists()
