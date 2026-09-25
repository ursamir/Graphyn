"""Port types for ab_assign (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class AbAssignment(PortDataType):
    variant: str = "control"
    unit_id: str = ""
