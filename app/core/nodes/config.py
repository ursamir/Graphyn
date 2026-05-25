# app/core/nodes/config.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Base configuration model for all node Config classes.
                  Provides strict validation (extra="forbid"), mutability,
                  and JSON round-trip support.
Owns:             NodeConfig Pydantic base class.
Public Surface:   NodeConfig — subclass as ``class Config(NodeConfig)`` inside
                  each Node subclass.
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not contain node-specific fields.
Dependencies:     pydantic.
Reason To Change: Global config model settings change (e.g. extra policy,
                  serialization mode), or new base validators are added.
"""
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
