"""Port types for agent_loop (Agents).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class AgentResult(PortDataType):
    final: str = ""
    steps: list = Field(default_factory=list)
    mode: str = "llm"
    metadata: dict[str, Any] = Field(default_factory=dict)
