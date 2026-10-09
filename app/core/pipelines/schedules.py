# app/core/pipelines/schedules.py
"""
Bounded Context:  BC6 — Observability & Storage / ops
Responsibility:   Persist interval- or cron-based schedule jobs that execute
                  project pipelines (always-on lite — API process ticks while
                  running). A row with ``cron`` (5-field, UTC; see
                  app.core.pipelines.cron) fires on the cron; otherwise every
                  ``interval_minutes``.
Owns:             list/create/update/delete/run_due schedules helpers;
                  orphan handling (project deleted → schedules disabled with
                  ``orphaned: true``) and auto-disable on permanent start
                  errors (project / pipeline not found). Disabled / orphaned
                  schedules carry ``next_run_at: null`` (recomputed on enable);
                  :func:`normalize_schedule` gives the API view with stable
                  ``orphaned``, ``disabled_reason``, ``orphaned_at`` keys.
Public Surface:   Same helpers used by /system/schedules routes.
Must NOT:         Import app.api; must not require croniter (own parser in cron.py).
Dependencies:     json, uuid, datetime, pathlib, app.core.persist.file_lock; project_pipelines; runtime_backend lazy.
Reason To Change: Schedule schema or tick policy changes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)
_lock = threading.RLock()

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

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
    """Run ``fn`` while holding an advisory lock file (cross-process).

    Fails closed: if the platform cannot lock, the mutation is not run.
    """
    from app.core.persist.file_lock import acquire, release

    lock_path = _lock_path(data_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(lock_path, "a+b") as lf:
            acquire(lf, exclusive=exclusive)
            try:
                return fn()
            finally:
                release(lf)


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


def list_schedules(
    base_dir: str | Path | None = None, *, project: str | None = None
) -> list[dict[str, Any]]:
    """Return all schedules, optionally filtered to one ``project``."""
    path = schedules_path(base_dir)

    def _read() -> list[dict[str, Any]]:
        return list(_load(path))

    items = [_reported(i) for i in _with_file_lock(path, False, _read)]
    if project:
        items = [i for i in items if str(i.get("project") or "") == project]
    return items


def _reported(item: dict[str, Any]) -> dict[str, Any]:
    """Copy of a stored row with ``next_run_at: None`` when disabled.

    A disabled schedule never fires, so a timestamp would be misleading
    (legacy rows written before this rule still carry one on disk).
    """
    out = dict(item)
    if not out.get("enabled"):
        out["next_run_at"] = None
    return out


def normalize_schedule(item: dict[str, Any]) -> dict[str, Any]:
    """API view of one schedule: stable ``orphaned`` / ``disabled_reason`` /
    ``orphaned_at`` keys (``False`` / ``None`` when unset) and
    ``next_run_at: None`` for disabled schedules. Does not mutate ``item``.
    """
    out = _reported(item)
    out["orphaned"] = bool(out.get("orphaned"))
    out["disabled_reason"] = out.get("disabled_reason") or None
    out["orphaned_at"] = out.get("orphaned_at") or None
    out["cron"] = out.get("cron") or None
    return out


def _next_run_iso(item: dict[str, Any], now: datetime | None = None) -> str:
    base = now or _now()
    cron = str(item.get("cron") or "").strip()
    if cron:
        from app.core.pipelines.cron import CronError, next_fire

        try:
            return next_fire(cron, base).isoformat()
        except CronError:
            logger.warning("schedule %s has an invalid cron %r; using interval", item.get("id"), cron)
    mins = int(item.get("interval_minutes") or 60)
    return (base + timedelta(minutes=mins)).isoformat()


def validate_cron(cron: str | None) -> str | None:
    """Normalise an optional cron expression; ValueError when invalid."""
    text = str(cron or "").strip()
    if not text:
        return None
    from app.core.pipelines.cron import parse_cron

    parse_cron(text)  # CronError is a ValueError
    return text


# Start errors that will never succeed on retry — the schedule is disabled
# instead of failing on every tick.
_PERMANENT_ERROR_PATTERNS = (
    re.compile(r"^Project not found", re.IGNORECASE),
    re.compile(r"^Pipeline '?[^']*'? not found", re.IGNORECASE),
    re.compile(r"pipeline not found", re.IGNORECASE),
)


def is_permanent_schedule_error(exc: BaseException) -> bool:
    """True when ``exc`` means the schedule target no longer exists."""
    if not isinstance(exc, (FileNotFoundError, KeyError)):
        return False
    msg = str(exc.args[0]) if exc.args else str(exc)
    return any(p.search(msg) for p in _PERMANENT_ERROR_PATTERNS)


def _apply_error(it: dict[str, Any], exc: BaseException) -> None:
    msg = str(exc.args[0] if exc.args else exc)[:500]
    it["last_error"] = msg
    it["last_error_at"] = _now().isoformat()
    if is_permanent_schedule_error(exc):
        it["enabled"] = False
        it["next_run_at"] = None
        it["disabled_reason"] = f"auto-disabled after permanent error: {msg}"
        if msg.lower().startswith("project not found"):
            it["orphaned"] = True
            it["orphaned_at"] = it["last_error_at"]


def disable_schedules_for_project(
    project: str,
    *,
    reason: str | None = None,
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Disable every schedule targeting ``project`` and mark it ``orphaned``.

    Called when a project is deleted. No-op (and no file created) when no
    ``schedules.json`` exists. Returns the updated schedules.
    """
    path = schedules_path(base_dir)
    if not path.is_file():
        return []
    why = reason or f"Project deleted: {project}"
    now = _now().isoformat()

    def _orphan(
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        changed: list[dict[str, Any]] = []
        for it in items:
            if str(it.get("project") or "") != project:
                continue
            it["enabled"] = False
            it["next_run_at"] = None
            it["orphaned"] = True
            it["disabled_reason"] = why
            it["orphaned_at"] = now
            changed.append({**it})
        return items, changed

    return _mutate(path, _orphan)


def disable_schedules_for_pipeline(
    project: str,
    pipeline: str,
    *,
    reason: str | None = None,
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Disable every schedule targeting ``project``/``pipeline`` and mark it orphaned.

    Called when a project pipeline is deleted (F19 / F-04). No-op (and no file
    created) when no ``schedules.json`` exists. Returns the updated schedules.
    """
    path = schedules_path(base_dir)
    if not path.is_file():
        return []
    why = reason or f"Pipeline deleted: {project}/{pipeline}"
    now = _now().isoformat()

    def _orphan(
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        changed: list[dict[str, Any]] = []
        for it in items:
            if str(it.get("project") or "") != project:
                continue
            if str(it.get("pipeline") or "") != pipeline:
                continue
            it["enabled"] = False
            it["next_run_at"] = None
            it["orphaned"] = True
            it["disabled_reason"] = why
            it["orphaned_at"] = now
            changed.append({**it})
        return items, changed

    return _mutate(path, _orphan)


def create_schedule(
    *,
    name: str,
    project: str,
    pipeline: str,
    interval_minutes: int = 60,
    enabled: bool = True,
    env: str = "prod",
    base_dir: str | Path | None = None,
    cron: str | None = None,
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
    cron_s = validate_cron(cron)
    now = _now()
    item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "project": project,
        "pipeline": pipeline,
        "env": env_s,
        "interval_minutes": minutes,
        "cron": cron_s,
        "enabled": bool(enabled),
        "created_at": now.isoformat(),
        "last_run_at": None,
        "last_run_id": None,
        "last_error": None,
        "next_run_at": None,
    }
    if enabled:
        item["next_run_at"] = _next_run_iso(item, now)
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
                if enabled:
                    # Re-enabling is an explicit operator decision; the next
                    # tick re-disables it if the target is still missing.
                    item.pop("orphaned", None)
                    item.pop("orphaned_at", None)
                    item.pop("disabled_reason", None)
                    item["next_run_at"] = _next_run_iso(item)
                else:
                    item["next_run_at"] = None
                return items, item
        raise KeyError(schedule_id)

    return _mutate(path, _set)


def set_schedule_env(
    schedule_id: str, env: str, base_dir: str | Path | None = None
) -> dict[str, Any]:
    env_s = (env or "draft").strip().lower()
    if env_s not in ("draft", "staging", "prod"):
        raise ValueError("env must be draft, staging, or prod")
    path = schedules_path(base_dir)

    def _set(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        for item in items:
            if item.get("id") == schedule_id:
                item["env"] = env_s
                item["last_error"] = None
                return items, item
        raise KeyError(schedule_id)

    return _mutate(path, _set)


def _execute_pipeline(project: str, pipeline: str, env: str = "prod") -> str:
    from app.core.config import datasets_output_dir
    from app.core.ir.loader import load_ir
    from app.core.pipelines.pipeline_environments import get_environment_graph
    from app.core.runs.run_journal import RunManager
    from app.core.execution.runtime_backend import get_backend

    project_dir = datasets_output_dir() / project
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project not found: {project}")
    chosen = env or "prod"
    try:
        data = get_environment_graph(project_dir, pipeline, env=chosen)
    except FileNotFoundError as exc:
        if str(exc).startswith("No version pointed"):
            raise FileNotFoundError(
                f"Pipeline {pipeline} has no published {chosen} version. "
                "Publish that environment, or set this schedule to draft to run the saved pipeline."
            ) from exc
        raise
    from app.core.execution.dataset_refs import resolve_latest_refs

    graph, _ = resolve_latest_refs(load_ir(data))
    run_mgr = RunManager()
    run_mgr._write_meta_field("project", project)
    run_mgr._write_meta_field("schedule", True)
    run_mgr._write_meta_field("pipeline_env", env or "prod")
    # Audit: declared saved-pipeline ref + scheduler identity.
    run_mgr._write_meta_field("pipeline_name", pipeline)
    run_mgr._write_meta_field("actor", "scheduler")
    run_mgr._write_meta_field("trigger", "schedule")
    try:
        from app.core.trust.audit import record_audit

        record_audit(actor="scheduler", action="run.start", resource_type="run",
                     resource_id=run_mgr.run_id,
                     meta={"mode": "schedule", "trigger": "schedule", "project": project,
                           "pipeline": pipeline, "env": chosen})
    except Exception:
        pass

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
    try:
        run_id = _execute_pipeline(exec_info["project"], exec_info["pipeline"], env=exec_info["env"])
    except Exception as exc:
        logger.warning("schedule %s failed to start: %s", schedule_id, exc)

        def _record_error(
            items: list[dict[str, Any]],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            for it in items:
                if it.get("id") == schedule_id:
                    _apply_error(it, exc)
                    return items, {**it}
            raise KeyError(schedule_id)

        _mutate(path, _record_error)
        raise
    now = _now()

    def _update(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        for it in items:
            if it.get("id") == schedule_id:
                it["last_run_at"] = now.isoformat()
                it["last_run_id"] = run_id
                it["last_error"] = None
                # Manual "run now" on a disabled schedule must not re-arm it.
                it["next_run_at"] = _next_run_iso(it, now) if it.get("enabled") else None
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


def _ticker_lock_path(base_dir: str | Path | None = None) -> Path:
    return schedules_path(base_dir).with_name("schedules.ticker.lock")


def try_tick_due_schedules(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Run :func:`tick_due_schedules` only when this process holds the ticker lease.

    Uses a non-blocking cross-process lock so multiple API workers do not each
    fire schedules. If the platform cannot lock, the tick is skipped (fail
    closed) instead of running unlocked.
    """
    from app.core.persist.file_lock import LockUnavailable, acquire, release

    lock_path = _ticker_lock_path(base_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lf:
        try:
            acquire(lf, exclusive=True, nonblocking=True)
        except BlockingIOError:
            return []
        except LockUnavailable:
            logger.error(
                "Schedule ticker skipped: no cross-process file lock on this platform"
            )
            return []
        try:
            return tick_due_schedules(base_dir)
        finally:
            release(lf)


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
            item["next_run_at"] = _next_run_iso(item, now)
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
                        _apply_error(it, exc)
                        return items, {**it}
                return items, {**snap, "last_error": str(exc)[:500]}

            fired.append(_mutate(path, _record_error))
    return fired
