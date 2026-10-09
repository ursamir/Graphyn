"""Port types for scene_detect (Video pack). No `from __future__ import annotations`."""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class SceneBoundary(PortDataType):
    """One detected scene [start_s, end_s) of ``video_path``."""

    video_path: str = ""
    index: int = 0
    start_s: float = 0.0
    end_s: float = 0.0
    score: float = 0.0
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
