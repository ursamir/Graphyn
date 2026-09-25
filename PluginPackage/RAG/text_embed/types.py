"""Port types for text_embed (RAG).

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


class EmbeddingVector(PortDataType):
    embedding: Any = None
    source_path: str = ""
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
