"""Port types for yolo_track (Vision).

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


class TrackResult(PortDataType):
    tracks: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
