"""Port types for micro_speech_pipeline (TinyML).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class McuSample(PortDataType):
    sample_id: str = ""
    payload: Any = None
    modality: str = "audio"
    label: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
