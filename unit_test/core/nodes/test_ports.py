# unit_test/core/nodes/test_ports.py
"""Tests for app/core/nodes/ports.py — Req 18 (port descriptors and PortDataType)."""
from __future__ import annotations

import pytest

from app.core.nodes.ports import InputPort, OutputPort, PortDataType


class TestInputPort:
    """InputPort constructs correctly with required fields."""

    def test_constructs_with_name_and_data_type(self):
        port = InputPort(name="audio_in", data_type=float)
        assert port.name == "audio_in"
        assert port.data_type is float

    def test_defaults(self):
        port = InputPort(name="x", data_type=int)
        assert port.cardinality == "single"
        assert port.required is True
        assert port.description == ""

    def test_cardinality_multi(self):
        port = InputPort(name="inputs", data_type=list, cardinality="multi")
        assert port.cardinality == "multi"

    def test_optional_port(self):
        port = InputPort(name="opt", data_type=str, required=False)
        assert port.required is False

    def test_data_type_none_allowed(self):
        """Source nodes may have data_type=None."""
        port = InputPort(name="src", data_type=None)
        assert port.data_type is None

    def test_custom_description(self):
        port = InputPort(name="p", data_type=bytes, description="raw audio bytes")
        assert port.description == "raw audio bytes"


class TestOutputPort:
    """OutputPort constructs correctly with required fields."""

    def test_constructs_with_name_and_data_type(self):
        port = OutputPort(name="audio_out", data_type=float)
        assert port.name == "audio_out"
        assert port.data_type is float

    def test_defaults(self):
        port = OutputPort(name="y", data_type=int)
        assert port.description == ""

    def test_data_type_none_allowed(self):
        """Sink nodes may have data_type=None."""
        port = OutputPort(name="sink", data_type=None)
        assert port.data_type is None

    def test_custom_description(self):
        port = OutputPort(name="p", data_type=str, description="processed text")
        assert port.description == "processed text"


class TestPortDataType:
    """PortDataType is importable and subclassable."""

    def test_importable(self):
        assert PortDataType is not None

    def test_is_a_class(self):
        assert isinstance(PortDataType, type)

    def test_custom_subclass_is_recognized(self):
        class MyDataType(PortDataType):
            value: float = 0.0

        assert issubclass(MyDataType, PortDataType)

    def test_custom_subclass_instance_is_instance_of_port_data_type(self):
        class MyDataType(PortDataType):
            value: float = 0.0

        obj = MyDataType(value=3.14)
        assert isinstance(obj, PortDataType)
        assert obj.value == pytest.approx(3.14)

    def test_multiple_subclasses_are_independent(self):
        class TypeA(PortDataType):
            a: int = 0

        class TypeB(PortDataType):
            b: str = ""

        assert issubclass(TypeA, PortDataType)
        assert issubclass(TypeB, PortDataType)
        assert not issubclass(TypeA, TypeB)
        assert not issubclass(TypeB, TypeA)
