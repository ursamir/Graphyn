"""Port types for video_exporter (Video).

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


class VideoSample(PortDataType):
    path: str = ""
    frames: list = Field(default_factory=list)
    fps: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
