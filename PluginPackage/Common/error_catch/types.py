"""Error payload.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ErrorPayload(PortDataType):
    ok: bool = True
    error_type: str = ""
    message: str = ""
    payload: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)

