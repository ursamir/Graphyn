"""Port types for tflm_op_support_check (TinyML).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class TflmSupportReport(PortDataType):
    supported: bool = True
    unsupported_ops: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
