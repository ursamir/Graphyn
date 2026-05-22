# R3 · R4 · R13 — Registration, Metadata, and Type Catalogue

← [Back to master requirements](requirements.md)

---

## Requirement 3: Auto-Registration via Directory Scanning

**User Story:** As a node author, I want to drop a new node file into the nodes directory and have it automatically available in the registry, so that I never need to manually edit `registry.py`.

### Acceptance Criteria

1. `AutoDiscovery.run()` SHALL be called once inside `app/core/nodes/__init__.py` at module import time, scanning all `.py` files in `app/core/nodes/` excluding `__init__.py`, `base.py`, and files whose name begins with `_`.
2. WHEN a scanned module defines one or more classes that are subclasses of `Node` (and are not `Node` itself), `AutoDiscovery` SHALL register each such class in the `NodeRegistry` under its `node_type` class attribute, which MUST be a non-empty string.
3. WHEN a `Node` subclass does not define a `node_type` class attribute, `AutoDiscovery` SHALL derive the type name by converting the class name from `PascalCase` to `snake_case` (insert `_` before each uppercase letter that is not the first character, then lowercase the entire string) and stripping a trailing `_node` suffix. Examples: `FilterNode` → `filter`, `TFLiteProcessorNode` → `tf_lite_processor`, `AudioMixerNode` → `audio_mixer`.
4. WHEN two classes resolve to the same `node_type`, `AutoDiscovery` SHALL raise `DuplicateNodeTypeError` identifying both classes and the conflicting name.
5. `AutoDiscovery` SHALL also scan the `plugins/` directory (configurable via the `GRAPHYN_PLUGINS_DIR` environment variable) using the same rules: same exclusion list, same `Node` subclass detection, same `PortDataType` subclass detection, and same error handling.
6. WHEN a scanned file raises an `ImportError` or any other exception during import, `AutoDiscovery` SHALL log a warning with the file path and exception traceback, and continue scanning remaining files.
7. `NodeRegistry` SHALL be a module-level singleton instantiated in `app/core/nodes/__init__.py`. Importing `app.core.nodes` SHALL guarantee the registry is fully populated before any pipeline is constructed.
8. WHEN a scanned module defines a class that is a subclass of `PortDataType` (and is not `PortDataType` itself), `AutoDiscovery` SHALL register that class in the `TypeCatalogue` under its fully-qualified type name (`"{module}.{qualname}"`).
9. WHEN a `PortDataType` subclass is registered and a class with the same fully-qualified name is already present in the `TypeCatalogue`, `AutoDiscovery` SHALL raise `DuplicatePortTypeError` identifying both classes and the conflicting name.

---

## Requirement 4: NodeMetadata for Introspection

**User Story:** As a UI developer, I want to query a node's metadata — including all its port definitions — from a single source of truth, so that I can render node palettes, port connection validators, and configuration forms without duplicating information.

### Acceptance Criteria

1. Each `Node` subclass SHALL declare a class-level `metadata` attribute that is an instance of `NodeMetadata`. `NodeMetadata` SHALL carry:
   - `node_type: str` — required, non-empty.
   - `label: str` — required, human-readable display name.
   - `description: str` — required, one-sentence description.
   - `category: str` — required (e.g. `"Audio"`, `"ML"`, `"Data"`).
   - `version: str` — defaults to `"1.0.0"`.
   - `tags: list[str]` — defaults to `[]`.
   - `input_ports: dict[str, InputPort]` — mirrors the node's `input_ports` class attribute; populated automatically by `AutoDiscovery` if not set explicitly.
   - `output_ports: dict[str, OutputPort]` — mirrors the node's `output_ports` class attribute; populated automatically by `AutoDiscovery` if not set explicitly.
2. `NodeMetadata` SHALL be a Pydantic model so that it can be serialised to JSON for API responses.
3. WHEN `AutoDiscovery` encounters a `Node` subclass whose `metadata` is missing any required field (`node_type`, `label`, `description`, `category`), `AutoDiscovery` SHALL raise `NodeMetadataError` identifying the class and the missing fields.
4. `NodeRegistry.get_metadata(node_type: str) -> NodeMetadata` SHALL return the metadata for a registered node type. WHEN called with an unregistered `node_type`, it SHALL raise `NodeNotFoundError` identifying the unknown type.
5. `NodeRegistry.list_nodes(category: str | None = None) -> list[NodeMetadata]` SHALL return metadata for all registered nodes, optionally filtered by `category`. WHEN called with a `category` that has no registered nodes, it SHALL return an empty list.

---

## Requirement 13: Type Catalogue and Reverse Node Discovery

**User Story:** As a pipeline builder, I want the system to maintain a catalogue of all registered port types and expose reverse-lookup queries, so that I can reference types by name in YAML/JSON configs and discover which nodes are compatible with a given type.

### Acceptance Criteria

#### 13A — TypeCatalogue

1. `NodeRegistry` SHALL maintain a `TypeCatalogue` instance that maps fully-qualified type names (`"{module}.{qualname}"`) to Python `type` objects for all `PortDataType` subclasses registered during `AutoDiscovery`.
2. `TypeCatalogue.register(type_class: type) -> None` SHALL add a type to the catalogue under its fully-qualified name. WHEN called with a type that is not a subclass of `PortDataType`, it SHALL raise `TypeError`. WHEN called with a type whose fully-qualified name is already present, it SHALL raise `DuplicatePortTypeError`.
3. `TypeCatalogue.resolve(type_name: str) -> type` SHALL return the Python type for the given fully-qualified name. WHEN the name is not registered, it SHALL raise `PortTypeNotFoundError` with the unresolved name.
4. `TypeCatalogue.list_types() -> list[str]` SHALL return a sorted list of all registered fully-qualified type names.

#### 13B — Reverse Node Discovery

5. `NodeRegistry.find_compatible_nodes(port_type: type, direction: Literal["input", "output"]) -> list[NodeMetadata]` SHALL return metadata for all registered nodes whose port is compatible with `port_type`.
6. WHEN `direction="input"`, the method SHALL return all nodes `n` that have at least one input port `p` for which `are_compatible(port_type, p.data_type)` is `True` — i.e. nodes that can consume `port_type`.
7. WHEN `direction="output"`, the method SHALL return all nodes `n` that have at least one output port `p` for which `are_compatible(p.data_type, port_type)` is `True` — i.e. nodes that produce a type compatible with `port_type`.

#### 13C — String Type Resolution in Pipeline Configs

8. WHEN a YAML or JSON pipeline configuration references a port type as a string (e.g. `data_type: "app.core.nodes.tflite.TFLiteModel"`), the System SHALL resolve the string to a Python type via `TypeCatalogue.resolve` at pipeline build time, before `are_compatible` is called.
9. IF a pipeline configuration references a port type string that cannot be resolved, the System SHALL raise `PortTypeNotFoundError` identifying the unresolved type name and the pipeline step where it was referenced.
