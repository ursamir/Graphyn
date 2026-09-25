"""Port types for yolo_hyperparam_search (Vision).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ExperimentArtifact(PortDataType):
    status: str = "stub"
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload: Any = None
