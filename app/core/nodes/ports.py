# app/core/nodes/ports.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Define port descriptors and the PortDataType base class.
                  Ports are the typed connection points between nodes.
Owns:             InputPort, OutputPort, PortDataType.
Public Surface:   InputPort, OutputPort, PortDataType.
Must NOT:         Import from app.domain, app.api, or any BC3/BC4/BC5/BC6 module.
Dependencies:     pydantic, stdlib (typing).
Reason To Change: Port descriptor fields change (new cardinality options,
                  new validation rules), or PortDataType base class evolves.
"""
from __future__ import annotations

import types as _types
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# Origins that are not valid port data types even though get_origin() is not None.
_REJECTED_ORIGINS = {Annotated, Literal}


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
        if v is not None:
            origin = get_origin(v)
            if origin in _REJECTED_ORIGINS:
                raise ValueError(
                    f"data_type must not use Annotated or Literal, got {v!r}"
                )
            if not isinstance(v, type) and origin is None:
                raise ValueError(
                    f"data_type must be a Python type or generic alias (e.g. list[str]), got {v!r}"
                )
        return v

    @model_validator(mode="after")
    def _optional_port_must_accept_none(self) -> "InputPort":
        """Warn early when required=False but data_type cannot receive None.

        A required=False port will receive None at runtime when unconnected.
        If data_type is not Optional/None-accepting the node's process() will
        crash with a confusing AttributeError deep in its logic.
        """
        if not self.required and self.data_type is not None:
            origin = get_origin(self.data_type)
            # typing.Optional[X] / typing.Union[X, None]
            if origin is Union:
                if type(None) not in get_args(self.data_type):
                    raise ValueError(
                        f"InputPort '{self.name}': required=False but data_type "
                        f"{self.data_type!r} does not accept None. "
                        "Use Optional[...] or include None in the Union."
                    )
            # Python 3.10+ X | None  (types.UnionType)
            elif isinstance(self.data_type, _types.UnionType):
                if type(None) not in get_args(self.data_type):
                    raise ValueError(
                        f"InputPort '{self.name}': required=False but data_type "
                        f"{self.data_type!r} does not accept None. "
                        "Use X | None to allow optional values."
                    )
            else:
                # Plain type or generic alias — neither accepts None
                raise ValueError(
                    f"InputPort '{self.name}': required=False but data_type "
                    f"{self.data_type!r} does not accept None. "
                    "Use Optional[...] or X | None."
                )
        return self


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
        if v is not None:
            origin = get_origin(v)
            if origin in _REJECTED_ORIGINS:
                raise ValueError(
                    f"data_type must not use Annotated or Literal, got {v!r}"
                )
            if not isinstance(v, type) and origin is None:
                raise ValueError(
                    f"data_type must be a Python type or generic alias (e.g. list[str]), got {v!r}"
                )
        return v
