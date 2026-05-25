# app/core/ir/__init__.py
"""
Bounded Context:  BC1 — Graph Language
Responsibility:   Public API surface for the Graph IR package. Re-exports all
                  types, loaders, and constants so callers use a single import
                  path rather than deep sub-module imports.
Owns:             Re-export declarations for GraphIR, IRNode, IREdge,
                  IRMetadata, IRCapabilityMetadata, IRParameter, load_ir,
                  dump_ir, load_ir_from_file, dump_ir_to_file,
                  CURRENT_IR_VERSION, IRValidationError, IRVersionError.
Public Surface:   All names listed in __all__.
Must NOT:         Contain IR parsing or validation logic — delegate to
                  ir/models.py and ir/loader.py.
Dependencies:     app.core.ir.models, app.core.ir.loader.
Reason To Change: New IR type or loader function is added to the public API.
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
