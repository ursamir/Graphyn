"""Port types for artifact_checksum (MLOps).

Do NOT use `from __future__ import annotations`.
"""
from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ChecksumRecord(PortDataType):
    algo: str = "sha256"
    digest: str = ""
    path: str = ""
