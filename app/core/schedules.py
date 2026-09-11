# app/core/schedules.py
"""
Bounded Context:  BC6 — Observability & Storage / ops
Responsibility:   Persist interval-based schedule jobs that execute project
                  pipelines (always-on lite — API process ticks while running).
Owns:             list/create/update/delete/run_due schedules helpers.
Public Surface:   Same helpers used by /system/schedules routes.
Must NOT:         Import app.api; must not require croniter.
Dependencies:     json, uuid, datetime, pathlib; project_pipelines; runtime_backend lazy.
Reason To Change: Schedule schema or tick policy changes.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_lock = threading.RLock()

_SAFE_NAME = __import__("re").compile(r"^[A-Za-z0-9_-]{1,64}$")


def schedules_path(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir) / "schedules.json"
    from app.core.config import project_dir

    return project_dir() / "schedules.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def list_schedules(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    with _lock:
        return list(_load(schedules_path(base_dir)))


def create_schedule(
    *,
    name: str,
    project: str,
    pipeline: str,
    interval_minutes: int = 60,
    enabled: bool = True,
    env: str = "prod",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not _SAFE_NAME.match(name or ""):
        raise ValueError("Invalid schedule name")
    if not _SAFE_NAME.match(project or ""):
        raise ValueError("Invalid project name")
    if not _SAFE_NAME.match(pipeline or ""):
        raise ValueError("Invalid pipeline name")
    env_s = (env or "prod").strip().lower()
    if env_s not in ("draft", "staging", "prod"):
        raise ValueError("env must be draft, staging, or prod")
    minutes = max(1, min(int(interval_minutes), 60 * 24 * 30))
    now = _now()
    item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "project": project,
        "pipeline": pipeline,
        "env": env_s,
        "interval_minutes": minutes,
        "enabled": bool(enabled),
        "created_at": now.isoformat(),
        "last_run_at": None,
        "last_run_id": None,
        "last_error": None,
        "next_run_at": (now + timedelta(minutes=minutes)).isoformat(),
    }
    path = schedules_path(base_dir)
    with _lock:
        items = _load(path)
        items.append(item)
        _save(path, items)
    return item


def delete_schedule(schedule_id: str, base_dir: str | Path | None = None) -> None:
    path = schedules_path(base_dir)
    with _lock:
        items = _load(path)
        nxt = [i for i in items if i.get("id") != schedule_id]
        if len(nxt) == len(items):
            raise KeyError(schedule_id)
        _save(path, nxt)


def set_schedule_enabled(
    schedule_id: str, enabled: bool, base_dir: str | Path | None = None
) -> dict[str, Any]:
    path = schedules_path(base_dir)
    with _lock:
        items = _load(path)
        for item in items:
            if item.get("id") == schedule_id:
                item["enabled"] = bool(enabled)
                _save(path, items)
                return item
    raise KeyError(schedule_id)


def _execute_pipeline(project: str, pipeline: str, env: str = "prod") -> str:
    from app.core.config import datasets_output_dir
    from app.core.ir.loader import load_ir
    from app.core.pipeline_environments import get_environment_graph
    from app.core.run_journal import RunManager
    from app.core.runtime_backend import get_backend

    project_dir = datasets_output_dir() / project
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project not found: {project}")
    data = get_environment_graph(project_dir, pipeline, env=env or "prod")
    graph = load_ir(data)
    run_mgr = RunManager()
    run_mgr._write_meta_field("project", project)
    run_mgr._write_meta_field("schedule", True)
    run_mgr._write_meta_field("pipeline_env", env or "prod")

    def _run() -> None:
        try:
            get_backend().execute(graph, run_manager=run_mgr)
        except Exception as exc:
            try:
                run_mgr.mark_failed(str(exc))
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return run_mgr.run_id


def run_schedule_now(schedule_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    path = schedules_path(base_dir)
    with _lock:
        items = _load(path)
        item = next((i for i in items if i.get("id") == schedule_id), None)
        if item is None:
            raise KeyError(schedule_id)
        project = str(item.get("project") or "")
        pipeline = str(item.get("pipeline") or "")
        env = str(item.get("env") or "prod")
    run_id = _execute_pipeline(project, pipeline, env=env)
    now = _now()
    with _lock:
        items = _load(path)
        for it in items:
            if it.get("id") == schedule_id:
                it["last_run_at"] = now.isoformat()
                it["last_run_id"] = run_id
                it["last_error"] = None
                mins = int(it.get("interval_minutes") or 60)
                it["next_run_at"] = (now + timedelta(minutes=mins)).isoformat()
                _save(path, items)
                return {**it}
    return {"id": schedule_id, "last_run_id": run_id}


def tick_due_schedules(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Run any enabled schedules whose next_run_at is due. Returns fired items."""
    now = _now()
    fired: list[dict[str, Any]] = []
    with _lock:
        items = list(_load(schedules_path(base_dir)))
    for item in items:
        if not item.get("enabled"):
            continue
        nxt = item.get("next_run_at")
        try:
            due = datetime.fromisoformat(str(nxt).replace("Z", "+00:00"))
        except Exception:
            due = now
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due > now:
            continue
        try:
            fired.append(run_schedule_now(str(item["id"]), base_dir=base_dir))
        except Exception as exc:
            logger.warning("schedule %s failed: %s", item.get("id"), exc)
            with _lock:
                path = schedules_path(base_dir)
                all_items = _load(path)
                for it in all_items:
                    if it.get("id") == item.get("id"):
                        it["last_error"] = str(exc)[:500]
                        mins = int(it.get("interval_minutes") or 60)
                        it["next_run_at"] = (now + timedelta(minutes=mins)).isoformat()
                        _save(path, all_items)
                        break
    return fired
