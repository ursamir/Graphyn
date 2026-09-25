"""Port types for dataset_diff (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class DatasetDiffReport(PortDataType):
    added: int = 0
    removed: int = 0
    changed: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
