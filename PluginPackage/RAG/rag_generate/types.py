"""Port types for rag_generate (RAG).

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


class RagAnswer(PortDataType):
    answer: str = ""
    citations: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
