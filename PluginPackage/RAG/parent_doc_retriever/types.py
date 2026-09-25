"""Port types for parent_doc_retriever (RAG).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class RetrievalHit(PortDataType):
    chunk_id: str = ""
    text: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorStoreRef(PortDataType):
    backend: str = ""
    path: str = ""
    collection: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
