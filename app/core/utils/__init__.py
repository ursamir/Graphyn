# app/core/utils/__init__.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   Shared utility helpers used across bounded contexts.
Owns:             stable_hash(), collect_stream().
Public Surface:   stable_hash(*args) -> int
                  collect_stream(executor, inputs) -> dict
Must NOT:         Import from app.domain, app.api, or any specific BC module.
                  Must remain dependency-free (only stdlib + BC2 node interface).
Dependencies:     app.core.utils.hash (stable_hash), stdlib (typing, asyncio).
Reason To Change: New cross-cutting utilities are needed, or the stream
                  collection protocol changes.
"""
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
