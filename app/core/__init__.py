# app/core/__init__.py
"""Graphyn core package.

Exports ``ResumeError`` lazily to avoid pulling in the full pipeline module
(and its transitive imports of nodes, registry, IR, etc.) at package import
time (S-09 fix).
"""
from __future__ import annotations


def __getattr__(name: str):
    if name == "ResumeError":
        from app.core.nodes.errors import ResumeError  # noqa: PLC0415
        return ResumeError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ResumeError"]
