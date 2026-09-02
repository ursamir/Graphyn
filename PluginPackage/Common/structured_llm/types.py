"""Structured LLM extraction types.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class StructuredDocument(PortDataType):
    data: dict[str, Any] = Field(default_factory=dict)
    schema_name: str = ""
    provider: str = "mock"
    raw_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
