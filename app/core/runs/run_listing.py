# app/core/runs/run_listing.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Single, stable run-history lister shared by REST GET /runs,
                  MCP list_runs, CLI `runs list`, and experiment boards.
Owns:             sorted_run_dirs(), list_runs(), RunListPage, run_sort_key().
Public Surface:   sorted_run_dirs(runs_root) -> list[Path];
                  list_runs(runs_root, limit, offset, project, status,
                  include_unreadable) -> RunListPage.
Must NOT:         Write run journal files; import app.api / app.domain;
                  sort by directory mtime (atomic meta.json renames bump it,
                  which reorders pages mid-scroll → duplicate / skipped rows).
Dependencies:     app.core.config.runs_dir, app.core.runs.run_project (project
                  filter), app.core.runs.run_status (status normalisation), stdlib.
Reason To Change: Run ordering / pagination contract or run meta schema changes.

Ordering contract: ``created_at`` descending (immutable — written once by
RunManager at construction), ``run_id`` descending as a deterministic
tiebreak. A run deleted between directory listing and stat/read is skipped
per entry; it never empties the whole listing.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Sort keys are cached per run directory, validated by meta.json mtime_ns, so
# unfiltered pagination costs one stat per run (not one JSON read) once warm.
# Bounded: cleared wholesale when it grows past the cap.
_SORT_KEY_CACHE: dict[str, tuple[int, float]] = {}
_SORT_KEY_CACHE_MAX = 200_000
_CACHE_LOCK = threading.Lock()
_UNREADABLE = object()


@dataclass
class RunListPage:
    """One page of runs: ``rows`` are ``(run_dir, meta)`` newest first."""

    rows: list[tuple[Path, dict[str, Any]]] = field(default_factory=list)
    total_matched: int = 0


def _parse_ts(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return the JSON object at path; None when missing (raises on corrupt)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def run_sort_key(meta: dict[str, Any] | None, run_dir: Path) -> tuple[float, str]:
    """``(created_at_epoch, run_id)`` — callers sort descending."""
    meta = meta or {}
    ts = _parse_ts(meta.get("created_at"))
    if ts is None:
        ts = _parse_ts(meta.get("started_at"))
    run_id = str(meta.get("run_id") or run_dir.name)
    return (ts if ts is not None else 0.0, run_id)


def _cached_created(run_dir: Path, mtime_ns: int) -> float | None:
    with _CACHE_LOCK:
        hit = _SORT_KEY_CACHE.get(str(run_dir))
    if hit is not None and hit[0] == mtime_ns:
        return hit[1]
    return None


def _remember_created(run_dir: Path, mtime_ns: int, meta: dict[str, Any]) -> None:
    ts = _parse_ts(meta.get("created_at"))
    if ts is None:
        ts = _parse_ts(meta.get("started_at"))
    if ts is None:
        return
    with _CACHE_LOCK:
        if len(_SORT_KEY_CACHE) >= _SORT_KEY_CACHE_MAX:
            _SORT_KEY_CACHE.clear()
        _SORT_KEY_CACHE[str(run_dir)] = (mtime_ns, ts)


def clear_run_listing_cache() -> None:
    """Drop cached sort keys (tests / after bulk deletes)."""
    with _CACHE_LOCK:
        _SORT_KEY_CACHE.clear()


def _scan(
    runs_root: Path, *, require_meta: bool = True
) -> tuple[list[tuple[tuple[float, str], Path]], dict[Path, Any]]:
    """Return sortable entries plus metas already read (dict or ``_UNREADABLE``).

    Directories without meta.json are dropped unless ``require_meta`` is
    False (then keyed last). Every per-entry OSError
    (e.g. the run was deleted between iterdir and stat) skips only that entry.
    """
    try:
        children = list(runs_root.iterdir())
    except FileNotFoundError:
        return [], {}
    except OSError as exc:
        log.warning("run_listing: cannot list %s (%s)", runs_root, exc)
        return [], {}

    keyed: list[tuple[tuple[float, str], Path]] = []
    loaded: dict[Path, Any] = {}
    for entry in children:
        try:
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            try:
                mtime_ns = meta_path.stat().st_mtime_ns
            except FileNotFoundError:
                if not require_meta:
                    keyed.append(((0.0, entry.name), entry))
                continue
            cached = _cached_created(entry, mtime_ns)
            if cached is not None:
                keyed.append(((cached, entry.name), entry))
                continue
            try:
                meta = _read_json(meta_path)
            except (OSError, ValueError) as exc:
                if isinstance(exc, FileNotFoundError):
                    continue
                log.warning("run_listing: unreadable meta in %s (%s)", entry, exc)
                loaded[entry] = _UNREADABLE
                keyed.append(((0.0, entry.name), entry))
                continue
            if meta is None:
                if not require_meta:
                    keyed.append(((0.0, entry.name), entry))
                continue
            loaded[entry] = meta
            _remember_created(entry, mtime_ns, meta)
            keyed.append(((run_sort_key(meta, entry)[0], entry.name), entry))
        except OSError:
            continue
    keyed.sort(key=lambda item: item[0], reverse=True)
    return keyed, loaded


def sorted_run_dirs(runs_root: Path | None = None, *, require_meta: bool = True) -> list[Path]:
    """Run directories newest first (created_at desc, dir name desc).

    ``require_meta=False`` also yields directories without meta.json (sorted
    last) — used by experiment boards, which accept experiment.json-only dirs.
    """
    root = _resolve_root(runs_root)
    keyed, _ = _scan(root, require_meta=require_meta)
    return [entry for _key, entry in keyed]


def _resolve_root(runs_root: Path | None) -> Path:
    if runs_root is not None:
        return Path(runs_root)
    from app.core.config import runs_dir

    return runs_dir()


def list_runs(
    runs_root: Path | None = None,
    *,
    limit: int | None = 50,
    offset: int = 0,
    project: str | None = None,
    status: str | None = None,
    include_unreadable: bool = False,
) -> RunListPage:
    """Return a stable page of runs, newest first.

    - Entries without ``meta.json`` are skipped (not a run, or mid-delete).
    - Corrupt ``meta.json`` is skipped unless ``include_unreadable`` (then a
      ``{"run_id", "status": "unknown"}`` placeholder is returned).
    - ``project`` is a hard filter via :func:`run_project.project_matches`
      (in-memory inference from graph.json; never writes).
    - ``status`` compares against the normalised status vocabulary.
    - ``limit=None`` (or ``<= 0``) returns every match from ``offset``.
    """
    from app.core.runs.run_project import normalize_project_name, project_matches
    from app.core.runs.run_status import normalize_status

    root = _resolve_root(runs_root)
    keyed, loaded = _scan(root)
    needle = normalize_project_name(project)
    status_filter = str(status or "").strip().lower() or None
    offset = max(0, int(offset or 0))
    cap = int(limit) if limit is not None and int(limit) > 0 else None

    page: list[tuple[Path, dict[str, Any]]] = []
    matched = 0
    unfiltered = not needle and not status_filter
    for index, (_key, entry) in enumerate(keyed):
        if unfiltered and cap is not None and len(page) >= cap:
            # Page full: count the rest without reading their meta.json.
            matched += len(keyed) - index
            break
        if entry in loaded:
            meta = loaded[entry]
        else:
            try:
                meta = _read_json(entry / "meta.json")
            except (OSError, ValueError) as exc:
                log.warning("run_listing: unreadable meta in %s (%s)", entry, exc)
                meta = _UNREADABLE
        if meta is None:
            continue
        if meta is _UNREADABLE:
            if not include_unreadable or needle or status_filter:
                continue
            meta = {"run_id": entry.name, "status": "unknown", "created_at": None, "duration_s": None}
        else:
            meta = dict(meta)
            meta.setdefault("run_id", entry.name)
        try:
            if needle and not project_matches(meta, needle, entry):
                continue
        except OSError:
            continue
        if status_filter:
            current = normalize_status(str(meta.get("status") or "")) if meta.get("status") else ""
            if str(current).lower() != status_filter:
                continue
        matched += 1
        if matched <= offset:
            continue
        if cap is None or len(page) < cap:
            page.append((entry, meta))
    return RunListPage(rows=page, total_matched=matched)
