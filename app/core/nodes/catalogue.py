# app/core/nodes/catalogue.py
"""
Bounded Context:  BC3 — Node Catalog
Responsibility:   Map fully-qualified PortDataType class names to Python type
                  objects. Enables string-based type resolution at runtime.
Owns:             TypeCatalogue — register(), resolve(), list_types().
Public Surface:   TypeCatalogue.
Must NOT:         Import from app.domain, app.api, or any BC4/BC5/BC6 module.
Dependencies:     BC2 (nodes.errors, nodes.ports), stdlib (threading).
Reason To Change: Type resolution strategy changes, or new catalogue query
                  methods are needed.
"""
from __future__ import annotations

import threading

from app.core.nodes.errors import DuplicatePortTypeError, PortTypeNotFoundError
from app.core.nodes.ports import PortDataType


def _fqn(cls: type) -> str:
    """Return the fully-qualified name: '{module}.{qualname}'."""
    return f"{cls.__module__}.{cls.__qualname__}"


class TypeCatalogue:
    """Maps fully-qualified type names to Python type objects.

    Populated by AutoDiscovery for every PortDataType subclass found
    during scanning.  Used by the pipeline builder to resolve string
    type references in YAML/JSON configs.
    """

    def __init__(self) -> None:
        self._types: dict[str, type] = {}
        self._lock = threading.RLock()  # G1-38 fix: guards _types for thread safety

    def register(self, type_class: type) -> None:
        """Register a PortDataType subclass.

        Raises:
            TypeError: if type_class is not a concrete subclass of PortDataType
                       (the base class itself is rejected).
            DuplicatePortTypeError: if the fully-qualified name is already
                       registered by a *different* class object.  If the same
                       class object is already registered under any FQN (e.g.
                       re-imported under a shorter module path), the call is a
                       silent no-op so that plugin loaders can safely call
                       register() without tracking which types they have already
                       catalogued.
        """
        with self._lock:
            # F2 fix: reject the abstract base class itself
            if not (
                isinstance(type_class, type)
                and issubclass(type_class, PortDataType)
                and type_class is not PortDataType
            ):
                raise TypeError(
                    f"{type_class!r} is not a concrete subclass of PortDataType"
                )
            # F1 fix: if the same class object is already registered under any
            # FQN (e.g. loaded via two different import paths), skip silently
            # rather than creating a duplicate entry.
            for existing_cls in self._types.values():
                if existing_cls is type_class:
                    return
            name = _fqn(type_class)
            if name in self._types:
                raise DuplicatePortTypeError(
                    f"PortDataType '{name}' is already registered "
                    f"(existing: {self._types[name]!r}, new: {type_class!r})"
                )
            self._types[name] = type_class

    def resolve(self, type_name: str) -> type:
        """Return the Python type for the given fully-qualified name.

        Raises:
            PortTypeNotFoundError: if the name is not registered.
        """
        with self._lock:
            if type_name not in self._types:
                # F3 fix: cap the sample list so the error message stays
                # readable even when hundreds of types are registered.
                all_types = sorted(self._types)
                sample = all_types[:10]
                suffix = (
                    f" … and {len(all_types) - 10} more"
                    if len(all_types) > 10
                    else ""
                )
                raise PortTypeNotFoundError(
                    f"Port type '{type_name}' is not registered in TypeCatalogue. "
                    f"Known types (sample): {sample}{suffix}"
                )
            return self._types[type_name]

    def list_types(self) -> list[str]:
        """Return a sorted list of all registered fully-qualified type names."""
        with self._lock:
            return sorted(self._types)

    def __contains__(self, type_name: str) -> bool:
        with self._lock:
            return type_name in self._types
