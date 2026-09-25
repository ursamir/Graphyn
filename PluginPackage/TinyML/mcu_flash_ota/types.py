"""Port types for mcu_flash_ota (TinyML).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class FlashReceipt(PortDataType):
    status: str = "needs-api"
    device_id: str = ""
    message: str = "MCU flash/OTA requires Devices API — not faked."
    metadata: dict[str, Any] = Field(default_factory=dict)
