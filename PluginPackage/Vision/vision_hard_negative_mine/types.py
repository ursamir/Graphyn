"""Port types for vision_hard_negative_mine (Vision).

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


class VisionDatasetArtifact(PortDataType):
    root: str = ""
    task: str = "detect"
    names: list[str] = Field(default_factory=list)
    yaml_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
