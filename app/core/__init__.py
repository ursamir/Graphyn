# app/core/__init__.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   Lazy re-export of ResumeError to avoid pulling in the full
                  pipeline module and its transitive imports at package import
                  time (S-09 fix).
Owns:             __getattr__ hook for lazy ResumeError resolution.
Public Surface:   ResumeError (lazy)
Must NOT:         Import any heavy module at module level. Must remain a
                  near-zero-cost import.
Dependencies:     app.core.nodes.errors (lazy, via __getattr__).
Reason To Change: New lazy re-export is needed at the core package level.
"""
from __future__ import annotations


def __getattr__(name: str):
    if name == "ResumeError":
        from app.core.nodes.errors import ResumeError  # noqa: PLC0415
        return ResumeError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ResumeError"]
