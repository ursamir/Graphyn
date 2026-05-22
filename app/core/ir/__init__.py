"""Graph Intermediate Representation — public API.

This package defines the canonical, runtime-agnostic JSON graph representation
used by all platform interfaces (SDK, CLI, REST API, MCP).

Usage::

    from app.core.ir import GraphIR, IRNode, IREdge, IRMetadata
    from app.core.ir import load_ir, dump_ir, load_ir_from_file, dump_ir_to_file
    from app.core.ir import CURRENT_IR_VERSION, IRVersionError, IRValidationError
"""
from app.core.ir.models import (
    GraphIR,
    IRCapabilityMetadata,
    IREdge,
    IRMetadata,
    IRNode,
    IRParameter,
)
from app.core.ir.loader import (
    CURRENT_IR_VERSION,
    IRValidationError,
    IRVersionError,
    dump_ir,
    dump_ir_to_file,
    load_ir,
    load_ir_from_file,
)

__all__ = [
    # Models
    "GraphIR",
    "IRCapabilityMetadata",
    "IREdge",
    "IRMetadata",
    "IRNode",
    "IRParameter",
    # Loader
    "CURRENT_IR_VERSION",
    "IRValidationError",
    "IRVersionError",
    "dump_ir",
    "dump_ir_to_file",
    "load_ir",
    "load_ir_from_file",
]
