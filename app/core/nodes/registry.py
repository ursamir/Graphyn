# app/core/nodes/registry.py
"""
Bounded Context:  BC3 — Node Catalog
Responsibility:   Thread-safe singleton registry mapping node_type strings to
                  Node classes and NodeMetadata.
Owns:             NodeRegistry — register, unregister, get_class, get_metadata,
                  list_nodes, find_compatible_nodes, to_json, get_config_schema,
                  get_port_schema.
Public Surface:   NodeRegistry (all public methods above).
Must NOT:         Import from app.domain, app.api, app.core.orchestrator,
                  app.core.planner, or any BC4/BC5/BC6 module.
Dependencies:     BC2 (nodes.catalogue, nodes.compat, nodes.errors,
                  nodes.metadata, nodes.ports), stdlib (json, threading).
Reason To Change: Registry query API changes, new introspection methods are
                  added, or thread-safety strategy evolves.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Literal

import pydantic

from app.core.nodes.catalogue import TypeCatalogue
from app.core.nodes.compat import CompatibilityChecker
from app.core.nodes.errors import NodeNotFoundError
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import PortDataType


class NodeRegistry:
    """Singleton registry mapping node_type strings to Node classes and metadata.

    Thread-safe: all mutations and reads that iterate the dicts acquire
    ``_lock`` (a reentrant lock so that methods can call each other safely).

    Instantiated once in app/core/nodes/__init__.py.  All pipeline
    construction code imports the singleton via:

        from app.core.nodes import registry
    """

    def __init__(self) -> None:
        self._classes: dict[str, type] = {}           # node_type → Node subclass
        self._metadata: dict[str, NodeMetadata] = {}  # node_type → NodeMetadata
        self.type_catalogue = TypeCatalogue()
        self._lock = threading.RLock()  # N-08 fix: guards _classes and _metadata

    # ── registration ─────────────────────────────────────────────────────────

    def register(
        self,
        node_type: str,
        node_class: type,
        metadata: NodeMetadata,
    ) -> None:
        """Register a node class under node_type.

        Also registers any PortDataType subclasses used by the node's input
        and output ports into ``type_catalogue``.  This ensures that port
        types are resolvable via ``type_catalogue.resolve()`` even when a
        node is registered directly (bypassing AutoDiscovery).

        The catalogue registration is idempotent: types already catalogued
        (e.g. by AutoDiscovery) are silently skipped because
        ``TypeCatalogue.register()`` performs an identity check and returns
        early for already-registered class objects.
        """
        with self._lock:
            self._classes[node_type] = node_class
            self._metadata[node_type] = metadata
            # F4 fix: auto-register port data types so that catalogue.resolve()
            # works for nodes registered outside of AutoDiscovery._register_node.
            for port in (
                *node_class.input_ports.values(),
                *node_class.output_ports.values(),
            ):
                dt = port.data_type
                if (
                    isinstance(dt, type)
                    and issubclass(dt, PortDataType)
                    and dt is not PortDataType
                ):
                    # TypeCatalogue.register() is idempotent for the same class
                    # object (returns early); DuplicatePortTypeError is only
                    # raised for a *different* class with the same FQN, which
                    # we propagate so the caller knows about the conflict.
                    self.type_catalogue.register(dt)

    def unregister(self, node_type: str) -> None:
        """Remove a node type from the registry (no-op if not registered)."""
        with self._lock:
            self._classes.pop(node_type, None)
            self._metadata.pop(node_type, None)

    # ── lookup ────────────────────────────────────────────────────────────────

    def get_class(self, node_type: str) -> type:
        """Return the Node subclass for node_type.

        Raises:
            NodeNotFoundError: if node_type is not registered.
        """
        with self._lock:
            if node_type not in self._classes:
                raise NodeNotFoundError(
                    f"Node type '{node_type}' is not registered. "
                    f"Registered types: {sorted(self._classes)}"
                )
            return self._classes[node_type]

    def get_metadata(self, node_type: str) -> NodeMetadata:
        """Return NodeMetadata for node_type.

        Raises:
            NodeNotFoundError: if node_type is not registered.
        """
        with self._lock:
            if node_type not in self._metadata:
                raise NodeNotFoundError(
                    f"Node type '{node_type}' is not registered."
                )
            return self._metadata[node_type]

    def list_nodes(self, category: str | None = None) -> list[NodeMetadata]:
        """Return metadata for all registered nodes, optionally filtered by category.

        Returns shallow copies of each ``NodeMetadata`` so that callers cannot
        mutate the live registry entries.
        """
        with self._lock:
            all_meta = list(self._metadata.values())
        return [
            m.model_copy()
            for m in all_meta
            if category is None or m.category == category
        ]

    # ── reverse discovery ─────────────────────────────────────────────────────

    def find_compatible_nodes(
        self,
        port_type: type,
        direction: Literal["input", "output"],
    ) -> list[NodeMetadata]:
        """Return metadata for nodes whose ports are compatible with port_type.

        G1-24 fix: both _classes and _metadata are snapshotted under a single
        lock acquisition.  The loop then operates on the snapshots with no lock
        held, so unregister() racing between the snapshot and the metadata
        lookup can no longer cause a KeyError.
        """
        with self._lock:
            classes_snapshot = list(self._classes.items())
            meta_snapshot = dict(self._metadata)
        result = []
        for node_type, node_class in classes_snapshot:
            if direction == "input":
                ports = node_class.input_ports.values()
                if any(
                    CompatibilityChecker.are_compatible(port_type, p.data_type)
                    for p in ports
                ):
                    meta = meta_snapshot.get(node_type)
                    if meta is None:
                        continue  # node was unregistered between snapshot and here
                    result.append(meta)
            else:
                ports = node_class.output_ports.values()
                if any(
                    CompatibilityChecker.are_compatible(p.data_type, port_type)
                    for p in ports
                ):
                    meta = meta_snapshot.get(node_type)
                    if meta is None:
                        continue  # node was unregistered between snapshot and here
                    result.append(meta)
        return result

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_json(self) -> str:
        """Serialise all NodeMetadata entries to a JSON array string."""
        with self._lock:
            meta_list = list(self._metadata.values())
        return json.dumps(
            [m.model_dump(mode="json") for m in meta_list],
            indent=2,
        )

    @staticmethod
    def parse_metadata_list(json_str: str) -> list[NodeMetadata]:
        """Reconstruct a NodeMetadata list from a JSON string produced by to_json().

        Raises:
            ValueError: if json_str is not valid JSON.
            pydantic.ValidationError: if the JSON does not conform to NodeMetadata schema.

        Note: previously named ``from_json`` which was misleading (it does not
        populate a registry). Renamed to ``parse_metadata_list`` for clarity.
        """
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if not isinstance(raw, list):
            raise ValueError(
                f"Expected a JSON array, got {type(raw).__name__}"
            )
        return [NodeMetadata.model_validate(item) for item in raw]

    # Keep old name as an alias for backward compatibility
    @staticmethod
    def from_json(json_str: str) -> list[NodeMetadata]:
        """Deprecated alias for ``parse_metadata_list``."""
        return NodeRegistry.parse_metadata_list(json_str)

    # ── schema export ─────────────────────────────────────────────────────────

    def get_config_schema(self, node_type: str) -> dict[str, Any]:
        """Return the JSON Schema for the node's Config Pydantic model.

        Raises:
            NodeNotFoundError: if node_type is not registered or has no
                Pydantic Config class.
        """
        node_class = self.get_class(node_type)
        cfg = getattr(node_class, "Config", None)
        if cfg is None or not hasattr(cfg, "model_json_schema"):
            raise NodeNotFoundError(
                f"Node '{node_type}' has no Pydantic Config class."
            )
        return cfg.model_json_schema()

    def get_port_schema(self, node_type: str) -> dict[str, Any]:
        """Return the port schema dict (inputs + outputs) for the node.

        Raises:
            NodeNotFoundError: if node_type is not registered or does not
                expose a callable ``port_schemas`` method.
        """
        node_class = self.get_class(node_type)
        port_schemas_fn = getattr(node_class, "port_schemas", None)
        if not callable(port_schemas_fn):
            raise NodeNotFoundError(
                f"Node '{node_type}' does not expose a callable 'port_schemas' method."
            )
        return port_schemas_fn()

    # ── introspection ─────────────────────────────────────────────────────────

    def __contains__(self, node_type: str) -> bool:
        with self._lock:
            return node_type in self._classes

    def __len__(self) -> int:
        with self._lock:
            return len(self._classes)
