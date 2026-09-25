"""Port types for feature_store_read (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class FeatureStoreRef(PortDataType):
    path: str = ""
    feature_set: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
