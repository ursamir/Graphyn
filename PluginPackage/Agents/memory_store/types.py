"""Port types for memory_store (Agents).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class MemoryOp(PortDataType):
    op: str = "get"
    key: str = ""
    value: Any = None


class MemoryRecord(PortDataType):
    key: str = ""
    value: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
