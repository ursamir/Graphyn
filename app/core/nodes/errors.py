# app/core/nodes/errors.py
"""
Bounded Context:  BC2 — Node Contract  (shared with BC3, BC4, BC5)
Responsibility:   Define the exception hierarchy for the node system. All node
                  and pipeline errors derive from NodeSystemError.
Owns:             NodeSystemError, NodeNotFoundError, DuplicateNodeTypeError,
                  NodeMetadataError, NodeTypeError, PortTypeNotFoundError,
                  DuplicatePortTypeError, PipelineGraphError.
Public Surface:   All exception classes above.
Must NOT:         Import from any other app module. Pure stdlib only.
          Must NOT own ResumeError — that is a run-persistence error
          belonging to app.core.errors (BC6 / Platform Infrastructure).
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


# ---------------------------------------------------------------------------
# Backward-compatibility re-export
# ---------------------------------------------------------------------------
# ResumeError has been moved to app.core.errors (platform-level errors module).
# This alias is kept so existing imports of
#   from app.core.nodes.errors import ResumeError
# continue to work without modification.
# New code should import from app.core.errors directly.
from app.core.errors import ResumeError  # noqa: E402, F401
