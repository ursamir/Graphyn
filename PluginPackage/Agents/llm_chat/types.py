"""Port types for llm_chat (Agents).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ChatMessage(PortDataType):
    role: str = "user"
    content: str = ""
    # F19: provenance — which provider produced this message (echo is not an LLM).
    metadata: dict[str, Any] = Field(default_factory=dict)
