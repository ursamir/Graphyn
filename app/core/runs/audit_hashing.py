# app/core/runs/audit_hashing.py
"""
Bounded Context:  BC6 — Observability (Prove pillar / audit records)
Responsibility:   Deterministic, cached content hashing of files and
                  directory trees for run audit records (external inputs,
                  run outputs, plugin source code).
Owns:             hash_file(), hash_path(), tree_listing(); the per-process
                  file-hash cache keyed by (abs path, mtime_ns, size) and the
                  per-tree cache keyed by (abs path, stat signature), plus a
                  small persisted file-hash cache under ``{project}/cache``.
Public Surface:   hash_file(path) -> str, hash_path(path, ...) -> dict,
                  tree_listing(path, ...) -> list[tuple[rel, size, sha|None]],
                  DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES, clear_hash_caches()
Must NOT:         Import app.api, orchestrator or domain code; raise on
                  unreadable files (they hash as an ``error`` marker).
Dependencies:     stdlib (hashlib, json, os, threading, pathlib),
                  app.core.config.cache_dir (lazy).
Reason To Change: Hash format / huge-tree policy / cache persistence changes.

Tree hash format (``sha256:`` prefix)
-------------------------------------
Files are walked in sorted relative-path order (dot-files, ``__pycache__``
and ``*.pyc`` skipped). ``content`` mode hashes ``"<rel>\\t<size>\\t<sha256>\\n"``
lines; ``manifest`` mode (trees above ``max_bytes`` / ``max_files``) hashes
``"<rel>\\t<size>\\n"`` lines only and reports ``hash_mode: "manifest"``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = int(os.environ.get("GRAPHYN_AUDIT_HASH_MAX_BYTES", str(512 * 1024 * 1024)))
DEFAULT_MAX_FILES = int(os.environ.get("GRAPHYN_AUDIT_HASH_MAX_FILES", "20000"))
_SKIP_DIRS = frozenset({"__pycache__", ".git", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"})
_PERSIST_MAX = 50_000
_CHUNK = 1024 * 1024

_lock = threading.RLock()
_file_cache: dict[str, tuple[int, int, str]] = {}
_tree_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_persist_loaded = False
_persist_dirty = 0


def clear_hash_caches() -> None:
    """Drop in-memory caches (tests)."""
    global _persist_loaded, _persist_dirty
    with _lock:
        _file_cache.clear()
        _tree_cache.clear()
        _persist_loaded = False
        _persist_dirty = 0


def _persist_path() -> Path | None:
    try:
        from app.core.config import cache_dir

        return cache_dir() / "audit_file_hashes.json"
    except Exception:
        return None


def _load_persisted() -> None:
    global _persist_loaded
    if _persist_loaded:
        return
    _persist_loaded = True
    path = _persist_path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    for key, val in data.items():
        if isinstance(val, list) and len(val) == 3:
            try:
                _file_cache.setdefault(str(key), (int(val[0]), int(val[1]), str(val[2])))
            except (TypeError, ValueError):
                continue


def _save_persisted() -> None:
    global _persist_dirty
    if _persist_dirty <= 0:
        return
    path = _persist_path()
    if path is None:
        return
    try:
        items = list(_file_cache.items())[-_PERSIST_MAX:]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({k: list(v) for k, v in items}), encoding="utf-8")
        os.replace(tmp, path)
        _persist_dirty = 0
    except Exception:
        log.debug("audit hash cache persist failed", exc_info=True)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_file(path: str | Path, *, st: os.stat_result | None = None) -> str:
    """Return the sha256 hex digest of a file (cached by mtime_ns + size)."""
    global _persist_dirty
    p = Path(path)
    key = os.path.abspath(p)
    if st is None:
        st = p.stat()
    with _lock:
        _load_persisted()
        hit = _file_cache.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
    digest = _sha256_file(p)
    with _lock:
        _file_cache[key] = (st.st_mtime_ns, st.st_size, digest)
        _persist_dirty += 1
    return digest


def _iter_files(root: Path) -> Iterable[tuple[str, Path, os.stat_result]]:
    """Yield (rel_posix, path, stat) for regular files under root, sorted."""
    seen_real: set[str] = set()
    out: list[tuple[str, Path, os.stat_result]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen_real:
            dirnames[:] = []
            continue
        seen_real.add(real)
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in filenames:
            if name.startswith(".") or name.endswith(".pyc"):
                continue
            fp = Path(dirpath) / name
            try:
                st = fp.stat()
            except OSError:
                continue
            if not os.path.isfile(fp):
                continue
            rel = fp.relative_to(root).as_posix()
            out.append((rel, fp, st))
    out.sort(key=lambda t: t[0])
    return out


def tree_listing(
    root: str | Path, *, with_content: bool = True, limit: int | None = None
) -> list[tuple[str, int, str | None]]:
    """Sorted ``(rel, size, sha256|None)`` for files under a directory (or one file)."""
    p = Path(root)
    if p.is_file():
        st = p.stat()
        return [(p.name, st.st_size, hash_file(p, st=st) if with_content else None)]
    rows: list[tuple[str, int, str | None]] = []
    for rel, fp, st in _iter_files(p):
        if limit is not None and len(rows) >= limit:
            break
        sha = None
        if with_content:
            try:
                sha = hash_file(fp, st=st)
            except OSError:
                sha = "error"
        rows.append((rel, st.st_size, sha))
    return rows


def hash_path(
    path: str | Path,
    *,
    max_bytes: int | None = None,
    max_files: int | None = None,
) -> dict[str, Any]:
    """Hash a file or directory tree.

    Returns ``{kind: file|dir|missing, content_hash, hash_mode, file_count,
    total_bytes}``. Trees above ``max_bytes`` or ``max_files`` fall back to
    ``hash_mode: "manifest"`` (relative paths + sizes only) to stay fast.
    """
    p = Path(path)
    max_bytes = DEFAULT_MAX_BYTES if max_bytes is None else int(max_bytes)
    max_files = DEFAULT_MAX_FILES if max_files is None else int(max_files)
    try:
        if not p.exists():
            return {"kind": "missing", "content_hash": None, "hash_mode": None, "file_count": 0, "total_bytes": 0}
        if p.is_file():
            st = p.stat()
            digest = hash_file(p, st=st)
            return {
                "kind": "file",
                "content_hash": f"sha256:{digest}",
                "hash_mode": "content",
                "file_count": 1,
                "total_bytes": st.st_size,
            }
        files = list(_iter_files(p))
    except OSError as exc:
        return {"kind": "missing", "content_hash": None, "hash_mode": None, "file_count": 0,
                "total_bytes": 0, "error": str(exc)}
    total = sum(st.st_size for _rel, _fp, st in files)
    mode = "content" if (total <= max_bytes and len(files) <= max_files) else "manifest"
    sig = hashlib.sha256()
    for rel, _fp, st in files:
        sig.update(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}\n".encode("utf-8", "surrogateescape"))
    cache_key = (os.path.abspath(p), sig.hexdigest(), mode)
    with _lock:
        cached = _tree_cache.get(cache_key)
    if cached is not None:
        return dict(cached)
    h = hashlib.sha256()
    for rel, fp, st in files:
        if mode == "content":
            try:
                digest = hash_file(fp, st=st)
            except OSError:
                digest = "error"
            h.update(f"{rel}\t{st.st_size}\t{digest}\n".encode("utf-8", "surrogateescape"))
        else:
            h.update(f"{rel}\t{st.st_size}\n".encode("utf-8", "surrogateescape"))
    result = {
        "kind": "dir",
        "content_hash": f"sha256:{h.hexdigest()}",
        "hash_mode": mode,
        "file_count": len(files),
        "total_bytes": total,
    }
    with _lock:
        if len(_tree_cache) > 2048:
            _tree_cache.clear()
        _tree_cache[cache_key] = dict(result)
        _save_persisted()
    return result
