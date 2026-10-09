"""Port types for video_caption (Video pack). No `from __future__ import annotations`."""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class CaptionRecord(PortDataType):
    """A caption for one frame of a video."""

    text: str = ""
    source_path: str = ""
    image_path: str = ""
    timestamp_s: float = 0.0
    model: str = ""
    provider: str = ""
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
