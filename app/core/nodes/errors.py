# app/core/nodes/errors.py
"""
Bounded Context:  BC2 — Node Contract  (shared with BC3, BC4, BC5)
Responsibility:   Define the exception hierarchy for the node system. All node
                  and pipeline errors derive from NodeSystemError.
Owns:             NodeSystemError, NodeNotFoundError, DuplicateNodeTypeError,
                  NodeMetadataError, NodeTypeError, PortTypeNotFoundError,
                  DuplicatePortTypeError, PipelineGraphError, ResumeError.
Public Surface:   All exception classes above.
Must NOT:         Import from any other app module. Pure stdlib only.
Dependencies:     stdlib only.
Reason To Change: New error categories are needed in the node/pipeline system.
"""
from __future__ import annotations


class NodeSystemError(Exception):
    """Base class for all Enhanced Node System errors."""


class NodeNotFoundError(NodeSystemError):
    """Raised when a node_type is not found in the registry."""


class DuplicateNodeTypeError(NodeSystemError):
    """Raised when two classes resolve to the same node_type during AutoDiscovery."""


class NodeMetadataError(NodeSystemError):
    """Raised when a Node subclass is missing required metadata fields."""


class NodeTypeError(NodeSystemError):
    """Raised when an output port type is incompatible with an input port type."""


class PortTypeNotFoundError(NodeSystemError):
    """Raised when a type name cannot be resolved in TypeCatalogue."""


class DuplicatePortTypeError(NodeSystemError):
    """Raised when a PortDataType subclass is registered under a name already in use."""


class PipelineGraphError(NodeSystemError):
    """Raised for invalid pipeline graph structure (cycles, missing ports, etc.)."""


class ResumeError(RuntimeError):
    """Raised when a resume operation cannot be completed."""
