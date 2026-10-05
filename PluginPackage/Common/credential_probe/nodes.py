"""CredentialProbeNode — resolve a platform credential connection (redacted)."""
from __future__ import annotations

import importlib
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("credential_probe.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CredentialProbeResult = _types.CredentialProbeResult


class CredentialProbeNode(Node):
    """Resolve an existing credential connection and return redacted metadata."""

    node_type: ClassVar[str] = "credential_probe"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="credential_probe",
        label="Credential Probe",
        description="Resolve a Graphyn credential connection by id/kind (redacted; for smoke tests).",
        category="Utility",
        version="0.1.0",
        tags=["credentials", "smoke"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="Unused"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="CredentialProbeResult"),
    }

    class Config(NodeConfig):
        kind: Literal["openai_compat", "ollama", "smtp"] = Field(
            default="openai_compat", title="Kind", description="Credential kind."
        )
        connection_id: str = Field(default="", title="Credential connection id")

    def process(self, inputs=None, **kwargs):
        kind = (getattr(self.config, "kind", None) or "openai_compat").strip().lower()
        cid = (getattr(self.config, "connection_id", "") or "").strip() or None
        from app.core.credentials.kinds import redact_payload
        from app.core.credentials.resolve import resolve_connection

        resolved = resolve_connection(kind=kind, connection_id=cid, required=True)
        payload = resolved.get("payload") or {}
        redacted = redact_payload(kind, payload if isinstance(payload, dict) else {})
        return {
            "output": CredentialProbeResult(
                ok=True,
                kind=kind,
                source=str(resolved.get("source") or ""),
                connection_id=resolved.get("connection_id"),
                field_names=sorted(redacted.keys()),
                redacted=redacted,
            )
        }
