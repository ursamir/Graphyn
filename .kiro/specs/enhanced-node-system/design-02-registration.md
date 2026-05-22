# Design 02 — Registration, Metadata, and Type Catalogue

← [Back to design.md](design.md) | ← [Back to requirements](req-02-registration.md)

---

## 1. `NodeMetadata`

```python
# app/core/nodes/metadata.py
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, field_validator


class NodeMetadata(BaseModel):
    """Describes a node's identity, ports, and display properties.

    Serialisable to JSON for API responses. AutoDiscovery populates
    input_ports and output_ports from the node class if not set explicitly.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    node_type: str
    label: str
    description: str
    category: str
    version: str = "1.0.0"
    tags: list[str] = []

    # Populated by AutoDiscovery from the node class's port declarations.
    # Stored as serialisable dicts (port name → port schema dict) rather
    # than InputPort/OutputPort objects so that NodeMetadata can be
    # round-tripped through JSON without losing type information.
    input_ports: dict[str, dict[str, Any]] = {}
    output_ports: dict[str, dict[str, Any]] = {}

    @field_validator("node_type", "label", "description", "category")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be a non-empty string")
        return v
```

> **Port serialisation in metadata**: `InputPort` and `OutputPort` objects carry Python `type` objects in their `data_type` field, which are not JSON-serialisable. `NodeMetadata` therefore stores ports as plain dicts produced by `InputPort.model_dump()` with `data_type` replaced by its fully-qualified name string. `AutoDiscovery` performs this conversion when populating metadata.

---

## 2. `TypeCatalogue`

```python
# app/core/nodes/catalogue.py
from __future__ import annotations

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

    def register(self, type_class: type) -> None:
        """Register a PortDataType subclass.

        Raises:
            TypeError: if type_class is not a subclass of PortDataType.
            DuplicatePortTypeError: if the fully-qualified name is already registered.
        """
        if not (isinstance(type_class, type) and issubclass(type_class, PortDataType)):
            raise TypeError(
                f"{type_class!r} is not a subclass of PortDataType"
            )
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
        if type_name not in self._types:
            raise PortTypeNotFoundError(
                f"Port type '{type_name}' is not registered in TypeCatalogue. "
                f"Registered types: {sorted(self._types)}"
            )
        return self._types[type_name]

    def list_types(self) -> list[str]:
        """Return a sorted list of all registered fully-qualified type names."""
        return sorted(self._types)

    def __contains__(self, type_name: str) -> bool:
        return type_name in self._types
```

---

## 3. `NodeRegistry`

```python
# app/core/nodes/registry.py
from __future__ import annotations

import json
from typing import Any, Literal

import pydantic

from app.core.nodes.catalogue import TypeCatalogue
from app.core.nodes.compat import CompatibilityChecker
from app.core.nodes.errors import NodeNotFoundError
from app.core.nodes.metadata import NodeMetadata


class NodeRegistry:
    """Singleton registry mapping node_type strings to Node classes and metadata.

    Instantiated once in app/core/nodes/__init__.py.  All pipeline
    construction code imports the singleton via:

        from app.core.nodes import registry
    """

    def __init__(self) -> None:
        self._classes: dict[str, type] = {}          # node_type → Node subclass
        self._metadata: dict[str, NodeMetadata] = {} # node_type → NodeMetadata
        self.type_catalogue = TypeCatalogue()

    # ── registration ─────────────────────────────────────────────────────────

    def register(
        self,
        node_type: str,
        node_class: type,
        metadata: NodeMetadata,
    ) -> None:
        """Register a node class under node_type."""
        self._classes[node_type] = node_class
        self._metadata[node_type] = metadata

    # ── lookup ────────────────────────────────────────────────────────────────

    def get_class(self, node_type: str) -> type:
        """Return the Node subclass for node_type.

        Raises:
            NodeNotFoundError: if node_type is not registered.
        """
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
        if node_type not in self._metadata:
            raise NodeNotFoundError(
                f"Node type '{node_type}' is not registered."
            )
        return self._metadata[node_type]

    def list_nodes(self, category: str | None = None) -> list[NodeMetadata]:
        """Return metadata for all registered nodes, optionally filtered by category."""
        all_meta = list(self._metadata.values())
        if category is None:
            return all_meta
        return [m for m in all_meta if m.category == category]

    # ── reverse discovery ─────────────────────────────────────────────────────

    def find_compatible_nodes(
        self,
        port_type: type,
        direction: Literal["input", "output"],
    ) -> list[NodeMetadata]:
        """Return metadata for nodes whose ports are compatible with port_type.

        direction="input"  → nodes that can CONSUME port_type
                             (have an input port where are_compatible(port_type, p.data_type))
        direction="output" → nodes that PRODUCE a type compatible with port_type
                             (have an output port where are_compatible(p.data_type, port_type))
        """
        result = []
        for node_type, node_class in self._classes.items():
            if direction == "input":
                ports = node_class.input_ports.values()
                if any(
                    CompatibilityChecker.are_compatible(port_type, p.data_type)
                    for p in ports
                ):
                    result.append(self._metadata[node_type])
            else:
                ports = node_class.output_ports.values()
                if any(
                    CompatibilityChecker.are_compatible(p.data_type, port_type)
                    for p in ports
                ):
                    result.append(self._metadata[node_type])
        return result

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_json(self) -> str:
        """Serialise all NodeMetadata entries to a JSON array string."""
        return json.dumps(
            [m.model_dump(mode="json") for m in self._metadata.values()],
            indent=2,
        )

    @staticmethod
    def from_json(json_str: str) -> list[NodeMetadata]:
        """Reconstruct NodeMetadata list from a JSON string produced by to_json().

        Raises:
            ValueError: if json_str is not valid JSON.
            pydantic.ValidationError: if the JSON does not conform to NodeMetadata schema.
        """
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        return [NodeMetadata.model_validate(item) for item in raw]

    # ── schema export ─────────────────────────────────────────────────────────

    def get_config_schema(self, node_type: str) -> dict[str, Any]:
        """Return the JSON Schema for the node's Config Pydantic model.

        Raises:
            NodeNotFoundError: if node_type is not registered.
        """
        node_class = self.get_class(node_type)  # raises NodeNotFoundError if missing
        return node_class.Config.model_json_schema()

    def get_port_schema(self, node_type: str) -> dict[str, Any]:
        """Return the port schema dict (inputs + outputs) for the node.

        Raises:
            NodeNotFoundError: if node_type is not registered.
        """
        node_class = self.get_class(node_type)
        return node_class.port_schemas()

    # ── introspection ─────────────────────────────────────────────────────────

    def __contains__(self, node_type: str) -> bool:
        return node_type in self._classes

    def __len__(self) -> int:
        return len(self._classes)
```

---

## 4. `AutoDiscovery`

```python
# app/core/nodes/discovery.py
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.nodes.errors import (
    DuplicateNodeTypeError,
    DuplicatePortTypeError,
    NodeMetadataError,
)
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort, PortDataType

if TYPE_CHECKING:
    from app.core.nodes.base import Node
    from app.core.nodes.registry import NodeRegistry

log = logging.getLogger(__name__)

# Files excluded from scanning in the nodes directory
_EXCLUDED_FILES = {"__init__.py", "base.py"}
_EXCLUDED_PREFIXES = {"_"}

# Regex for PascalCase → snake_case conversion
_PASCAL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _pascal_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case and strip trailing '_node' suffix.

    Examples:
        FilterNode        → filter
        TFLiteProcessorNode → tf_lite_processor
        AudioMixerNode    → audio_mixer
    """
    snake = _PASCAL_RE.sub("_", name).lower()
    if snake.endswith("_node"):
        snake = snake[:-5]
    return snake


def _fqn(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _port_to_dict(port: InputPort | OutputPort) -> dict:
    """Serialise a port to a dict, replacing data_type with its fqn string."""
    d = port.model_dump()
    dt = port.data_type
    if dt is None:
        d["data_type"] = None
    elif hasattr(dt, "__module__") and hasattr(dt, "__qualname__"):
        d["data_type"] = _fqn(dt)
    else:
        d["data_type"] = str(dt)
    return d


class AutoDiscovery:
    """Scans node directories and registers Node/PortDataType subclasses."""

    def __init__(self, registry: "NodeRegistry") -> None:
        self._registry = registry

    def run(
        self,
        nodes_dir: str | Path,
        plugins_dir: str | Path | None = None,
    ) -> None:
        """Scan nodes_dir (and optionally plugins_dir) and populate the registry."""
        self._scan_directory(Path(nodes_dir), package_prefix="app.core.nodes")

        if plugins_dir is None:
            plugins_dir = os.environ.get("GRAPHYN_PLUGINS_DIR", "plugins")

        plugins_path = Path(plugins_dir)
        if plugins_path.exists() and plugins_path.is_dir():
            self._scan_directory(plugins_path, package_prefix=None)

    def _scan_directory(
        self,
        directory: Path,
        package_prefix: str | None,
    ) -> None:
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name in _EXCLUDED_FILES:
                continue
            if any(py_file.name.startswith(p) for p in _EXCLUDED_PREFIXES):
                continue

            try:
                module = self._import_file(py_file, package_prefix)
            except Exception as exc:
                log.warning(
                    "AutoDiscovery: failed to import '%s': %s",
                    py_file,
                    exc,
                    exc_info=True,
                )
                continue

            self._process_module(module)

    def _import_file(self, path: Path, package_prefix: str | None):
        if package_prefix:
            # Use importlib.import_module for proper package resolution
            module_name = f"{package_prefix}.{path.stem}"
            return importlib.import_module(module_name)
        else:
            # Plugin file — load from path
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[path.stem] = module
            spec.loader.exec_module(module)
            return module

    def _process_module(self, module) -> None:
        from app.core.nodes.base import Node

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if not isinstance(obj, type):
                continue

            # Register PortDataType subclasses
            if (
                issubclass(obj, PortDataType)
                and obj is not PortDataType
                and obj.__module__ == module.__name__
            ):
                try:
                    self._registry.type_catalogue.register(obj)
                except DuplicatePortTypeError:
                    raise

            # Register Node subclasses
            if (
                issubclass(obj, Node)
                and obj is not Node
                and obj.__module__ == module.__name__
            ):
                self._register_node(obj)

    def _register_node(self, cls: type) -> None:
        from app.core.nodes.base import Node

        # Derive node_type
        node_type = getattr(cls, "node_type", "") or _pascal_to_snake(cls.__name__)

        # Check for duplicates
        if node_type in self._registry:
            existing = self._registry.get_class(node_type)
            if existing is not cls:
                raise DuplicateNodeTypeError(
                    f"node_type '{node_type}' is claimed by both "
                    f"{existing!r} and {cls!r}"
                )
            return  # already registered (e.g. re-import)

        # Validate metadata
        raw_meta = getattr(cls, "metadata", None)
        if raw_meta is None:
            # Auto-build minimal metadata from class attributes
            missing = []
            for field in ("label", "description", "category"):
                if not getattr(raw_meta, field, None):
                    missing.append(field)
            if missing:
                raise NodeMetadataError(
                    f"Node '{cls.__name__}' is missing metadata fields: {missing}. "
                    "Declare a 'metadata: ClassVar[NodeMetadata]' on the class."
                )

        meta: NodeMetadata = raw_meta

        # Populate port dicts on metadata if not already set
        if not meta.input_ports:
            object.__setattr__(
                meta,
                "input_ports",
                {k: _port_to_dict(v) for k, v in cls.input_ports.items()},
            )
        if not meta.output_ports:
            object.__setattr__(
                meta,
                "output_ports",
                {k: _port_to_dict(v) for k, v in cls.output_ports.items()},
            )

        self._registry.register(node_type, cls, meta)
```

---

## 5. `app/core/nodes/__init__.py`

```python
# app/core/nodes/__init__.py
"""Enhanced Node System — public API.

Importing this module guarantees:
  1. AutoDiscovery has scanned all node files and the plugins directory.
  2. The NodeRegistry singleton is fully populated.
  3. The TypeCatalogue contains all PortDataType subclasses.

Usage:
    from app.core.nodes import registry
    node_class = registry.get_class("clean")
    metadata   = registry.get_metadata("clean")
"""
from __future__ import annotations

import os
from pathlib import Path

from app.core.nodes.registry import NodeRegistry
from app.core.nodes.discovery import AutoDiscovery

# ── Singleton ─────────────────────────────────────────────────────────────────
registry = NodeRegistry()

# ── Auto-discovery ────────────────────────────────────────────────────────────
_nodes_dir = Path(__file__).parent
_plugins_dir = os.environ.get("GRAPHYN_PLUGINS_DIR", str(Path(__file__).parent.parent.parent.parent / "plugins"))

AutoDiscovery(registry).run(
    nodes_dir=_nodes_dir,
    plugins_dir=_plugins_dir,
)

__all__ = ["registry"]
```

---

## 6. Data Flow Diagram — Registration

```
Module import: "from app.core.nodes import registry"
        │
        ▼
app/core/nodes/__init__.py
        │
        ├─► NodeRegistry()  ──────────────────────────────────────────┐
        │                                                              │
        └─► AutoDiscovery(registry).run(nodes_dir, plugins_dir)       │
                │                                                      │
                ├─ scan app/core/nodes/*.py                           │
                │       │                                              │
                │       ├─ import module                               │
                │       ├─ find PortDataType subclasses               │
                │       │       └─► TypeCatalogue.register(cls)       │
                │       └─ find Node subclasses                       │
                │               ├─ derive node_type                   │
                │               ├─ validate NodeMetadata              │
                │               └─► NodeRegistry.register(...)  ──────┤
                │                                                      │
                └─ scan plugins/*.py  (same process)                  │
                                                                       │
                                                              registry (populated)
                                                                       │
                                                                       ▼
                                                          pipeline.py can now call:
                                                          registry.get_class("clean")
                                                          registry.get_metadata("split")
                                                          registry.type_catalogue.resolve(...)
```

---

## 7. `node_type` Derivation Examples

| Class name | Derived `node_type` |
|---|---|
| `FilterNode` | `filter` |
| `TFLiteProcessorNode` | `tf_lite_processor` |
| `AudioMixerNode` | `audio_mixer` |
| `CleanNode` | `clean` |
| `HFExportNode` | `hf_export` |
| `TFRecordExportNode` | `tf_record_export` |
| `StratifiedSplitNode` | `stratified_split` |
| `MicInputNode` | `mic_input` |

Nodes that declare `node_type: ClassVar[str] = "my_type"` use that value directly and skip derivation.
