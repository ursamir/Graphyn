"""Port types for tool_router (Agents).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ToolCallRequest(PortDataType):
    tool: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(PortDataType):
    tool: str = ""
    ok: bool = False
    result: Any = None
    error: Optional[str] = None
