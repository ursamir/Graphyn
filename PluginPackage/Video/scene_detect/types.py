"""Port types for scene_detect (Video).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class SceneBoundary(PortDataType):
    start_s: float = 0.0
    end_s: float = 0.0
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VideoSample(PortDataType):
    path: str = ""
    frames: list = Field(default_factory=list)
    fps: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
