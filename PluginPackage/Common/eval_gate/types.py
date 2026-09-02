"""Eval gate report type.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class EvalReport(PortDataType):
    passed: bool = True
    checks: list = Field(default_factory=list)
    failures: list = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
