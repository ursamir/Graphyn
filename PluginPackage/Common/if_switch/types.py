"""Branch result type.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class BranchResult(PortDataType):
    matched: bool = False
    branch: str = ""
    payload: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
