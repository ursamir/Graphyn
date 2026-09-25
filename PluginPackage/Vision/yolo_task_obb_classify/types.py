"""Port types for yolo_task_obb_classify (Vision).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class DetectionResult(PortDataType):
    boxes: list = Field(default_factory=list)
    scores: list = Field(default_factory=list)
    labels: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageSample(PortDataType):
    path: str = ""
    image: Any = None
    label: Optional[str] = None
    boxes: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
