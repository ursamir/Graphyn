"""CredentialProbeResult — redacted resolve receipt."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CredentialProbeResult(BaseModel):
    ok: bool = True
    kind: str = ""
    source: str = ""
    connection_id: str | None = None
    field_names: list[str] = Field(default_factory=list)
    redacted: dict[str, Any] = Field(default_factory=dict)
