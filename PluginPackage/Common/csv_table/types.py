"""CSV table result.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class CsvTableResult(PortDataType):
    path: str = ""
    operation: str = ""
    rows: list = Field(default_factory=list)
    row_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

