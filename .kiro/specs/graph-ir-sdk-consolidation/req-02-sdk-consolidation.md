# req-02 — SDK Consolidation

## Introduction

This document defines requirements for rewriting the SDK internals (`Pipeline` and `PipelineNode` in `app/core/sdk.py`) to be backed by the Graph IR, while keeping the public API identical so that existing user code requires no changes.

The public method signatures of `Pipeline` and `PipelineNode` are a compatibility contract. They must not change. Only the internals change.

---

## Glossary

See [requirements.md](requirements.md) for the full glossary. Terms used here:

- **SDK**, **Pipeline**, **PipelineNode**, **IR**, **IR_Schema**, **IR_Loader**, **YAML_Shim**, **DAG_Executor**

---

## Requirements

### Requirement 2.1 — PipelineNode: Public API Preserved

**User Story:** As a Python developer, I want `PipelineNode` to keep its existing constructor signature, so that my existing SDK code continues to work without modification.

#### Acceptance Criteria

1. THE `PipelineNode` class SHALL retain the constructor signature `__init__(self, node_type: str, config: dict[str, Any] | None = None)`.
2. THE `PipelineNode.node_type` attribute SHALL remain a `str` accessible after construction.
3. THE `PipelineNode.config` attribute SHALL remain a `dict` accessible after construction.
4. THE `PipelineNode.to_dict()` method SHALL remain and SHALL return `{"type": self.node_type, "config": self.config}`.
5. THE `PipelineNode` constructor SHALL continue to validate `config` against the node's Pydantic `Config` model via the registry, raising `ValueError` for invalid configs.

---

### Requirement 2.2 — PipelineNode: IR Backing

**User Story:** As a platform developer, I want `PipelineNode` to internally hold an `IRNode` object, so that the SDK natively produces IR objects rather than raw dicts.

#### Acceptance Criteria

1. THE `PipelineNode` class SHALL internally construct and hold an `IRNode` object after successful validation.
2. THE `PipelineNode` SHALL expose a `to_ir_node(node_index: int) -> IRNode` method that returns the backing `IRNode`, using `f"{self.node_type}_{node_index}"` as the node `id` when no explicit id is set.
3. WHEN `PipelineNode.to_dict()` is called, THE `PipelineNode` SHALL derive its return value from the backing `IRNode` fields, not from a separate raw dict.

---

### Requirement 2.3 — Pipeline: Public API Preserved

**User Story:** As a Python developer, I want `Pipeline` to keep its existing constructor and method signatures, so that my existing SDK code continues to work without modification.

#### Acceptance Criteria

1. THE `Pipeline` class SHALL retain the constructor signature `__init__(self, nodes: list[PipelineNode], seed: int = 42)`.
2. THE `Pipeline.nodes` attribute SHALL remain a `list[PipelineNode]` accessible after construction.
3. THE `Pipeline.seed` attribute SHALL remain an `int` accessible after construction.
4. THE `Pipeline.run()` method SHALL remain and SHALL execute the pipeline, returning the outputs of the final node.
5. THE `Pipeline.from_yaml(path: str)` class method SHALL remain (as a shim — see req-04).
6. THE `Pipeline.to_yaml(path: str)` method SHALL remain and SHALL serialize the pipeline to a YAML file.

---

### Requirement 2.4 — Pipeline: IR-Backed Internals

**User Story:** As a platform developer, I want `Pipeline` to internally hold a `GraphIR` object, so that the SDK is the canonical producer of IR graphs.

#### Acceptance Criteria

1. THE `Pipeline` class SHALL internally construct and hold a `GraphIR` object after construction.
2. THE `Pipeline` SHALL expose a `to_ir() -> GraphIR` method that returns the backing `GraphIR` object.
3. WHEN `Pipeline.run()` is called, THE `Pipeline` SHALL pass the `GraphIR` object to the `DAG_Executor` (not a YAML string or raw dict).
4. THE `GraphIR` produced by `Pipeline.to_ir()` SHALL have `schema_version` set to `CURRENT_IR_VERSION`.
5. THE `GraphIR` produced by `Pipeline.to_ir()` SHALL have `IRMetadata.seed` equal to `Pipeline.seed`.
6. THE `GraphIR` produced by `Pipeline.to_ir()` SHALL have `IRMetadata.name` set to a default value of `"pipeline"` when no explicit name is provided.

---

### Requirement 2.5 — Pipeline: Canonical JSON Loader

**User Story:** As a Python developer, I want to load a pipeline from an IR JSON file, so that I can use the canonical format without going through YAML.

#### Acceptance Criteria

1. THE `Pipeline` class SHALL expose a class method `from_json(path: str) -> Pipeline` that loads a `GraphIR` from a JSON file and constructs a `Pipeline` from it.
2. WHEN `Pipeline.from_json(path)` is called, THE `Pipeline` SHALL use `IR_Loader.load_ir_from_file(path)` to load and validate the IR.
3. WHEN `Pipeline.from_json(path)` is called with a path to a file containing an incompatible schema version, THE `Pipeline` SHALL propagate the `IRVersionError` to the caller without wrapping it.
4. THE `Pipeline` constructed by `from_json` SHALL have `nodes` and `seed` attributes consistent with the loaded `GraphIR`.

---

### Requirement 2.6 — Pipeline: JSON Serialization

**User Story:** As a Python developer, I want to serialize a pipeline to an IR JSON file, so that I can persist and share pipelines in the canonical format.

#### Acceptance Criteria

1. THE `Pipeline` class SHALL expose a method `to_json(path: str) -> None` that writes the backing `GraphIR` to a JSON file.
2. WHEN `Pipeline.to_json(path)` is called, THE `Pipeline` SHALL use `IR_Loader.dump_ir_to_file(self.to_ir(), path)`.
3. WHEN `Pipeline.to_json(path)` is called and then `Pipeline.from_json(path)` is called on the resulting file, THE resulting `Pipeline` SHALL have nodes and seed equal to the original (round-trip property).

---

### Requirement 2.7 — Pipeline: YAML Serialization Preserved

**User Story:** As a Python developer, I want `Pipeline.to_yaml()` to continue working, so that I can still produce YAML output for tools that consume it.

#### Acceptance Criteria

1. THE `Pipeline.to_yaml(path: str)` method SHALL remain functional and SHALL serialize the pipeline to a YAML file in the existing pipeline YAML format.
2. THE `Pipeline.to_yaml()` implementation SHALL derive the YAML content from the backing `GraphIR` (not from a separate raw dict).
3. WHEN `Pipeline.to_yaml(path)` is called, THE `Pipeline` SHALL NOT emit a `DeprecationWarning` (writing YAML is not deprecated; only loading YAML is deprecated).

---

### Requirement 2.8 — Pipeline: Named Graph Support

**User Story:** As a Python developer, I want to give my pipeline a name and description, so that IR documents are self-describing.

#### Acceptance Criteria

1. THE `Pipeline` constructor SHALL accept optional keyword arguments `name: str = "pipeline"` and `description: str = ""`.
2. THE `Pipeline.to_ir()` method SHALL populate `IRMetadata.name` and `IRMetadata.description` from these constructor arguments.
3. WHEN `Pipeline.from_json(path)` loads a `GraphIR` with a non-empty `IRMetadata.name`, THE resulting `Pipeline` SHALL expose that name via a `name` attribute.

---

### Requirement 2.9 — SDK as Single Source of Truth

**User Story:** As a platform architect, I want all interfaces to delegate to the SDK, so that business logic is not duplicated across CLI, REST API, and other entry points.

#### Acceptance Criteria

1. THE CLI `run` command SHALL construct a `Pipeline` object and call `Pipeline.run()` rather than calling `run_pipeline()` directly with a file path.
2. THE REST_API pipeline execution endpoint SHALL construct a `Pipeline` object (or accept a `GraphIR` and pass it to the executor) rather than calling `run_pipeline()` directly with a file path.
3. THE `Pipeline.run()` method SHALL be the single code path through which all interfaces trigger pipeline execution.
4. WHEN `Pipeline.run()` is called, THE `Pipeline` SHALL pass the `GraphIR` to the `DAG_Executor` via a new `run_pipeline_ir(graph: GraphIR, ...)` function, not via a temporary YAML file.
