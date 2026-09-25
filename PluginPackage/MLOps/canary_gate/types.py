"""Port types for canary_gate (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class CanaryDecision(PortDataType):
    promote: bool = False
    reason: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
