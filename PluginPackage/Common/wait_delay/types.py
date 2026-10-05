"""Delay receipt.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class DelayReceipt(PortDataType):
    slept_s: float = 0.0
    requested_s: float = 0.0
    capped: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

