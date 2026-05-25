---
inclusion: fileMatch
fileMatchPattern: "app/core/nodes/registry.py,app/core/nodes/discovery.py,app/core/nodes/catalogue.py,app/core/nodes/compat.py,app/core/nodes/errors.py,app/core/nodes/__init__.py"
---

# Node Registry, AutoDiscovery, and Type System

## Registry Access

```python
from app.core.nodes import registry          # preferred
from app.core.registry_runtime import get_registry; registry = get_registry()

# Capability resolution (canonical — use this, not orchestrator._resolve_capability)
from app.core.registry_runtime import resolve_capability
cap = resolve_capability(ir_node, registry)
```

## `NodeRegistry` Key Methods

| Method | Returns |
|---|---|
| `register(node_type, node_class, metadata)` | `None` — registers a node class |
| `unregister(node_type)` | `None` — removes a node type; no-op if not registered |
| `get_class(node_type)` | Node subclass — raises `NodeNotFoundError` |
| `get_metadata(node_type)` | `NodeMetadata` — raises `NodeNotFoundError` |
| `list_nodes(category=None)` | `list[NodeMetadata]` |
| `find_compatible_nodes(port_type, direction)` | `list[NodeMetadata]` |
| `get_config_schema(node_type)` | JSON Schema dict |
| `"clean" in registry` | `bool` |

### `unregister()` Notes

- Called by `PluginManager` when **disabling** or **uninstalling** a plugin to remove its contributed node types.
- Removes entries from both `_classes` and `_metadata` via `dict.pop(key, None)`.
- Safe to call with an unknown `node_type` — silently does nothing (no exception raised).

Registry also holds `type_catalogue: TypeCatalogue`.

## `AutoDiscovery`

**Registration:** `Node` subclasses with `metadata: ClassVar[NodeMetadata]` → `NodeRegistry`. `PortDataType` subclasses → `TypeCatalogue`.

**`AutoDiscovery` scans at import via `app/core/nodes/__init__.py`:**
1. `app/core/nodes/` — skips framework files (base, ports, config, etc.)
2. `app/models/` — registers `PortDataType` subclasses
3. `plugins/` (or `GRAPHYN_PLUGINS_DIR`) — loads all enabled plugins

**`node_type` derivation** (if not set): PascalCase → snake_case, strip `_node` suffix. Always set explicitly.

**Errors:** missing `metadata` → warning + skip. Duplicate `node_type` → `DuplicateNodeTypeError` (server fails to start). Import error → warning + skip.

## `TypeCatalogue`

```python
catalogue.resolve("app.models.audio_sample.AudioSample")  # → AudioSample class
catalogue.list_types()   # sorted FQN strings
```

## `CompatibilityChecker`

```python
CompatibilityChecker.are_compatible(output_type, input_type) → bool
CompatibilityChecker.check_connection(src_node, src_port, dst_node, dst_port)  # raises NodeTypeError
```

Rules: `(None, None)` → True; `(X, None)` → False; plain classes → `issubclass`; generics → origins + args. Union/Optional handled via rules 4a/4b/4c.

## `_type_to_schema`

Converts a port `data_type` to a minimal JSON Schema dict. Returns `None` for `None` input.

| Input | Output |
|---|---|
| `Optional[X]` | `{**schema_of_X, "nullable": True}` |
| `Union[X, Y]` | `{"oneOf": [schema_of_X, schema_of_Y]}` |
| `Union[X, Y, None]` | `{"oneOf": [...], "nullable": True}` |
| `X \| Y` (Python 3.10+) | same as `Union[X, Y]` |
| `list[X]` | `{"type": "array", "items": schema_of_X}` |
| `dict` | `{"type": "object"}` |
| `int/float/str/bool/bytes` | `{"type": "integer/number/string/boolean/string"}` |
| Pydantic model | `model.model_json_schema()` |
| other | `{"type": "object", "title": type_name}` |

## Exception Hierarchy

```
NodeSystemError
├── NodeNotFoundError          # node_type not in registry
├── DuplicateNodeTypeError     # two classes claim same node_type
├── NodeMetadataError          # Node subclass missing metadata ClassVar
├── NodeTypeError              # incompatible port types
├── PortTypeNotFoundError      # type name not in TypeCatalogue
├── DuplicatePortTypeError     # PortDataType FQN already registered
└── PipelineGraphError         # cycle, missing port, unknown node ID

RuntimeError
└── ResumeError                # resume operation cannot be completed
```
