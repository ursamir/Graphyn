# app/core/schedules.py
"""
Bounded Context:  BC6 — Observability & Storage / ops
Responsibility:   Persist interval-based schedule jobs that execute project
                  pipelines (always-on lite — API process ticks while running).
Owns:             list/create/update/delete/run_due schedules helpers.
Public Surface:   Same helpers used by /system/schedules routes.
Must NOT:         Import app.api; must not require croniter.
Dependencies:     json, uuid, datetime, pathlib, fcntl; project_pipelines; runtime_backend lazy.
Reason To Change: Schedule schema or tick policy changes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)
_lock = threading.RLock()

_SAFE_NAME = __import__("re").compile(r"^[A-Za-z0-9_-]{1,64}$")

T = TypeVar("T")


class SchedulesDataError(ValueError):
    """``schedules.json`` is missing, corrupt, or not a JSON array."""


def schedules_path(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir) / "schedules.json"
    from app.core.config import project_dir

    return project_dir() / "schedules.json"


def _lock_path(data_path: Path) -> Path:
    return data_path.with_suffix(data_path.suffix + ".lock")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backup_corrupt(path: Path) -> Path | None:
    ts = _now().strftime("%Y%m%dT%H%M%SZ")
    backup = path.parent / f"schedules.json.corrupt.{ts}"
    try:
        path.rename(backup)
        return backup
    except OSError:
        return None


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        backup = _backup_corrupt(path)
        hint = f" backed up to {backup.name}" if backup is not None else ""
        raise SchedulesDataError(
            f"schedules.json is corrupt ({exc}){hint}. "
            "Repair or remove the file before reading or mutating schedules."
        ) from exc
    if not isinstance(data, list):
        backup = _backup_corrupt(path)
        hint = f" backed up to {backup.name}" if backup is not None else ""
        raise SchedulesDataError(
            f"schedules.json must be a JSON array{hint}. "
            "Repair or remove the file before reading or mutating schedules."
        )
    return data


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    payload = json.dumps(items, indent=2) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _with_file_lock(data_path: Path, exclusive: bool, fn: Callable[[], T]) -> T:
    """Run ``fn`` while holding an advisory lock file (cross-process)."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-POSIX
        fcntl = None  # type: ignore[assignment]

    lock_path = _lock_path(data_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(lock_path, "a+", encoding="utf-8") as lf:
            if fcntl is not None:
                fcntl.flock(
                    lf.fileno(),
                    fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
                )
            try:
                return fn()
            finally:
                if fcntl is not None:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _mutate(
    path: Path, mutator: Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], T]]
) -> T:
    """Atomically load → mutate → save under an exclusive cross-process lock."""

    def _do() -> T:
        items = _load(path)
        new_items, result = mutator(items)
        _save(path, new_items)
        return result

    return _with_file_lock(path, True, _do)


def list_schedules(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    path = schedules_path(base_dir)

    def _read() -> list[dict[str, Any]]:
        return list(_load(path))

    return _with_file_lock(path, False, _read)


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

    def _add(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items.append(item)
        return items, item

    _mutate(path, _add)
    return item


def delete_schedule(schedule_id: str, base_dir: str | Path | None = None) -> None:
    path = schedules_path(base_dir)

    def _delete(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], None]:
        nxt = [i for i in items if i.get("id") != schedule_id]
        if len(nxt) == len(items):
            raise KeyError(schedule_id)
        return nxt, None

    _mutate(path, _delete)


def set_schedule_enabled(
    schedule_id: str, enabled: bool, base_dir: str | Path | None = None
) -> dict[str, Any]:
    path = schedules_path(base_dir)

    def _set(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        for item in items:
            if item.get("id") == schedule_id:
                item["enabled"] = bool(enabled)
                return items, item
        raise KeyError(schedule_id)

    return _mutate(path, _set)


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

    def _read(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        item = next((i for i in items if i.get("id") == schedule_id), None)
        if item is None:
            raise KeyError(schedule_id)
        return items, {
            "project": str(item.get("project") or ""),
            "pipeline": str(item.get("pipeline") or ""),
            "env": str(item.get("env") or "prod"),
        }

    exec_info = _mutate(path, _read)
    run_id = _execute_pipeline(exec_info["project"], exec_info["pipeline"], env=exec_info["env"])
    now = _now()

    def _update(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        for it in items:
            if it.get("id") == schedule_id:
                it["last_run_at"] = now.isoformat()
                it["last_run_id"] = run_id
                it["last_error"] = None
                mins = int(it.get("interval_minutes") or 60)
                it["next_run_at"] = (now + timedelta(minutes=mins)).isoformat()
                return items, {**it}
        raise KeyError(schedule_id)

    return _mutate(path, _update)


def _parse_due(nxt: Any, now: datetime) -> datetime:
    try:
        due = datetime.fromisoformat(str(nxt).replace("Z", "+00:00"))
    except Exception:
        due = now
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due


def tick_due_schedules(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Run any enabled schedules whose next_run_at is due. Returns fired items.

    Claim-before-execute: ``next_run_at`` is advanced under the exclusive flock
    before the pipeline is started so concurrent tickers cannot double-fire.
    """
    now = _now()
    path = schedules_path(base_dir)

    def _claim_due(
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        claimed: list[dict[str, Any]] = []
        for item in items:
            if not item.get("enabled"):
                continue
            due = _parse_due(item.get("next_run_at"), now)
            if due > now:
                continue
            mins = int(item.get("interval_minutes") or 60)
            item["next_run_at"] = (now + timedelta(minutes=mins)).isoformat()
            claimed.append(dict(item))
        return items, claimed

    claimed = _mutate(path, _claim_due)
    fired: list[dict[str, Any]] = []
    for snap in claimed:
        sid = str(snap["id"])
        project = str(snap.get("project") or "")
        pipeline = str(snap.get("pipeline") or "")
        env = str(snap.get("env") or "prod")
        try:
            run_id = _execute_pipeline(project, pipeline, env=env)
            now2 = _now()

            def _record_success(
                items: list[dict[str, Any]],
            ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                for it in items:
                    if it.get("id") == sid:
                        it["last_run_at"] = now2.isoformat()
                        it["last_run_id"] = run_id
                        it["last_error"] = None
                        return items, {**it}
                return items, {**snap, "last_run_id": run_id}

            fired.append(_mutate(path, _record_success))
        except Exception as exc:
            logger.warning("schedule %s failed: %s", sid, exc)

            def _record_error(
                items: list[dict[str, Any]],
            ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                for it in items:
                    if it.get("id") == sid:
                        it["last_error"] = str(exc)[:500]
                        return items, {**it}
                return items, {**snap, "last_error": str(exc)[:500]}

            fired.append(_mutate(path, _record_error))
    return fired
