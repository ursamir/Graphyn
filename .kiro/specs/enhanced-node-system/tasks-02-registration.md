# Tasks 02 — Registration: Metadata, TypeCatalogue, NodeRegistry, AutoDiscovery, `__init__.py`

← [Back to tasks.md](tasks.md)

---

## Tasks

- [x] 10. Create `app/core/nodes/metadata.py` — `NodeMetadata`
  - Implement `NodeMetadata(BaseModel)` with fields: `node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`
  - Add `@field_validator` for `node_type`, `label`, `description`, `category` rejecting empty strings
  - Store ports as `dict[str, dict[str, Any]]` (serialisable dicts, not `InputPort`/`OutputPort` objects)
  - _Requirements: R4.1–R4.2_
  - _Design: design-02-registration.md § 1_

- [x] 11. Create `app/core/nodes/catalogue.py` — `TypeCatalogue`
  - Implement `TypeCatalogue` with `_types: dict[str, type]`
  - Implement `register(type_class)` raising `TypeError` for non-`PortDataType` subclasses and `DuplicatePortTypeError` for duplicate FQNs
  - Implement `resolve(type_name)` raising `PortTypeNotFoundError` when not found
  - Implement `list_types() -> list[str]` returning sorted FQNs
  - Implement `__contains__`
  - Implement module-level `_fqn(cls) -> str` helper
  - _Requirements: R13A.1–R13A.4_
  - _Design: design-02-registration.md § 2_

- [x] 12. Rewrite `app/core/nodes/registry.py` — `NodeRegistry` singleton class
  - Replace the existing `NODE_REGISTRY` dict with the `NodeRegistry` class
  - Implement `register(node_type, node_class, metadata)`, `get_class`, `get_metadata`, `list_nodes`, `find_compatible_nodes`
  - Implement `to_json() -> str` and `from_json(json_str) -> list[NodeMetadata]`
  - Implement `get_config_schema(node_type)` and `get_port_schema(node_type)`
  - Implement `__contains__` and `__len__`
  - Attach `type_catalogue: TypeCatalogue` as an instance attribute
  - _Requirements: R3.7, R4.4–R4.5, R11.1–R11.3, R12.1–R12.4, R13A.1, R13B.5–R13B.7_
  - _Design: design-02-registration.md § 3_

- [x] 13. Create `app/core/nodes/discovery.py` — `AutoDiscovery`
  - Implement `AutoDiscovery(registry)` with `run(nodes_dir, plugins_dir)` entry point
  - Implement `_scan_directory(directory, package_prefix)` iterating sorted `*.py` files, skipping `__init__.py`, `base.py`, and `_`-prefixed files
  - Implement `_import_file(path, package_prefix)` using `importlib.import_module` for package files and `importlib.util.spec_from_file_location` for plugins
  - Implement `_process_module(module)` detecting `PortDataType` subclasses (→ `TypeCatalogue`) and `Node` subclasses (→ `_register_node`)
  - Implement `_register_node(cls)` with `node_type` derivation (PascalCase → snake_case, strip `_node`), duplicate detection, metadata validation, and port dict population
  - Implement `_pascal_to_snake` and `_port_to_dict` helpers
  - Log warnings (not exceptions) on import failures; raise `DuplicateNodeTypeError` / `DuplicatePortTypeError` / `NodeMetadataError` on structural errors
  - _Requirements: R3.1–R3.9, R4.3_
  - _Design: design-02-registration.md § 4_

- [x] 14. Rewrite `app/core/nodes/__init__.py` — singleton wiring
  - Instantiate `registry = NodeRegistry()` at module level
  - Resolve `_nodes_dir` and `_plugins_dir` (from `GRAPHYN_PLUGINS_DIR` env var or default `plugins/`)
  - Call `AutoDiscovery(registry).run(nodes_dir=_nodes_dir, plugins_dir=_plugins_dir)` at import time
  - Export `registry` in `__all__`
  - _Requirements: R3.1, R3.7_
  - _Design: design-02-registration.md § 5_

- [x]* 15. Write unit tests for registration layer (`tests/test_registration.py`)
  - Test `TypeCatalogue.register` with non-`PortDataType` → `TypeError`
  - Test `TypeCatalogue.register` duplicate FQN → `DuplicatePortTypeError`
  - Test `TypeCatalogue.resolve` unknown name → `PortTypeNotFoundError`
  - Test `NodeRegistry.get_class` / `get_metadata` for registered and unregistered types
  - Test `NodeRegistry.list_nodes` with and without category filter
  - Test `NodeRegistry.from_json` with invalid JSON → `ValueError`; invalid schema → `ValidationError`
  - Test `AutoDiscovery` duplicate `node_type` → `DuplicateNodeTypeError`
  - Test `AutoDiscovery` missing metadata fields → `NodeMetadataError`
  - Test `AutoDiscovery` import failure → warning logged, scan continues
  - Test `_pascal_to_snake` derivation examples from design table
  - _Requirements: R3.2–R3.6, R3.8–R3.9, R4.3–R4.5, R13A.2–R13A.3_

- [x] 16. Checkpoint — registration layer
  - Ensure all tests pass, ask the user if questions arise.
