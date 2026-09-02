"""PII redaction types.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class PiiFinding(PortDataType):
    entity_type: str = ""
    start: int = 0
    end: int = 0
    score: float = 1.0
    text: str = ""


class RedactionAudit(PortDataType):
    findings: list = Field(default_factory=list)
    engine: str = "regex"
    n_redacted: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
