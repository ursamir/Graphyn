# req-01 — Graph Intermediate Representation (IR)

## Introduction

This document defines requirements for the formal Graph IR: the versioned, validated, runtime-agnostic JSON schema that becomes the canonical representation of all pipelines in the platform.

The IR is defined as Pydantic models in `app/core/ir/` and is the single source of truth that all interfaces (SDK, CLI, REST API) produce and consume.

---

## Glossary

See [requirements.md](requirements.md) for the full glossary. Terms used here:

- **IR**, **IR_Schema**, **IR_Loader**, **Schema_Version**, **Seed**, **DAG_Executor**, **PipelineGraph**

---

## Requirements

### Requirement 1.1 — IR Module Location and Structure

**User Story:** As a platform developer, I want the IR defined in a dedicated module, so that it is clearly separated from execution logic and can be imported independently.

#### Acceptance Criteria

1. THE IR_Schema SHALL be defined as Pydantic `BaseModel` subclasses located in `app/core/ir/`.
2. THE IR_Schema SHALL export the following top-level models: `GraphIR`, `IRNode`, `IREdge`, `IRParameter`, `IRMetadata`.
3. THE IR_Schema SHALL be importable without importing any execution runtime components (no dependency on `app/core/pipeline.py`, `app/core/nodes/`, or `app/core/sdk.py`).
4. THE `app/core/ir/__init__.py` SHALL re-export all public IR model classes so that callers can import from `app.core.ir` directly.

---

### Requirement 1.2 — IR Schema: GraphIR Model

**User Story:** As a platform developer, I want a top-level `GraphIR` model that captures the complete graph definition, so that a single object fully describes an executable pipeline.

#### Acceptance Criteria

1. THE `GraphIR` model SHALL contain the following required fields:
   - `schema_version`: `str` — the IR schema version (e.g. `"1.0"`)
   - `metadata`: `IRMetadata` — graph-level metadata
   - `nodes`: `list[IRNode]` — ordered list of node specifications
   - `edges`: `list[IREdge]` — directed edges connecting node ports
2. THE `GraphIR` model SHALL contain the following optional fields with defaults:
   - `parameters`: `dict[str, IRParameter]` — graph-level parameter definitions (default: `{}`)
3. THE `GraphIR` model SHALL be serializable to a JSON-compatible dict via `.model_dump(mode="json")`.
4. THE `GraphIR` model SHALL be deserializable from a JSON-compatible dict via `.model_validate(data)`.
5. WHEN a `GraphIR` is serialized and then deserialized, THE IR_Schema SHALL produce an object equal to the original (round-trip property).

---

### Requirement 1.3 — IR Schema: IRMetadata Model

**User Story:** As a platform developer, I want graph-level metadata captured in a dedicated model, so that name, description, seed, and other graph properties are clearly separated from structural data.

#### Acceptance Criteria

1. THE `IRMetadata` model SHALL contain the following required fields:
   - `name`: `str` — human-readable graph name
   - `seed`: `int` — random seed for deterministic replay
2. THE `IRMetadata` model SHALL contain the following optional fields with defaults:
   - `description`: `str` — human-readable description (default: `""`)
   - `created_at`: `str | None` — ISO 8601 timestamp of creation (default: `None`)
   - `tags`: `list[str]` — user-defined tags (default: `[]`)

---

### Requirement 1.4 — IR Schema: IRNode Model

**User Story:** As a platform developer, I want each node in the IR to carry its identity, configuration, and capability metadata, so that the executor can instantiate and run it without consulting external sources.

#### Acceptance Criteria

1. THE `IRNode` model SHALL contain the following required fields:
   - `id`: `str` — unique node identifier within the graph (e.g. `"clean_0"`)
   - `node_type`: `str` — registry key matching a registered node class (e.g. `"clean"`)
   - `config`: `dict[str, Any]` — node configuration parameters
2. THE `IRNode` model SHALL contain the following optional fields with defaults:
   - `label`: `str | None` — display label override (default: `None`)
   - `capability_metadata`: `IRCapabilityMetadata | None` — capability hints (default: `None`; see req-05)
3. WHEN two `IRNode` objects in the same `GraphIR` have the same `id`, THE IR_Schema SHALL raise a `ValidationError` during `GraphIR` construction.
4. THE `IRNode.id` field SHALL only contain alphanumeric characters, underscores, or hyphens.

---

### Requirement 1.5 — IR Schema: IREdge Model

**User Story:** As a platform developer, I want edges to explicitly name source and destination nodes and ports, so that the executor can wire data flow without ambiguity.

#### Acceptance Criteria

1. THE `IREdge` model SHALL contain the following required fields:
   - `src_id`: `str` — source node `id`
   - `src_port`: `str` — source node output port name
   - `dst_id`: `str` — destination node `id`
   - `dst_port`: `str` — destination node input port name
2. WHEN an `IREdge` references a `src_id` or `dst_id` not present in `GraphIR.nodes`, THE IR_Loader SHALL raise a `ValidationError` with a message identifying the unknown node id.

---

### Requirement 1.6 — IR Schema: IRParameter Model

**User Story:** As a platform developer, I want graph-level parameters defined in the IR, so that pipelines can be parameterized and reused with different values without modifying the graph structure.

#### Acceptance Criteria

1. THE `IRParameter` model SHALL contain the following required fields:
   - `type`: `str` — parameter type hint (e.g. `"int"`, `"str"`, `"float"`)
   - `default`: `Any` — default value for the parameter
2. THE `IRParameter` model SHALL contain the following optional fields with defaults:
   - `description`: `str` — human-readable description (default: `""`)

---

### Requirement 1.7 — Schema Versioning

**User Story:** As a platform developer, I want the IR to carry a schema version field, so that the loader can detect and reject incompatible IR documents before attempting execution.

#### Acceptance Criteria

1. THE `GraphIR.schema_version` field SHALL be a non-empty string following the format `"<major>.<minor>"` (e.g. `"1.0"`).
2. THE IR_Loader SHALL define a constant `CURRENT_IR_VERSION` equal to the version string of the IR schema implemented in this phase (`"1.0"`).
3. WHEN the IR_Loader deserializes a `GraphIR` document whose `schema_version` major component differs from `CURRENT_IR_VERSION` major component, THE IR_Loader SHALL raise an `IRVersionError` with a message stating the document version, the supported version, and a pointer to the migration utility.
4. WHEN the IR_Loader deserializes a `GraphIR` document whose `schema_version` minor component is greater than `CURRENT_IR_VERSION` minor component, THE IR_Loader SHALL emit a `UserWarning` and continue loading.
5. THE `IRVersionError` SHALL be a subclass of `ValueError` and SHALL be importable from `app.core.ir`.

---

### Requirement 1.8 — IR Serialization: JSON

**User Story:** As a platform developer, I want to serialize and deserialize IR objects to/from JSON, so that graphs can be stored as files, transmitted over HTTP, and inspected by humans.

#### Acceptance Criteria

1. THE IR_Loader SHALL provide a function `load_ir(data: dict) -> GraphIR` that validates and returns a `GraphIR` from a JSON-compatible dict.
2. THE IR_Loader SHALL provide a function `load_ir_from_file(path: str) -> GraphIR` that reads a JSON file and returns a validated `GraphIR`.
3. THE IR_Loader SHALL provide a function `dump_ir(graph: GraphIR) -> dict` that returns a JSON-serializable dict from a `GraphIR`.
4. THE IR_Loader SHALL provide a function `dump_ir_to_file(graph: GraphIR, path: str) -> None` that writes a `GraphIR` to a JSON file with 2-space indentation.
5. WHEN `load_ir_from_file` is called with a path to a file that does not exist, THE IR_Loader SHALL raise a `FileNotFoundError`.
6. WHEN `load_ir_from_file` is called with a path to a file containing invalid JSON, THE IR_Loader SHALL raise a `json.JSONDecodeError`.
7. WHEN `load_ir_from_file` is called with a path to a file containing valid JSON that does not conform to the `GraphIR` schema, THE IR_Loader SHALL raise a `pydantic.ValidationError`.
8. FOR ALL valid `GraphIR` objects `g`, `load_ir(dump_ir(g))` SHALL produce an object equal to `g` (round-trip property).

---

### Requirement 1.9 — IR Validation: Structural Integrity

**User Story:** As a platform developer, I want the IR loader to validate structural integrity of the graph, so that invalid graphs are rejected before reaching the executor.

#### Acceptance Criteria

1. THE IR_Loader SHALL validate that all `IREdge.src_id` and `IREdge.dst_id` values reference node `id` values present in `GraphIR.nodes`.
2. THE IR_Loader SHALL validate that no two `IRNode` entries in `GraphIR.nodes` share the same `id`.
3. WHEN structural validation fails, THE IR_Loader SHALL raise a `pydantic.ValidationError` or `IRValidationError` with a message identifying the specific violation.
4. THE `IRValidationError` SHALL be a subclass of `ValueError` and SHALL be importable from `app.core.ir`.

---

### Requirement 1.10 — Deterministic Replay

**User Story:** As a data scientist, I want the same IR document with the same seed to produce the same execution results, so that experiments are reproducible.

#### Acceptance Criteria

1. THE `IRMetadata.seed` field SHALL be an integer and SHALL be passed to the `DAG_Executor` as the pipeline seed.
2. THE `DAG_Executor` SHALL derive per-node seeds from the graph seed using the existing `stable_hash` function in `app/core/utils/hash.py`, preserving the current determinism contract.
3. WHEN a `GraphIR` is executed twice with the same `seed` and the same node configurations, THE `DAG_Executor` SHALL produce outputs that are equal for all deterministic nodes.
4. THE `GraphIR` SHALL NOT contain any mutable runtime state (timestamps, run IDs, or execution counters) — these belong to `RunManager`.

---

### Requirement 1.11 — Runtime Agnosticism

**User Story:** As a platform architect, I want the IR to be independent of any specific execution runtime, so that the same IR document can be executed by different backends in future phases.

#### Acceptance Criteria

1. THE `GraphIR` model SHALL NOT import or reference any execution runtime classes (`NodeExecutor`, `PipelineGraph`, `run_pipeline`, `RunManager`).
2. THE `GraphIR` model SHALL NOT contain any fields that are specific to the local Python runtime (e.g. Python object references, file handles, or thread locks).
3. THE IR_Schema module (`app/core/ir/`) SHALL have no runtime dependencies beyond `pydantic` and the Python standard library.
