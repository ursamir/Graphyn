"""Inbound webhook payload.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class WebhookEvent(PortDataType):
    body: Any = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
