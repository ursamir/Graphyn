# app/core/utils/__init__.py
"""Utility helpers for the Graphyn platform."""
from __future__ import annotations

from typing import Any

from app.core.utils.hash import stable_hash


async def collect_stream(
    executor: Any,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Collect all items from a streaming node into lists.

    SA-O5 fix: extracted from orchestrator.py (_collect_stream) and
    executor.py (_collect_stream_parallel) — previously two identical
    implementations existed with no shared abstraction. Both modules now
    import this single implementation so any bug fix applies everywhere.
    """
    collected: dict[str, list] = {}
    async for item in executor.execute_stream(inputs):
        for k, v in item.items():
            collected.setdefault(k, []).append(v)
    return collected


__all__ = ["stable_hash", "collect_stream"]
