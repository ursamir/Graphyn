# app/core/pipelines/project_pipelines.py
"""
Bounded Context:  BC6 — Observability & Storage / project assets
Responsibility:   Persist project-owned Graph IR under
                  workspace/datasets/output/{project}/pipelines/{name}.graph.json.
Owns:             list/get/put/delete helpers, name validation, the
                  content-hash ``resource_version`` token, and the reentrant
                  per-resource lock (resource_lock) shared with
                  pipeline_environments, ship_packages, model_registry and
                  ProjectManager.
Public Surface:   SAFE_PIPELINE_NAME_RE, pipelines_dir, list_pipelines,
                  get_pipeline, put_pipeline, delete_pipeline, resource_lock,
                  pipeline_resource_version.
Must NOT:         Import app.domain (callers pass project Path) or app.api.
Dependencies:     hashlib, json, os, re, threading, pathlib, tempfile;
                  app.core.persist.file_lock; app.core.ir.loader;
                  app.core.ir.secret_policy.
Reason To Change: Project pipeline storage layout or validation rules change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.ir.loader import dump_ir, load_ir
from app.core.ir.secret_policy import assert_no_inline_secrets

log = logging.getLogger(__name__)

SAFE_PIPELINE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def pipelines_dir(project_dir: Path) -> Path:
    return project_dir / "pipelines"


class _LockEntry:
    __slots__ = ("rlock", "depth", "fh")

    def __init__(self) -> None:
        self.rlock = threading.RLock()
        self.depth = 0
        self.fh: Any = None


_LOCKS: dict[str, _LockEntry] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def resource_lock(lock_path: Path, *, create_parent: bool = True) -> Iterator[None]:
    """Hold an exclusive, reentrant lock on ``lock_path`` (threads + processes).

    A per-path ``RLock`` serializes threads in this process; the first
    (outermost) holder also takes an ``fcntl``/``msvcrt`` lock on the file via
    :mod:`app.core.persist.file_lock` so other processes serialize too. Nested use by
    the same thread only bumps a depth counter (no self-deadlock).

    ``create_parent=False`` makes a vanished parent dir raise
    ``FileNotFoundError`` instead of being recreated (callers whose resource
    may be deleted concurrently, e.g. a project directory).
    """
    from app.core.persist.file_lock import acquire, release

    key = str(Path(lock_path).absolute())
    with _LOCKS_GUARD:
        entry = _LOCKS.get(key)
        if entry is None:
            entry = _LOCKS[key] = _LockEntry()
    with entry.rlock:
        if entry.depth == 0:
            if create_parent:
                Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
            fh = open(lock_path, "a+b")
            try:
                acquire(fh, exclusive=True)
            except BaseException:
                fh.close()
                raise
            entry.fh = fh
        entry.depth += 1
        try:
            yield
        finally:
            entry.depth -= 1
            if entry.depth == 0:
                fh, entry.fh = entry.fh, None
                try:
                    release(fh)
                finally:
                    fh.close()


def _pipeline_lock_path(project_dir: Path, name: str) -> Path:
    return pipelines_dir(project_dir) / f".{_validate_pipeline_name(name)}.lock"


def pipeline_lock(project_dir: Path, name: str):
    """Lock guarding read-check-write of one pipeline (head, versions, envs)."""
    return resource_lock(_pipeline_lock_path(project_dir, name))


def _rv_from_bytes(raw: bytes) -> str:
    """Opaque content token: identical bytes ⇔ identical version.

    Replaces the old ``st_mtime_ns`` token (two writes inside one filesystem
    timestamp tick looked identical, and GET stat'ed after reading).
    """
    return "sha256-" + hashlib.sha256(raw).hexdigest()[:32]


def pipeline_resource_version(project_dir: Path, name: str) -> str:
    """Current resource_version for the pipeline head (``"0"`` when absent)."""
    path = _pipeline_path(project_dir, name)
    try:
        return _rv_from_bytes(path.read_bytes())
    except FileNotFoundError:
        return "0"


def _rv_matches(path: Path, expected: str) -> tuple[bool, str]:
    """Compare ``expected`` to the head; accepts legacy mtime tokens once."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return str(expected) == "0", "0"
    current = _rv_from_bytes(raw)
    if str(expected) == current:
        return True, current
    # Back-compat: tokens issued before the content-hash switch were mtime_ns.
    if str(expected).isdigit():
        try:
            if str(expected) == str(path.stat().st_mtime_ns):
                return True, current
        except OSError:
            pass
    return False, current


def _validate_pipeline_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or not SAFE_PIPELINE_NAME_RE.match(cleaned):
        raise ValueError(
            f"Invalid pipeline name {name!r}. "
            "Use letters, digits, hyphens, and underscores only."
        )
    return cleaned


def _pipeline_path(project_dir: Path, name: str) -> Path:
    safe = _validate_pipeline_name(name)
    base = pipelines_dir(project_dir).resolve()
    path = (base / f"{safe}.graph.json").resolve()
    if not str(path).startswith(str(base) + "/") and path.parent != base:
        raise ValueError("Invalid pipeline path")
    return path


def list_pipelines(project_dir: Path) -> list[dict[str, Any]]:
    """Return summaries for ``*.graph.json`` under the project pipelines dir."""
    root = pipelines_dir(project_dir)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.graph.json")):
        name = path.name[: -len(".graph.json")]
        if not SAFE_PIPELINE_NAME_RE.match(name):
            continue
        meta_name = None
        node_count = 0
        updated_at = None
        try:
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            updated_at = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                nodes = data.get("nodes")
                node_count = len(nodes) if isinstance(nodes, list) else 0
                md = data.get("metadata")
                if isinstance(md, dict):
                    meta_name = md.get("name")
        except Exception:
            log.debug("Skipping unreadable pipeline %s", path, exc_info=True)
        items.append(
            {
                "name": name,
                "updated_at": updated_at,
                "node_count": node_count,
                "graph_name": meta_name,
            }
        )
    return items


def get_pipeline(project_dir: Path, name: str) -> dict[str, Any]:
    path = _pipeline_path(project_dir, name)
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline '{name}' not found")
    # Read the bytes once: body and resource_version describe the same write.
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Pipeline '{name}' not found") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to read pipeline '{name}': {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid pipeline '{name}'")
    # Validate shape
    load_ir(data)
    rv = _rv_from_bytes(raw)
    data = dict(data)
    data["resource_version"] = rv
    return data


def put_pipeline(
    project_dir: Path,
    name: str,
    payload: dict[str, Any],
    *,
    project_name: str,
    expected_resource_version: str | None = None,
    via_if_match: bool = False,
) -> dict[str, Any]:
    """Validate, stamp project, and atomically write the pipeline Graph IR.

    With ``expected_resource_version`` the compare and the write happen under
    the pipeline lock, so two If-Match writers cannot both win.
    """
    if not isinstance(payload, dict):
        raise ValueError("Pipeline body must be a Graph IR object")
    path_early = _pipeline_path(project_dir, name)
    with pipeline_lock(project_dir, name):
        if expected_resource_version is not None:
            ok, current_rv = _rv_matches(path_early, str(expected_resource_version))
            if not ok:
                # Imported lazily to avoid circular import with api layer
                from app.core.errors import VersionConflict
                raise VersionConflict(via_if_match=via_if_match, current=current_rv)
        return _put_pipeline_unlocked(project_dir, name, payload, project_name=project_name)


def _put_pipeline_unlocked(
    project_dir: Path,
    name: str,
    payload: dict[str, Any],
    *,
    project_name: str,
) -> dict[str, Any]:
    # Strip concurrency token from IR payload if present
    payload = {k: v for k, v in payload.items() if k != "resource_version"}
    graph = load_ir(payload)
    assert_no_inline_secrets(graph)

    meta = graph.metadata
    updates: dict[str, Any] = {"project": project_name}
    if not getattr(meta, "name", None):
        updates["name"] = name
    new_meta = meta.model_copy(update=updates)
    graph = graph.model_copy(update={"metadata": new_meta})
    assert_no_inline_secrets(graph)

    out = dump_ir(graph)
    path = _pipeline_path(project_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    raw = (json.dumps(out, indent=2) + "\n").encode("utf-8")
    try:
        with open(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_path, 0o644)
        except OSError:
            pass
        tmp_path.replace(path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    rv = _rv_from_bytes(raw)
    out = dict(out)
    out["resource_version"] = rv
    return out


def delete_pipeline(project_dir: Path, name: str) -> None:
    path = _pipeline_path(project_dir, name)
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline '{name}' not found")
    with pipeline_lock(project_dir, name):
        if not path.is_file():
            raise FileNotFoundError(f"Pipeline '{name}' not found")
        path.unlink()
