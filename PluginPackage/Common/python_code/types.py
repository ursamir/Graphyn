"""Code result type.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class CodeResult(PortDataType):
    data: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
