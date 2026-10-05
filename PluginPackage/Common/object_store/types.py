"""Object store result types.

Do NOT use `from __future__ import annotations`.
"""
from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ObjectRef(PortDataType):
    key: str = ""
    uri: str = ""
    backend: str = "local"
    size: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObjectList(PortDataType):
    keys: list = Field(default_factory=list)
    backend: str = "local"
    prefix: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
