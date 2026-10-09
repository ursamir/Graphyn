"""Port types for frame_sample (Video pack). No `from __future__ import annotations`."""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ImageSample(PortDataType):
    """One extracted video frame written as a JPEG."""

    path: str = ""
    source_path: str = ""
    timestamp_s: float = 0.0
    index: int = 0
    width: int = 0
    height: int = 0
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
