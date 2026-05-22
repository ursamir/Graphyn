# app/core/run_manager.py
"""Backward-compatibility shim for the run_manager module.

All implementation has been extracted into focused modules:
  - app.core.run_journal  — RunManager class (persistence + control)
  - app.core.run_control  — register_active_run, get_active_run,
                            deregister_active_run, _ACTIVE_RUNS

All public names are re-exported here so existing imports continue to work.
"""
from __future__ import annotations

from app.core.run_journal import RunManager, _WORKSPACE
from app.core.run_control import (
    _ACTIVE_RUNS,
    _ACTIVE_RUNS_LOCK,
    register_active_run,
    get_active_run,
    deregister_active_run,
)

__all__ = [
    "RunManager",
    "_WORKSPACE",
    "_ACTIVE_RUNS",
    "_ACTIVE_RUNS_LOCK",
    "register_active_run",
    "get_active_run",
    "deregister_active_run",
]
