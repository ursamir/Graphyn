# app/core/run_manager.py
"""
Bounded Context:  BC6 — Observability & Storage (re-export shim)
Responsibility:   Backward-compatibility shim. Re-exports all public names
                  from run_journal.py and run_control.py.
Owns:             Re-export declarations only — no implementation.
Public Surface:   RunManager, register_active_run, get_active_run,
                  deregister_active_run — all previously importable from
                  app.core.run_manager.
Must NOT:         Contain any implementation logic. Must not be the canonical
                  import path for new code — import from run_journal or
                  run_control directly. Must not re-export private names
                  (_ACTIVE_RUNS, _ACTIVE_RUNS_LOCK, _WORKSPACE).
Dependencies:     app.core.run_journal, app.core.run_control.
Reason To Change: A re-exported name is removed or renamed in its source module.

All implementation has been extracted into focused modules:
  - app.core.run_journal  — RunManager class (persistence + control)
  - app.core.run_control  — register_active_run, get_active_run,
                            deregister_active_run

DEPRECATION: This shim will be removed in a future version.
New code must import directly from the canonical modules above.
"""
from __future__ import annotations

from app.core.run_journal import RunManager
from app.core.run_control import (
    register_active_run,
    get_active_run,
    deregister_active_run,
)

__all__ = [
    "RunManager",
    "register_active_run",
    "get_active_run",
    "deregister_active_run",
]
