"""Port types for yolo_train (Vision).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class VisionDatasetArtifact(PortDataType):
    root: str = ""
    task: str = "detect"
    names: list[str] = Field(default_factory=list)
    yaml_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
