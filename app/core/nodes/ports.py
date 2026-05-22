# app/core/nodes/ports.py
"""Port descriptors and PortDataType base class for the Enhanced Node System."""
from __future__ import annotations

from typing import Any, Literal, get_origin

from pydantic import BaseModel, ConfigDict, field_validator


class PortDataType(BaseModel):
    """Base class for all port data types.

    Subclass this to define custom domain types (e.g. AudioSample, TFLiteModel).
    AutoDiscovery registers every subclass in TypeCatalogue automatically.

    Example::

        class TFLiteModel(PortDataType):
            path: str
            metadata: dict[str, Any] = {}
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)


class InputPort(BaseModel):
    """Descriptor for a node's input port.

    Attributes:
        name: Port name — must match the key in ``Node.input_ports``.
        data_type: The Python type this port accepts, or ``None`` for source nodes.
        cardinality: ``"single"`` (one upstream connection) or ``"multi"``
            (N upstream connections; port receives a ``list`` of values).
        required: If ``False`` the port does not need to be connected; the
            pipeline runtime passes ``None`` for unconnected optional ports.
        description: Human-readable description for UI rendering.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    data_type: Any  # type | None — stored as Python type object at runtime
    cardinality: Literal["single", "multi"] = "single"
    required: bool = True
    description: str = ""

    @field_validator("data_type", mode="before")
    @classmethod
    def _must_be_type_or_none(cls, v: Any) -> Any:
        """Reject non-type values early so errors surface at port declaration time."""
        if v is not None and not isinstance(v, type) and get_origin(v) is None:
            raise ValueError(
                f"data_type must be a Python type or generic alias (e.g. list[str]), got {v!r}"
            )
        return v


class OutputPort(BaseModel):
    """Descriptor for a node's output port.

    Attributes:
        name: Port name — must match the key in ``Node.output_ports``.
        data_type: The Python type this port produces, or ``None`` for sink nodes.
        description: Human-readable description for UI rendering.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    data_type: Any  # type | None
    description: str = ""

    @field_validator("data_type", mode="before")
    @classmethod
    def _must_be_type_or_none(cls, v: Any) -> Any:
        """Reject non-type values early so errors surface at port declaration time."""
        if v is not None and not isinstance(v, type) and get_origin(v) is None:
            raise ValueError(
                f"data_type must be a Python type or generic alias (e.g. list[str]), got {v!r}"
            )
        return v
