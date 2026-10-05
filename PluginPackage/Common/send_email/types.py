"""Port types for send_email.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class EmailReceipt(PortDataType):
    ok: bool = False
    dry_run: bool = False
    to: list = Field(default_factory=list)
    from_addr: str = ""
    subject: str = ""
    message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
