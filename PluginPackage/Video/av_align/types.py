"""Port types for av_align (Video pack). No `from __future__ import annotations`."""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class AvAlignedSample(PortDataType):
    """A video segment paired with its (aligned) audio."""

    video_path: str = ""
    audio_path: str = ""
    start_s: float = 0.0
    end_s: Optional[float] = None
    method: str = ""
    offset_ms: float = 0.0
    confidence: float = 0.0
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
