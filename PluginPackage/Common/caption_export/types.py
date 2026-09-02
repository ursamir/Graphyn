"""Caption export result type.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class CaptionExportResult(PortDataType):
    paths: list = Field(default_factory=list)
    format: str = "srt"
    n_cues: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
