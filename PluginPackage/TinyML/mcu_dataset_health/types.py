"""Port types for mcu_dataset_health (TinyML).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class DatasetHealthReport(PortDataType):
    ok: bool = True
    issues: list = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class McuSample(PortDataType):
    sample_id: str = ""
    payload: Any = None
    modality: str = "audio"
    label: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
