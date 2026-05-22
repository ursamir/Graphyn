# unit_test/core/nodes/test_catalogue.py
"""Tests for app/core/nodes/catalogue.py — Req 3 criteria 6–7."""
from __future__ import annotations

import pytest

from app.core.nodes.catalogue import TypeCatalogue, _fqn
from app.core.nodes.errors import DuplicatePortTypeError, PortTypeNotFoundError
from app.core.nodes.ports import PortDataType


# ── Test PortDataType subclasses ──────────────────────────────────────────────

class _TestPortType(PortDataType):
    value: int = 0


class _AnotherPortType(PortDataType):
    name: str = ""


class TestTypeCatalogueRegisterAndResolve:
    """Req 3.6 — register(cls) then resolve(fqn) returns same class."""

    def test_register_then_resolve_returns_same_class(self):
        """Req 3.6: register(cls) then resolve(fqn(cls)) returns the same class."""
        catalogue = TypeCatalogue()
        catalogue.register(_TestPortType)
        fqn = _fqn(_TestPortType)
        assert catalogue.resolve(fqn) is _TestPortType

    def test_register_multiple_types(self):
        catalogue = TypeCatalogue()
        catalogue.register(_TestPortType)
        catalogue.register(_AnotherPortType)
        assert catalogue.resolve(_fqn(_TestPortType)) is _TestPortType
        assert catalogue.resolve(_fqn(_AnotherPortType)) is _AnotherPortType

    def test_contains_after_register(self):
        catalogue = TypeCatalogue()
        catalogue.register(_TestPortType)
        assert _fqn(_TestPortType) in catalogue

    def test_list_types_returns_sorted(self):
        catalogue = TypeCatalogue()
        catalogue.register(_TestPortType)
        catalogue.register(_AnotherPortType)
        types = catalogue.list_types()
        assert types == sorted(types)

    def test_resolve_unregistered_raises_port_type_not_found(self):
        catalogue = TypeCatalogue()
        with pytest.raises(PortTypeNotFoundError):
            catalogue.resolve("nonexistent.module.Type")


class TestTypeCatalogueDuplicateRaises:
    """Req 3.7 — register(cls) twice raises DuplicatePortTypeError."""

    def test_register_same_class_twice_raises(self):
        """Req 3.7: register(cls) twice raises DuplicatePortTypeError on second call."""
        catalogue = TypeCatalogue()
        catalogue.register(_TestPortType)
        with pytest.raises(DuplicatePortTypeError):
            catalogue.register(_TestPortType)

    def test_register_non_port_data_type_raises_type_error(self):
        """Registering a non-PortDataType subclass raises TypeError."""
        catalogue = TypeCatalogue()
        with pytest.raises(TypeError):
            catalogue.register(int)  # type: ignore[arg-type]
