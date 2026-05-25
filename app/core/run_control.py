# app/core/run_control.py
"""Run control plane — in-process active run registry and pause/cancel signals.

Extracted from run_manager.py. Responsible for:
  - _ACTIVE_RUNS registry (process-local dict of live RunManager instances)
  - register_active_run / get_active_run / deregister_active_run
  - pause / resume / cancel / wait_if_paused / is_paused / is_cancelled

SCALABILITY NOTE (SCALE-1):
This registry is process-local. In a multi-worker deployment (e.g.
``uvicorn --workers 4``), pause/resume/cancel requests must be routed to the
worker that owns the run. Requests routed to a different worker will return
"run not active" (HTTP 404 from the run_control router).

Migration path: replace ``_ACTIVE_RUNS`` with a Redis-backed store.
The interface (register/get/deregister) is intentionally minimal so the
swap is a single-module change with no callers to update.
"""
from __future__ import annotations

import threading

_ACTIVE_RUNS: dict[str, "RunManager"] = {}  # type: ignore[name-defined]
_ACTIVE_RUNS_LOCK = threading.Lock()


def register_active_run(run: "RunManager") -> None:  # type: ignore[name-defined]
    """Register a RunManager as the active run for its run_id."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[run.run_id] = run


def get_active_run(run_id: str) -> "RunManager | None":  # type: ignore[name-defined]
    """Return the active RunManager for run_id, or None if not active.

    SA-RC2: Returns None in all of these cases:
      - The run never existed in this process
      - The run has already completed and been deregistered
      - The run is executing on a different worker (SCALE-1)
    The caller cannot distinguish between these cases from the return value
    alone. If precise error reporting is needed, consider typed exceptions:
    RunNotFoundError, RunCompletedError, RunOnOtherWorkerError.
    """
    with _ACTIVE_RUNS_LOCK:
        return _ACTIVE_RUNS.get(run_id)


def deregister_active_run(run_id: str) -> None:
    """Remove a run from the active registry (called in finally block)."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS.pop(run_id, None)
