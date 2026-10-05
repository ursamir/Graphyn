"""Port types for guardrail_filter (Agents).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class GuardrailHit(PortDataType):
    rule: str = ""
    severity: str = ""
    score: float = 0.0
