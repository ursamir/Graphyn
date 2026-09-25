"""Port types for ship_package_promote (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ShipPackageRef(PortDataType):
    package_id: str = ""
    path: str = ""
    state: str = "created"
    metadata: dict[str, Any] = Field(default_factory=dict)
