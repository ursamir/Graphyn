"""Port types for drift_detect (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class DriftReport(PortDataType):
    drifted: bool = False
    scores: dict[str, Any] = Field(default_factory=dict)
