"""
Bounded Context:  BC1 — Graph Language
Responsibility:   Define the canonical, versioned, immutable data model for
                  pipeline graphs. The single source of truth for graph structure.
Owns:             GraphIR, IRNode, IREdge, IRMetadata, IRParameter,
                  IRCapabilityMetadata — all frozen Pydantic models.
Public Surface:   All model classes above.
Must NOT:         Import from app.core.nodes, app.core.orchestrator,
                  app.core.sdk, app.domain, or app.api.
                  Must remain pure — only pydantic and stdlib.
Dependencies:     pydantic, stdlib (re, copy, types).
Reason To Change: Graph schema evolves (new fields on IRNode/IREdge/GraphIR),
                  or validation rules change.
"""
from __future__ import annotations

import copy
import re
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# Regex for valid node IDs: alphanumeric, underscores, hyphens only (Req 1.4.4)
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _deep_freeze(v: Any) -> Any:
    """Recursively wrap dicts in MappingProxyType and lists in tuple.

    Ensures that nested structures inside an IRNode config are fully
    immutable, not just the top-level mapping (P-23 fix extension).
    """
    if isinstance(v, dict):
        return MappingProxyType({k: _deep_freeze(vv) for k, vv in v.items()})
    if isinstance(v, list):
        return tuple(_deep_freeze(i) for i in v)
    return v


class IRCapabilityMetadata(BaseModel):
    """Capability hints for a node instance within a specific graph.

    When set on an IRNode, these values take precedence over the node class's
    NodeMetadata capability fields for that specific instance (Req 5.2.4).

    All fields are optional with sensible defaults (Req 5.1.1).
    """

    model_config = ConfigDict(frozen=True)

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

    memory_requirements: str | None = None
    """Memory requirement hint for this node instance. None = use NodeMetadata default."""

    dependency_requirements: tuple[str, ...] = ()
    """Required packages/libraries for this node instance."""

    batch_support: bool = False
    """Whether this node instance supports batch processing."""


class IRMetadata(BaseModel):
    """Graph-level metadata: name, seed, description, timestamps, tags.

    Req 1.3
    """

    model_config = ConfigDict(frozen=True)

    name: str
    seed: int
    description: str = ""
    created_at: str | None = None
    tags: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("IRMetadata.name must be a non-empty string")
        return v.strip()  # P-24 fix: strip and store the normalised value


class IRNode(BaseModel):
    """Specification for a single node in the graph.

    Note on mutability: ``GraphIR`` and ``IRNode`` use ``frozen=True`` for
    immutability at the Pydantic level, but ``config: dict[str, Any]`` is a
    plain Python dict and can be mutated in place. Callers that need a truly
    immutable config should use ``dict(node.config)`` to take a shallow copy.

    Req 1.4
    """

    model_config = ConfigDict(frozen=True)

    id: str
    node_type: str
    config: Any = {}
    label: str | None = None
    capability_metadata: IRCapabilityMetadata | None = None
    event_trigger: dict[str, Any] | None = None
    """Optional event trigger binding for event-driven execution (Phase 3).

    When set, contains ``source_type`` (str) and ``source_config`` (dict) fields
    that bind this node to an EventSource. Defaults to ``None`` for full backward
    compatibility — all existing IRNode instances without this field behave
    identically to the Phase 1/2 implementation.
    """

    @field_validator("config", mode="before")
    @classmethod
    def _deep_copy_config(cls, v: Any) -> Any:
        """Deep-copy and recursively freeze config on construction (P-23 fix).

        Rejects non-dict config values at construction time so callers get a
        clear ValidationError rather than an AttributeError deep in execution.
        Uses _deep_freeze to make nested dicts and lists fully immutable, not
        just the top-level mapping.
        """
        if v is None:
            return MappingProxyType({})
        if not isinstance(v, dict):
            raise ValueError(
                f"IRNode.config must be a dict, got {type(v).__name__}"
            )
        return _deep_freeze(copy.deepcopy(v))

    @field_validator("id")
    @classmethod
    def _id_valid(cls, v: str) -> str:
        if not _NODE_ID_RE.match(v):
            raise ValueError(
                f"IRNode.id '{v}' contains invalid characters. "
                "Only alphanumeric characters, underscores, and hyphens are allowed."
            )
        return v

    @field_validator("node_type")
    @classmethod
    def _node_type_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("IRNode.node_type must be a non-empty string")
        return v


class IREdge(BaseModel):
    """A directed edge connecting one node's output port to another's input port.

    Req 1.5
    """

    model_config = ConfigDict(frozen=True)

    src_id: str
    src_port: str
    dst_id: str
    dst_port: str
    condition: str | None = None
    """Optional boolean condition expression (Phase 3).

    When non-null, the edge transmits data only when this expression evaluates
    to ``True`` against the source node's output dict. Defaults to ``None`` for
    full backward compatibility — all existing ``IREdge`` instances without a
    ``condition`` field behave identically to the Phase 1/2 implementation.

    Optional boolean condition expression. Edge transmits data only when this evaluates to true.
    """

    @field_validator("src_port", "dst_port")
    @classmethod
    def _port_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("IREdge port name must be a non-empty string")
        return v


class IRParameter(BaseModel):
    """A graph-level parameter definition.

    Req 1.6
    """

    model_config = ConfigDict(frozen=True)

    type: str
    default: Any
    description: str = ""


class GraphIR(BaseModel):
    """Top-level graph IR model — the canonical representation of a pipeline.

    Req 1.2, 1.4.3, 1.9
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str
    metadata: IRMetadata
    nodes: list[IRNode]
    edges: list[IREdge] = []
    parameters: dict[str, IRParameter] = {}

    @field_validator("schema_version")
    @classmethod
    def _version_format(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("GraphIR.schema_version must be a non-empty string")
        parts = v.split(".")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError(
                f"GraphIR.schema_version '{v}' must follow the format '<major>.<minor>' "
                "(e.g. '1.0')"
            )
        return v

    @model_validator(mode="after")
    def _validate_graph(self) -> "GraphIR":
        """Validate node ID uniqueness and edge reference integrity.

        Req 1.4.3: no two nodes may share the same id.
        Req 1.9.1: all edge src_id and dst_id must reference known node ids.
        Req 1.9.2: no duplicate node ids.
        """
        # Build id set and check for duplicates
        seen_ids: set[str] = set()
        for node in self.nodes:
            if node.id in seen_ids:
                raise ValueError(
                    f"Duplicate node id '{node.id}' in GraphIR.nodes. "
                    "All node ids must be unique within a graph."
                )
            seen_ids.add(node.id)

        # Validate edge references
        for edge in self.edges:
            if edge.src_id not in seen_ids:
                raise ValueError(
                    f"IREdge references unknown source node id '{edge.src_id}'. "
                    f"Known node ids: {sorted(seen_ids)}"
                )
            if edge.dst_id not in seen_ids:
                raise ValueError(
                    f"IREdge references unknown destination node id '{edge.dst_id}'. "
                    f"Known node ids: {sorted(seen_ids)}"
                )
            if edge.src_id == edge.dst_id:
                raise ValueError(
                    f"Self-loop detected on node '{edge.src_id}'. "
                    "A node may not have an edge to itself."
                )

        return self
