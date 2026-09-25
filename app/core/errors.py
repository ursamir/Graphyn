# app/core/errors.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   Platform-level exception hierarchy. Errors that cross bounded
                  context boundaries and cannot belong to a single BC.
Owns:             ResumeError, VersionConflict.
Public Surface:   ResumeError, VersionConflict.
Must NOT:         Import from app.domain, app.api, or any specific BC module.
                  Pure stdlib only.
Dependencies:     stdlib only.
Reason To Change: New cross-cutting platform error categories are needed.

## Why this file exists

ResumeError was previously defined in app.core.nodes.errors (BC2 — Node
Contract), but it is raised by app.core.run_journal (BC6 — Observability &
Storage) and caught by app.core.orchestrator (BC5 — Execution Runtime).
It has nothing to do with the node contract. Moving it here removes the
incorrect BC2 ownership and eliminates the implicit cross-context dependency.

Backward-compatible re-export remains in app.core.nodes.errors so existing
imports continue to work without modification.
"""
from __future__ import annotations


class ResumeError(RuntimeError):
    """Raised when a pipeline resume operation cannot be completed.

    Typical causes:
    - The prior run directory does not exist.
    - resume_state.json is missing or corrupt.
    - The graph has changed since the checkpoint was written (hash mismatch).
    """


class VersionConflict(ValueError):
    """Optimistic concurrency mismatch (API-CONV-005).

    ``via_if_match`` True → HTTP 412 precondition_failed;
    False → HTTP 409 version_conflict.
    """

    def __init__(self, *, via_if_match: bool = False, current: str | None = None):
        self.via_if_match = via_if_match
        self.current = current
        super().__init__("version_conflict")
