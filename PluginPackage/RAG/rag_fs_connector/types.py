"""Port types for rag_fs_connector (RAG).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class RawDocument(PortDataType):
    path: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
