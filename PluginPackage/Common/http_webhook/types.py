"""Webhook receipt type.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class WebhookReceipt(PortDataType):
    url: str = ""
    status_code: int = 0
    ok: bool = False
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
