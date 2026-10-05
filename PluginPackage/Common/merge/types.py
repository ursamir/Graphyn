"""Merged payload.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class MergedPayload(PortDataType):
    data: Any = None
    mode: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

