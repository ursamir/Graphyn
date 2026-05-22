# app/core/nodes/errors.py
"""Custom exception hierarchy for the Enhanced Node System."""
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
