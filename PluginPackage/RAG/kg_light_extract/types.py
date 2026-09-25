"""Port types for kg_light_extract (RAG).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class Chunk(PortDataType):
    text: str = ""
    source: str = ""
    page: Optional[int] = None
    chunk_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphFragment(PortDataType):
    entities: list = Field(default_factory=list)
    relations: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagAnswer(PortDataType):
    answer: str = ""
    citations: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
