# app/core/host/readiness.py
"""
Bounded Context:  BC6 — Observability & Storage (operational readiness)
Responsibility:   Shared readiness snapshot (OPS-014 / PERS-021 / OPS-007):
                  registry readiness, store_corrupt markers at known index
                  paths, disk-full and project-dir writability probes.
Owns:             readiness_snapshot(), clear_readiness_cache(),
                  catalog_summary() (non-blocking ``catalog`` section:
                  installed vs bundled plugins, partial_catalog warning).
Public Surface:   readiness_snapshot(max_age_s=None) -> dict; used by REST
                  /system/readiness, MCP readiness, and the PERS-020 store
                  guard (store_integrity.readiness_store_corrupt).
Must NOT:         Import app.api / app.domain; recursively glob the workspace
                  (artifact trees can be huge) — only known index locations.
Dependencies:     app.core.config, app.core.nodes, app.core.plugins (store /
                  manifest, lazy), stdlib (os, shutil, time, tomllib).
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
        _CATALOG_CACHE.clear()


_CATALOG_TTL_S = 30.0
_CATALOG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _bundled_manifest_summary(root: Path) -> tuple[int, set[str]]:
    """(manifest count, declared node types) for ``PluginPackage/*/*/plugin.toml``."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py<3.11
        tomllib = None  # type: ignore[assignment]
    from app.core.config import bundled_plugin_allowlist

    allow = bundled_plugin_allowlist()
    count = 0
    node_types: set[str] = set()
    try:
        tomls = sorted(root.glob("*/*/plugin.toml")) if root.is_dir() else []
    except OSError:
        tomls = []
    for path in tomls:
        data: dict[str, Any] = {}
        if tomllib is not None:
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        plugin = data.get("plugin") if isinstance(data.get("plugin"), dict) else {}
        name = str(plugin.get("name") or path.parent.name)
        if allow is not None and name not in allow:
            continue
        count += 1
        declared = plugin.get("node_types") or data.get("node_types") or []
        if isinstance(declared, list):
            node_types.update(str(n) for n in declared if n)
    return count, node_types


def catalog_summary(registered_node_types: int | None = None) -> dict[str, Any]:
    """Informational catalog coverage — never affects ``ready``.

    ``partial_catalog`` is True when fewer plugins are installed+enabled than
    bundled manifests exist (after ``GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST``), or
    the registry has fewer node types than the bundled manifests declare.
    Cached for 30s (the PluginPackage glob is cheap but not free).
    """
    from app.core.config import plugin_package_dir

    root = plugin_package_dir()
    key = str(root)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CATALOG_CACHE.get(key)
    if hit is not None and now - hit[0] <= _CATALOG_TTL_S:
        base = copy.deepcopy(hit[1])
    else:
        bundled, declared = _bundled_manifest_summary(root)
        installed = enabled = 0
        try:
            from app.core.plugins.store import PluginStore

            records = PluginStore().list()
            installed = len(records)
            enabled = sum(1 for r in records if getattr(r, "enabled", False))
        except Exception:
            pass
        base = {
            "bundled_plugins": bundled,
            "bundled_node_types": len(declared),
            "installed_plugins": installed,
            "enabled_plugins": enabled,
            "plugin_package_dir": str(root),
        }
        with _CACHE_LOCK:
            _CATALOG_CACHE[key] = (now, copy.deepcopy(base))
    warnings: list[str] = []
    if base["bundled_plugins"] and base["enabled_plugins"] < base["bundled_plugins"]:
        warnings.append(
            f"{base['enabled_plugins']} of {base['bundled_plugins']} bundled plugins are "
            "installed+enabled; graphs using the others fail validation. "
            "Set GRAPHYN_AUTO_INSTALL_PLUGINS=1 (installs every PluginPackage manifest at "
            "startup) or install individually via POST /api/v1/plugins/install."
        )
    if (
        registered_node_types is not None
        and base["bundled_node_types"]
        and registered_node_types < base["bundled_node_types"]
    ):
        warnings.append(
            f"registry has {registered_node_types} node types; bundled manifests declare "
            f"{base['bundled_node_types']}"
        )
    base["registered_node_types"] = registered_node_types
    base["partial_catalog"] = bool(warnings)
    base["warnings"] = warnings
    return base


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
    # F19 / F-03: ``worker_count`` is *live* workers (fresh heartbeat), the same
    # set GET /workers returns; stale registrations are reported separately so
    # readiness can no longer claim a worker that is gone.
    worker_count = 0
    stale_worker_count = 0
    try:
        from app.core.distributed.registry import get_worker_registry

        _wreg = get_worker_registry()
        _all = _wreg.list(include_stale=True)
        worker_count = len([w for w in _all if not _wreg.is_stale(w)])
        stale_worker_count = len(_all) - worker_count
    except Exception:
        worker_count = 0
        stale_worker_count = 0
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
    node_type_count = len(registry) if reg_ready else 0
    try:
        catalog = catalog_summary(node_type_count if reg_ready else None)
    except Exception as exc:  # informational only — never fail readiness
        catalog = {"error": str(exc)[:200], "partial_catalog": None, "warnings": []}
    return {
        "status": status,
        "ready": ready,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend_id,
        "backend_mode": backend_mode,
        "worker_count": worker_count,
        "stale_worker_count": stale_worker_count,
        "registry_ready": reg_ready,
        "registry_init_error": init_err,
        "node_type_count": node_type_count,
        # Informational (does not change ``ready``): installed vs bundled.
        "catalog": catalog,
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
