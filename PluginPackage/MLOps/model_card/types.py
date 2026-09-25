"""Port types for model_card (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ModelCardArtifact(PortDataType):
    path: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
