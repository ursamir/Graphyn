"""Port types for feature_store_write (MLOps).

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


class FeatureStoreRef(PortDataType):
    path: str = ""
    feature_set: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
