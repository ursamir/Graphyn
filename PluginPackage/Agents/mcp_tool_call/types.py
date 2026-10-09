"""Port types for mcp_tool_call (Agents).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ToolCallResult(PortDataType):
    tool: str = ""
    ok: bool = False
    result: Any = None
    error: Optional[str] = None
