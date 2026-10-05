"""Schedule tick payload.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class TickEvent(PortDataType):
    tick: bool = True
    cron: str = ""
    interval_s: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

