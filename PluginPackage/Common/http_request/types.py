"""HTTP response type.

Do NOT use `from __future__ import annotations` — breaks Pydantic v2 rebuild.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class HttpResponse(PortDataType):
    url: str = ""
    method: str = "GET"
    status_code: int = 0
    ok: bool = False
    headers: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
