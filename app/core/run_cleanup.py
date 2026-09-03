# app/core/run_cleanup.py
"""
Bounded Context:  Platform Infrastructure
Responsibility:   Path-jailed deletion of run journals and workspace artifact
                  run folders, plus system cleanup policy.
Owns:             cleanup_workspace, delete_run, helper path-jail rmtree.
Public Surface:   cleanup_workspace, delete_run, FINISHED_STATUSES,
                  ACTIVE_STATUSES.
Must NOT:         Delete examples/, datasets/input, or anything outside
                  {project_dir}/runs, cache, artifacts.
Dependencies:     shutil, json, datetime, pathlib; app.core.config;
                  app.core.workspace_paths.
Reason To Change: Cleanup policy or run-delete semantics change.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import artifacts_dir, cache_dir, runs_dir
from app.core.workspace_paths import (
    ARTIFACTS_PREFIX,
    artifact_fs_path,
    artifact_layout,
    artifact_slug,
    latest_run_id,
    publish_latest,
    slug_from_artifacts_posix,
)

logger = logging.getLogger(__name__)

FINISHED_STATUSES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATUSES = frozenset({"running", "paused"})


class RunInProgressError(RuntimeError):
    """Raised when a currently running/paused run is requested for deletion."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_meta(run_path: Path) -> dict[str, Any]:
    meta_file = run_path / "meta.json"
    if not meta_file.exists():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _run_status(run_path: Path, meta: dict[str, Any] | None = None) -> str:
    meta = meta if meta is not None else _load_meta(run_path)
    status = str(meta.get("status") or "").strip().lower()
    return status or "unknown"


def _bytes_under(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    try:
        if path.is_file() or path.is_symlink():
            try:
                if path.is_file() and not path.is_symlink():
                    return path.stat().st_size
            except OSError:
                return 0
            return 0
        for f in path.rglob("*"):
            try:
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _jailed(path: Path, jail: Path) -> bool:
    try:
        resolved = path.resolve()
        root = jail.resolve()
        return resolved == root or resolved.is_relative_to(root)
    except (OSError, ValueError):
        return False


def _rmtree_jailed(path: Path, jail: Path) -> int:
    """Remove ``path`` if it resolves inside ``jail``. Returns bytes freed.

    Symlinks are unlinked (the target is not followed).
    """
    if not path.exists() and not path.is_symlink():
        return 0
    if not _jailed(path, jail):
        logger.warning("refusing to delete path outside jail: %s (jail=%s)", path, jail)
        return 0
    freed = 0
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return 0
        freed = _bytes_under(path)
        shutil.rmtree(path)
    except OSError as exc:
        logger.warning("failed to delete %s: %s", path, exc)
        return 0
    return freed


def _slug_for_run(run_id: str, run_path: Path, meta: dict[str, Any] | None = None) -> str | None:
    meta = meta if meta is not None else _load_meta(run_path)
    artifacts = meta.get("artifacts_dir") if isinstance(meta.get("artifacts_dir"), str) else None
    slug = slug_from_artifacts_posix(artifacts) if artifacts else None
    if not slug:
        name = meta.get("graph_name")
        if isinstance(name, str) and name.strip():
            slug = artifact_slug(name)
    if not slug:
        try:
            from app.core.run_outputs import _load_run_graph

            graph = _load_run_graph(run_path)
            gmeta = graph.get("metadata") if isinstance(graph, dict) else None
            if isinstance(gmeta, dict) and gmeta.get("name"):
                slug = artifact_slug(str(gmeta["name"]))
        except Exception:
            slug = None
    return slug


def _slug_runs_dir(slug: str) -> Path:
    return artifact_fs_path(f"{ARTIFACTS_PREFIX}/{artifact_slug(slug)}/runs")


def _remaining_artifact_run_ids(slug: str) -> list[str]:
    runs_root = _slug_runs_dir(slug)
    if not runs_root.is_dir():
        return []
    entries: list[tuple[float, str]] = []
    for child in runs_root.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append((mtime, child.name))
    entries.sort(reverse=True)
    return [name for _mt, name in entries]


def _remove_latest_alias(slug: str) -> None:
    """Unlink/remove the latest alias without deleting the run it pointed at."""
    jail = artifacts_dir()
    layout = artifact_layout(slug, "_")
    latest = artifact_fs_path(layout["latest_dir"])
    slug_dir = latest.parent
    try:
        if latest.is_symlink() or latest.is_file():
            if _jailed(latest, jail):
                latest.unlink()
        elif latest.is_dir() and _jailed(latest, jail):
            # Directory copy of latest (non-symlink fallback) — remove only the
            # alias folder, never a runs/<id> target.
            if latest.name == "latest":
                shutil.rmtree(latest)
    except OSError as exc:
        logger.warning("failed to remove latest alias for %s: %s", slug, exc)
    pointer = slug_dir / "latest.json"
    if pointer.is_file() and _jailed(pointer, jail):
        try:
            pointer.unlink()
        except OSError:
            pass


def retarget_latest(slug: str, deleted_run_id: str | None = None) -> str | None:
    """If latest points at a missing/deleted run, retarget or drop the alias."""
    slug = artifact_slug(slug)
    current = latest_run_id(slug)
    remaining = _remaining_artifact_run_ids(slug)
    if deleted_run_id:
        remaining = [rid for rid in remaining if rid != deleted_run_id]
    if current and current in remaining:
        return current
    if remaining:
        nxt = remaining[0]
        try:
            return publish_latest(slug, nxt)
        except OSError as exc:
            logger.warning("failed to retarget latest for %s -> %s: %s", slug, nxt, exc)
            return None
    _remove_latest_alias(slug)
    return None


def _delete_workspace_run_artifacts(slug: str | None, run_id: str) -> int:
    if not slug:
        # Best-effort: scan artifacts/*/runs/<run_id>
        art_root = artifacts_dir()
        if not art_root.is_dir():
            return 0
        freed = 0
        for slug_dir in art_root.iterdir():
            if not slug_dir.is_dir():
                continue
            candidate = slug_dir / "runs" / run_id
            if candidate.exists() or candidate.is_symlink():
                freed += _rmtree_jailed(candidate, art_root)
                retarget_latest(slug_dir.name, run_id)
                _prune_empty_runs_dir(slug_dir.name)
        return freed
    run_art = artifact_fs_path(artifact_layout(slug, run_id)["run_dir"])
    freed = _rmtree_jailed(run_art, artifacts_dir())
    retarget_latest(slug, run_id)
    _prune_empty_runs_dir(slug)
    return freed


def _prune_empty_runs_dir(slug: str) -> None:
    runs_root = _slug_runs_dir(slug)
    jail = artifacts_dir()
    try:
        if runs_root.is_dir() and _jailed(runs_root, jail) and not any(runs_root.iterdir()):
            runs_root.rmdir()
        slug_dir = runs_root.parent
        if slug_dir.is_dir() and _jailed(slug_dir, jail):
            leftover = [p for p in slug_dir.iterdir() if p.name not in {".", ".."}]
            # If only empty leftover dirs remain, leave latest handling to retarget.
            if not leftover:
                slug_dir.rmdir()
    except OSError:
        pass


def delete_run(run_id: str, *, require_finished: bool = True) -> dict[str, Any]:
    """Delete a run journal and its workspace artifact run folder.

    Raises FileNotFoundError if the journal dir is missing.
    Raises RunInProgressError if the run is currently running/paused.
    """
    runs_root = runs_dir()
    run_path = (runs_root / run_id).resolve()
    if not _jailed(run_path, runs_root):
        raise FileNotFoundError("Run not found")
    if not run_path.exists():
        raise FileNotFoundError("Run not found")
    meta = _load_meta(run_path)
    status = _run_status(run_path, meta)
    if require_finished and status in ACTIVE_STATUSES:
        raise RunInProgressError(f"Run {run_id} is {status}")
    slug = _slug_for_run(run_id, run_path, meta)
    bytes_freed = 0
    bytes_freed += _delete_workspace_run_artifacts(slug, run_id)
    bytes_freed += _rmtree_jailed(run_path, runs_root)
    return {
        "deleted": run_id,
        "slug": slug,
        "bytes_freed": bytes_freed,
        "status": status,
    }


def cleanup_workspace(
    *,
    older_than_days: int = 7,
    delete_cache: bool = True,
    delete_artifacts: bool = False,
    keep_latest: bool = True,
) -> dict[str, Any]:
    """Apply cleanup policy inside the project jail.

    ``older_than_days`` may be 0 (delete all finished runs, subject to
    keep_latest / running guards).
    """
    days = max(0, int(older_than_days))
    cutoff = _now() - timedelta(days=days)
    runs_deleted = 0
    cache_deleted = 0
    artifacts_deleted = 0
    bytes_freed = 0
    skipped_too_new = 0
    skipped_latest = 0
    skipped_running = 0

    runs_root = runs_dir()
    cache_root = cache_dir()
    art_root = artifacts_dir()

    latest_ids: dict[str, str] = {}

    def _is_latest(run_id: str, slug: str | None) -> bool:
        if not slug:
            return False
        if slug not in latest_ids:
            rid = latest_run_id(slug)
            if rid:
                latest_ids[slug] = rid
        return latest_ids.get(slug) == run_id

    to_delete: list[tuple[Path, str, str | None]] = []

    if runs_root.exists():
        for entry in list(runs_root.iterdir()):
            if not entry.is_dir():
                continue
            if not _jailed(entry, runs_root):
                continue
            run_id = entry.name
            meta = _load_meta(entry)
            status = _run_status(entry, meta)
            if status in ACTIVE_STATUSES or status not in FINISHED_STATUSES:
                skipped_running += 1
                continue
            slug = _slug_for_run(run_id, entry, meta)
            if keep_latest and _is_latest(run_id, slug):
                skipped_latest += 1
                continue
            if days > 0:
                try:
                    mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    skipped_too_new += 1
                    continue
                if mtime >= cutoff:
                    skipped_too_new += 1
                    continue
            to_delete.append((entry, run_id, slug))

    deleted_ids: list[str] = []
    for entry, run_id, slug in to_delete:
        if delete_artifacts:
            before = _bytes_under(artifact_fs_path(artifact_layout(slug, run_id)["run_dir"])) if slug else 0
            freed_art = _delete_workspace_run_artifacts(slug, run_id)
            if freed_art or (slug and before):
                artifacts_deleted += 1
            bytes_freed += freed_art
        else:
            # Journal-only: if this run was latest we already skipped it when
            # keep_latest. If not, leave workspace artifacts in place.
            pass
        bytes_freed += _rmtree_jailed(entry, runs_root)
        runs_deleted += 1
        deleted_ids.append(run_id)

    if delete_cache and cache_root.exists():
        for entry in list(cache_root.iterdir()):
            if not entry.is_dir():
                continue
            if not _jailed(entry, cache_root):
                continue
            if days > 0:
                try:
                    mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if mtime >= cutoff:
                    continue
            bytes_freed += _rmtree_jailed(entry, cache_root)
            cache_deleted += 1

    # If delete_artifacts, also sweep workspace artifact run dirs whose journal
    # is already gone and that are old enough — but never latest while keep_latest.
    if delete_artifacts and art_root.exists():
        for slug_dir in list(art_root.iterdir()):
            if not slug_dir.is_dir() or not _jailed(slug_dir, art_root):
                continue
            slug = slug_dir.name
            runs_folder = slug_dir / "runs"
            if not runs_folder.is_dir():
                continue
            current_latest = latest_run_id(slug)
            for run_folder in list(runs_folder.iterdir()):
                if not run_folder.is_dir():
                    continue
                rid = run_folder.name
                if rid in deleted_ids:
                    continue
                if keep_latest and current_latest == rid:
                    continue
                journal = runs_root / rid
                # Only delete orphaned artifact folders (journal already gone)
                # or ones whose journal was deleted above (already handled).
                if journal.exists():
                    continue
                try:
                    mtime = datetime.fromtimestamp(run_folder.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if mtime >= cutoff and days != 0:
                    continue
                bytes_freed += _rmtree_jailed(run_folder, art_root)
                artifacts_deleted += 1
            retarget_latest(slug)
            _prune_empty_runs_dir(slug)

    return {
        "deleted": runs_deleted + cache_deleted + artifacts_deleted,
        "runs_deleted": runs_deleted,
        "cache_entries_deleted": cache_deleted,
        "artifacts_deleted": artifacts_deleted,
        "bytes_freed": bytes_freed,
        "runs_skipped_too_new": skipped_too_new,
        "runs_skipped_latest": skipped_latest,
        "runs_skipped_running": skipped_running,
        "older_than_days": days,
        "keep_latest": keep_latest,
    }
