# app/core/nodes/metadata.py
"""NodeMetadata — describes a node's identity, ports, and display properties."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class NodeMetadata(BaseModel):
    """Describes a node's identity, ports, and display properties.

    Serialisable to JSON for API responses. AutoDiscovery populates
    input_ports and output_ports from the node class if not set explicitly.

    Capability fields (Req 5.1.1) are optional with sensible defaults.
    Existing node implementations that do not declare capability fields
    will have defaults applied automatically (Req 5.5.1).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ── Identity fields ───────────────────────────────────────────────────────
    node_type: str
    label: str
    description: str
    category: str
    version: str = "1.0.0"
    tags: list[str] = []

    # Populated by AutoDiscovery from the node class's port declarations.
    # Stored as serialisable dicts (port name → port schema dict) rather
    # than InputPort/OutputPort objects so that NodeMetadata can be
    # round-tripped through JSON without losing type information.
    input_ports: dict[str, dict[str, Any]] = {}
    output_ports: dict[str, dict[str, Any]] = {}

    # ── Capability fields (Req 5.1.1) ─────────────────────────────────────────
    # All optional with sensible defaults. Machine-readable for Phase 2 (MCP).
    requires_gpu: bool = False
    """Whether the node requires a GPU to execute."""

    supports_cpu: bool = True
    """Whether the node can execute on CPU."""

    supports_edge: bool = False
    """Whether the node is suitable for edge deployment (Phase 6 hook)."""

    deterministic: bool = True
    """Whether the node produces identical outputs for identical inputs and seed."""

    cacheable: bool = True
    """Whether the node's outputs can be safely cached."""

    streaming_support: bool = False
    """Whether the node supports streaming execution via process_stream."""

    realtime_support: bool = False
    """Whether the node can process data in real-time."""

    # ── Extended capability fields (V1.md §5.2) ───────────────────────────────
    memory_requirements: str | None = None
    """Memory requirement hint (e.g. '512MB', '2GB'). None = unspecified."""

    dependency_requirements: list[str] = []
    """List of required packages or libraries (e.g. ['torch>=2.0', 'onnxruntime'])."""

    batch_support: bool = False
    """Whether the node supports batch processing of multiple inputs simultaneously."""

    @field_validator("node_type", "label", "description", "category")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be a non-empty string")
        return v

    @field_validator("version")
    @classmethod
    def _version_format(cls, v: str) -> str:
        """Validate that version is a semver-like string (e.g. '1.0.0', '2.1', '1.0.0-beta')."""
        import re
        if not re.match(r"^\d+(\.\d+)*([.\-+][a-zA-Z0-9._\-+]*)?$", v):
            raise ValueError(
                f"version must be a semver-like string (e.g. '1.0.0', '2.1'), got {v!r}"
            )
        return v
