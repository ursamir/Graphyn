"""Port types for prompt_assemble (RAG).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class AssembledPrompt(PortDataType):
    system: str = ""
    user: str = ""
    messages: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalHit(PortDataType):
    chunk_id: str = ""
    text: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
