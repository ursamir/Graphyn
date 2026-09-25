# app/core/shutdown.py
"""
Bounded Context:  Platform Infrastructure / Ops
Responsibility:   Graceful shutdown drain (OPS-005 / OPS-011).
Owns:             Process-local draining flag; wait/cancel active runs.
Public Surface:   begin_drain, is_draining, assert_accepting_runs,
                  list_local_active_run_ids, drain_active_runs
Must NOT:         Import app.api.
Dependencies:     stdlib, app.core.run_control (lazy).
Reason To Change: Drain grace policy or active-run registry changes.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

_draining = False
_drain_lock = threading.Lock()

# Default grace for in-flight runs on SIGTERM (seconds). Override via env.
_DEFAULT_GRACE_S = 30.0


def begin_drain() -> None:
    """Mark the process as draining — new runs should be refused."""
    global _draining
    with _drain_lock:
        _draining = True
    log.info("shutdown: drain begun — refusing new runs")


def is_draining() -> bool:
    return _draining


def reset_drain_for_tests() -> None:
    """Test-only: clear draining flag."""
    global _draining
    with _drain_lock:
        _draining = False


def assert_accepting_runs() -> None:
    """Raise RuntimeError with code draining if new runs must not start."""
    if _draining:
        raise RuntimeError("draining: control plane is shutting down; refusing new runs")


def list_local_active_run_ids() -> list[str]:
    """Return run_ids registered in this process's active-run dict."""
    from app.core import run_control

    with run_control._ACTIVE_RUNS_LOCK:  # noqa: SLF001 — intentional drain introspect
        return list(run_control._ACTIVE_RUNS.keys())


def drain_active_runs(*, grace_seconds: float | None = None) -> dict[str, Any]:
    """Wait for in-flight runs up to grace, then cancel remainder (best-effort).

    Returns a summary dict for logging / audit.
    """
    if grace_seconds is None:
        raw = (os.environ.get("GRAPHYN_SHUTDOWN_GRACE_S") or "").strip()
        try:
            grace_seconds = float(raw) if raw else _DEFAULT_GRACE_S
        except ValueError:
            grace_seconds = _DEFAULT_GRACE_S

    begin_drain()
    deadline = time.monotonic() + max(0.0, float(grace_seconds))
    initial = list_local_active_run_ids()
    cancelled: list[str] = []
    waited_for: list[str] = []

    while True:
        active = list_local_active_run_ids()
        if not active:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)

    remaining = list_local_active_run_ids()
    from app.core.run_control import get_active_run

    for rid in remaining:
        run = get_active_run(rid)
        if run is None:
            continue
        try:
            run.cancel()
            cancelled.append(rid)
        except Exception as exc:
            log.warning("shutdown: failed to cancel run %s: %s", rid, exc)

    # Brief extra wait after cancel signals
    end_soft = time.monotonic() + min(5.0, max(1.0, float(grace_seconds) * 0.1))
    while list_local_active_run_ids() and time.monotonic() < end_soft:
        time.sleep(0.1)

    final = list_local_active_run_ids()
    waited_for = [r for r in initial if r not in final and r not in cancelled]

    # Best-effort audit flush note
    try:
        from app.core.audit import record_audit

        record_audit(
            actor="system",
            action="ops.shutdown_drain",
            resource_type="control_plane",
            resource_id="self",
            result="success",
            actor_kind="system",
            meta={
                "grace_seconds": grace_seconds,
                "initial_active": initial,
                "cancelled": cancelled,
                "still_active": final,
            },
        )
    except Exception:
        log.debug("shutdown: audit flush skipped", exc_info=True)

    summary = {
        "grace_seconds": grace_seconds,
        "initial_active": initial,
        "waited_completed": waited_for,
        "cancelled": cancelled,
        "still_active": final,
    }
    log.info("shutdown: drain complete %s", summary)
    return summary
