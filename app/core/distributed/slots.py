# app/core/distributed/slots.py
"""
Bounded Context:  BC5 — Execution Runtime (F18)
Responsibility:   Per-worker concurrency slot booking helpers (max/used/free).
                  Slots mirror ``WorkerInfo.max_claimed``; used count is the
                  number of claimed/running jobs held by the worker.
Owns:             worker_max_slots(), worker_used_slots(), worker_free_slots(),
                  slots_bookable(), slot_snapshot().
Public Surface:   Functions above.
Must NOT:         Import app.api / invent a parallel broker.
Dependencies:     app.core.distributed.quotas (worker_max_claimed), queue counts.
Reason To Change: Slot accounting or book/release semantics evolve.
"""
from __future__ import annotations

from typing import Any


def worker_max_slots(worker: Any) -> int | None:
    """Alias for ``max_claimed`` (None = unlimited)."""
    from app.core.distributed.quotas import worker_max_claimed

    return worker_max_claimed(worker)


def worker_used_slots(
    worker_id: str,
    *,
    jobs: list[Any] | dict[str, Any] | None = None,
) -> int:
    """Count claimed/running jobs held by ``worker_id`` (occupied slots)."""
    if isinstance(jobs, dict):
        n = 0
        for payload in jobs.values():
            if isinstance(payload, dict):
                status = payload.get("status")
                claimed_by = payload.get("claimed_by")
            else:
                status = getattr(payload, "status", None)
                claimed_by = getattr(payload, "claimed_by", None)
            if status in ("claimed", "running") and claimed_by == worker_id:
                n += 1
        return n
    from app.core.distributed.quotas import count_active_claims

    return count_active_claims(worker_id=worker_id, jobs=jobs)


def worker_free_slots(
    worker: Any,
    *,
    jobs: list[Any] | dict[str, Any] | None = None,
) -> int | None:
    """Free slots remaining, or None when unlimited."""
    limit = worker_max_slots(worker)
    if limit is None:
        return None
    wid = getattr(worker, "worker_id", None) or ""
    used = worker_used_slots(wid, jobs=jobs)
    return max(0, int(limit) - int(used))


def slots_bookable(
    worker: Any,
    *,
    jobs: list[Any] | dict[str, Any] | None = None,
) -> bool:
    """True when this worker can book one more concurrent slot."""
    free = worker_free_slots(worker, jobs=jobs)
    if free is None:
        return True
    return free > 0


def slot_snapshot(
    worker: Any,
    *,
    jobs: list[Any] | dict[str, Any] | None = None,
) -> dict[str, int | None]:
    """API-facing slot view: max_slots / used_slots / free_slots."""
    wid = getattr(worker, "worker_id", None) or ""
    mx = worker_max_slots(worker)
    used = worker_used_slots(wid, jobs=jobs)
    free = None if mx is None else max(0, int(mx) - int(used))
    return {"max_slots": mx, "used_slots": used, "free_slots": free}
