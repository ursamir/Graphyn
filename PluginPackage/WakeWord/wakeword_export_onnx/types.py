"""Port types for the WakeWord pack (identical in every wakeword_* plugin).

Do NOT use `from __future__ import annotations` (PortDataType introspection).
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class WakeWordRun(PortDataType):
    """A wake-word model directory moving through generate → features → train → export.

    ``model_dir`` uses the livekit-wakeword layout and carries a
    ``wakeword_run.json`` manifest; ``stage`` is the last completed step.
    """

    model_name: str = ""
    model_dir: str = ""
    target_phrases: list[str] = Field(default_factory=list)
    stage: str = ""
    clip_counts: dict[str, int] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    checkpoint_path: str = ""
    onnx_path: str = ""
    onnx_int8_path: str = ""
    threshold: Optional[float] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
