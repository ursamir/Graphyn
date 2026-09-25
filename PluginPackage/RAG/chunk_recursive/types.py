"""Port types for chunk_recursive (RAG).

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


class RawDocument(PortDataType):
    path: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
