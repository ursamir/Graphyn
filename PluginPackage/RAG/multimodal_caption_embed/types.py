"""Port types for multimodal_caption_embed (RAG).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class EmbeddingVector(PortDataType):
    embedding: Any = None
    source_path: str = ""
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageSample(PortDataType):
    path: str = ""
    image: Any = None
    label: Optional[str] = None
    boxes: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawDocument(PortDataType):
    path: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
