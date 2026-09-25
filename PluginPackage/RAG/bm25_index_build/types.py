"""Port types for bm25_index_build (RAG).

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


class SparseIndexRef(PortDataType):
    path: str = ""
    backend: str = "bm25"
    metadata: dict[str, Any] = Field(default_factory=dict)
