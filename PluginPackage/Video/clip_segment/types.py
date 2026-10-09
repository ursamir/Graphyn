"""Port types for clip_segment (Video pack). No `from __future__ import annotations`."""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class VideoSample(PortDataType):
    """One video (or a segment of one): file path + ffprobe facts.

    ``start_s`` / ``end_s`` give the segment inside ``path`` (0 / None = whole
    file). ``duration_s`` is the segment length.
    """

    path: str = ""
    label: str = ""
    start_s: float = 0.0
    end_s: Optional[float] = None
    duration_s: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    n_frames: int = 0
    has_audio: bool = False
    codec: str = ""
    size_bytes: int = 0
    source_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
