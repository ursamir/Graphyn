# unit_test/f19/test_f19_readiness_workers.py
"""F19 / F-03 — readiness counts live workers only (stale registrations reported apart).

Before: readiness used ``list(include_stale=True)`` and reported
``worker_count: 1`` while ``GET /workers`` (live only) returned ``[]``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_readiness_worker_count_excludes_stale():
    from app.core.distributed.models import WorkerInfo
    from app.core.distributed.registry import reset_worker_registry
    from app.core.host.readiness import _compute_snapshot

    reg = reset_worker_registry()
    try:
        reg.register(WorkerInfo(worker_id="live-1"))
        reg.register(WorkerInfo(worker_id="gone-1"))
        old = datetime.now(timezone.utc) - timedelta(days=1)
        with reg._lock:
            reg._workers["gone-1"] = reg._workers["gone-1"].model_copy(update={"heartbeat_at": old})
        assert [w.worker_id for w in reg.list()] == ["live-1"]
        snap = _compute_snapshot()
        assert snap["worker_count"] == 1
        assert snap["stale_worker_count"] == 1
    finally:
        reset_worker_registry()
