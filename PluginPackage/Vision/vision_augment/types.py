"""Port types for vision_augment (Vision).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ImageSample(PortDataType):
    path: str = ""
    image: Any = None
    label: Optional[str] = None
    boxes: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
