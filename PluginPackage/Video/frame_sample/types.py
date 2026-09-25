"""Port types for frame_sample (Video).

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


class VideoSample(PortDataType):
    path: str = ""
    frames: list = Field(default_factory=list)
    fps: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
