"""Port types for mcu_ondevice_metrics (TinyML).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class OnDeviceMetrics(PortDataType):
    status: str = "needs-api"
    metrics: dict[str, Any] = Field(default_factory=dict)
    message: str = "On-device metrics require Devices API — not faked."
    metadata: dict[str, Any] = Field(default_factory=dict)
