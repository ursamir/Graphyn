# app/core/host/readiness.py
"""
Bounded Context:  BC6 — Observability & Storage (operational readiness)
Responsibility:   Shared readiness snapshot (OPS-014 / PERS-021 / OPS-007):
                  registry readiness, store_corrupt markers at known index
                  paths, disk-full and project-dir writability probes.
Owns:             readiness_snapshot(), clear_readiness_cache().
Public Surface:   readiness_snapshot(max_age_s=None) -> dict; used by REST
                  /system/readiness, MCP readiness, and the PERS-020 store
                  guard (store_integrity.readiness_store_corrupt).
Must NOT:         Import app.api / app.domain; recursively glob the workspace
                  (artifact trees can be huge) — only known index locations.
Dependencies:     app.core.config, app.core.nodes, stdlib (os, shutil, time).
Reason To Change: New readiness signal, or index / quarantine file layout.

Caching: guarded GETs call this on every request, so results are cached per
(project_dir, backend, registry_ready) for ``GRAPHYN_READINESS_CACHE_S``
seconds (default 5; 0 disables). Probes pass ``max_age_s=0`` for a fresh read.
"""
from __future__ import annotations

import copy
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_CACHE_S = 5.0
_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str, bool], tuple[float, dict[str, Any]]] = {}


def _cache_ttl() -> float:
    raw = (os.environ.get("GRAPHYN_READINESS_CACHE_S") or "").strip()
    if not raw:
        return _DEFAULT_CACHE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_CACHE_S


def clear_readiness_cache() -> None:
    """Drop cached snapshots (tests / after repairing a corrupt index)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _any_match(directory: Path, pattern: str) -> bool:
    try:
        if not directory.is_dir():
            return False
        return any(directory.glob(pattern))
    except OSError:
        return False


def _store_corrupt_markers(root: Path) -> bool:
    """True when a ``*.corrupt`` marker sits at a known critical index path.

    Bounded (non-recursive) replacements for the former ``artifacts/**`` and
    ``**/registry.json.corrupt`` walks: artifact store index + by_run/by_name
    secondary indexes + per-artifact record dirs (one level), model registry
    (``artifacts/_registry``), and the workspace plugin registry. Timestamped quarantine copies (``*.corrupt.<ts>``) are
    self-healed indexes and do not flag the store.
    """
    artifacts = root / "artifacts"
    checks: list[tuple[Path, str]] = [
        (artifacts, "*.corrupt"),
        (artifacts / "by_run", "*.corrupt"),
        (artifacts / "by_name", "*.corrupt"),
        (artifacts / "_registry", "*.corrupt"),
        (artifacts, "*/*.json.corrupt"),
        (root / "plugins", "*.json.corrupt"),
    ]
    for directory, pattern in checks:
        if _any_match(directory, pattern):
            return True
    candidates = [root / "registry.json.corrupt", root / "plugins" / "registry.json.corrupt"]
    for path in candidates:
        try:
            if path.exists():
                return True
        except OSError:
            continue
    return False


def readiness_snapshot(max_age_s: float | None = None) -> dict[str, Any]:
    """Return readiness payload used by REST and MCP.

    ``max_age_s`` bounds how stale a cached snapshot may be (``None`` →
    ``GRAPHYN_READINESS_CACHE_S``, default 5s; ``0`` → always recompute).
    """
    from app.core.config import project_dir
    from app.core.nodes import is_registry_ready

    ttl = _cache_ttl() if max_age_s is None else max(0.0, float(max_age_s))
    backend_id = (os.environ.get("GRAPHYN_BACKEND") or "local_python").strip() or "local_python"
    key = (str(project_dir()), backend_id, bool(is_registry_ready()))
    now = time.monotonic()
    if ttl > 0:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit is not None and now - hit[0] <= ttl:
            return copy.deepcopy(hit[1])
    snap = _compute_snapshot()
    with _CACHE_LOCK:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = (now, snap)
    return copy.deepcopy(snap)


def _compute_snapshot() -> dict[str, Any]:
    from app.core.config import cache_dir, project_dir, runs_dir
    from app.core.nodes import is_registry_ready, registry, registry_init_error

    backend_id = (os.environ.get("GRAPHYN_BACKEND") or "local_python").strip() or "local_python"
    backend_mode = "distributed" if backend_id == "distributed" else "local"
    worker_count = 0
    try:
        from app.core.distributed.registry import get_worker_registry

        worker_count = len(get_worker_registry().list(include_stale=True))
    except Exception:
        worker_count = 0
    reg_ready = is_registry_ready()
    init_err = registry_init_error()

    store_corrupt = False
    try:
        store_corrupt = _store_corrupt_markers(project_dir())
    except Exception:
        pass

    disk_full = False
    try:
        usage = shutil.disk_usage(str(project_dir()))
        if usage.free < 1024 * 1024:
            disk_full = True
    except Exception:
        pass

    writable = True
    try:
        probe = project_dir() / ".readiness_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        writable = False
        if getattr(exc, "errno", None) == 28:
            disk_full = True

    ready = bool(reg_ready) and not store_corrupt and not disk_full and writable
    status = "ready" if ready else ("failed" if (init_err or store_corrupt or disk_full) else "starting")
    return {
        "status": status,
        "ready": ready,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend_id,
        "backend_mode": backend_mode,
        "worker_count": worker_count,
        "registry_ready": reg_ready,
        "registry_init_error": init_err,
        "node_type_count": len(registry) if reg_ready else 0,
        "checks": {
            "runs_dir_exists": runs_dir().exists(),
            "cache_dir_exists": cache_dir().exists(),
            "project_dir_exists": project_dir().exists(),
            "registry_ready": reg_ready,
            "store_corrupt": store_corrupt,
            "disk_full": disk_full,
            "project_dir_writable": writable,
        },
    }
