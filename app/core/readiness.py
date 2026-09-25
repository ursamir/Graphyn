# app/core/readiness.py
"""Shared readiness snapshot (OPS-014 / PERS-021 / OPS-007)."""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from typing import Any


def readiness_snapshot() -> dict[str, Any]:
    """Return readiness payload used by REST and MCP."""
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
        root = project_dir()
        for pattern in (
            "artifacts/**/*.corrupt",
            "artifacts/**/*.json.corrupt",
            "plugins/**/*.json.corrupt",
            "**/registry.json.corrupt",
        ):
            if any(root.glob(pattern)):
                store_corrupt = True
                break
        if (root / "plugins" / "registry.json.corrupt").exists():
            store_corrupt = True
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
