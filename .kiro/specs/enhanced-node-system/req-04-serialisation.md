# R10 · R11 · R12 — Migration, Serialisation, and Schema Export

← [Back to master requirements](requirements.md)

---

## Requirement 10: Migration of Existing Audio Nodes

**User Story:** As a maintainer, I want all existing audio nodes migrated to the new multi-port system, so that the codebase has a single, consistent node contract with no legacy code paths.

### Acceptance Criteria

1. ALL existing audio nodes (`InputNode`, `CleanNode`, `AugmentNode`, and all other `Node` subclasses in `app/core/nodes/`) SHALL be updated to declare `input_ports` and `output_ports` using `InputPort` and `OutputPort` instances with real Python `data_type` values (not strings or enums).
2. ALL existing audio nodes SHALL replace any plain `dict` config with a concrete `NodeConfig` Pydantic model subclass specific to that node.
3. THE `validate_pipeline` function in `app/core/validation.py` SHALL be updated to use `CompatibilityChecker.check_connection` for all port-to-port connections, replacing any string-based type comparison.
4. THE old `app/core/nodes/registry.py` hand-written registry format SHALL be removed; node registration SHALL occur exclusively through `AutoDiscovery`.
5. All existing audio nodes are SISO nodes (one input port named `"input"`, one output port named `"output"`). They SHALL be migrated as SISO nodes using the convenience shorthand defined in Requirement 2B, preserving their existing `process(self, data)` signature.
6. For each migrated node, the output of `node.process(data)` given the same `data` and equivalent config values SHALL be identical to the pre-migration output: byte-for-byte identical for deterministic nodes, or statistically equivalent (same distribution) for stochastic nodes when initialised with the same random seed.
7. WHEN a migrated node's `NodeConfig` is instantiated with a `dict` that was previously accepted by the old node's `REQUIRED_CONFIG` check and schema defaults, `NodeConfig.model_validate(dict)` SHALL accept those values without raising `pydantic.ValidationError`.

---

## Requirement 11: Round-Trip Serialisation of NodeMetadata

**User Story:** As an API developer, I want to serialise and deserialise the full node registry to/from JSON, so that the frontend can receive a complete node catalogue — including all port definitions — in a single API response.

### Acceptance Criteria

1. `NodeRegistry.to_json() -> str` SHALL serialise all registered `NodeMetadata` entries (including their `input_ports` and `output_ports`) to a JSON array string.
2. `to_json()` SHALL produce a JSON array string such that `[NodeMetadata.model_validate(item) for item in json.loads(result)]` produces a list equal to the original list of registered `NodeMetadata` objects (round-trip property). Port type information SHALL be serialised as the fully-qualified type name string and deserialised back to the same string (not to the Python type object, since types are not JSON-serialisable).
3. `NodeRegistry.from_json(json_str: str) -> list[NodeMetadata]` SHALL reconstruct the metadata list from a JSON string produced by `to_json()`. WHEN called with a string that is not valid JSON, it SHALL raise `ValueError`. WHEN called with valid JSON that does not conform to `NodeMetadata`'s schema, it SHALL raise `pydantic.ValidationError`.

---

## Requirement 12: Config Schema Export

**User Story:** As a UI developer, I want to retrieve the JSON Schema for any node's configuration model and its port definitions, so that I can render dynamic configuration forms and port connection UIs without hardcoding field definitions.

### Acceptance Criteria

1. `NodeRegistry.get_config_schema(node_type: str) -> dict` SHALL return the JSON Schema of the node's `NodeConfig` Pydantic model (output of `NodeConfig.model_json_schema()`). WHEN called with an unregistered `node_type`, it SHALL raise `NodeNotFoundError`.
2. The returned schema SHALL always include `"type": "object"` and `"properties"` (guaranteed by Pydantic v2's `model_json_schema()`).
3. FOR ALL registered node types `t`, calling `get_config_schema(t)` twice SHALL return structurally equal dicts (idempotence).
4. `NodeRegistry.get_port_schema(node_type: str) -> dict` SHALL return the output of `Node.port_schemas()` for the given node type (as defined in Requirement 2E criterion 14). WHEN called with an unregistered `node_type`, it SHALL raise `NodeNotFoundError`.
