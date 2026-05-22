# app/core/nodes/config.py
"""NodeConfig base class for the Enhanced Node System."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NodeConfig(BaseModel):
    """Base class for all node configuration models.

    Each ``Node`` subclass declares an inner ``Config(NodeConfig)`` class that
    defines the typed, validated configuration for that node.

    Features:
    - ``extra="forbid"`` — unknown fields raise ``ValidationError`` immediately.
    - Supports lossless JSON round-trip via ``model_dump(mode="json")`` and
      ``model_validate_json(json_str)``.
    - Optional fields declare a default value at the class level; fields without
      a default are required and raise ``ValidationError`` when omitted.

    Example::

        class CleanConfig(NodeConfig):
            sample_rate: int = 16000

        class CleanNode(Node):
            class Config(CleanConfig):
                pass
    """

    model_config = ConfigDict(
        extra="forbid",           # unknown fields raise ValidationError
        frozen=False,             # configs are mutable after construction
        populate_by_name=True,    # allow field population by name
    )
