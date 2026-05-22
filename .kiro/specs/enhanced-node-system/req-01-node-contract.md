# R1 · R2 · R9 — Node Contract: Configuration, Multi-Port Typed I/O, Domain Support

← [Back to master requirements](requirements.md)

---

## Requirement 1: Pydantic-Based Node Configuration

**User Story:** As a pipeline author, I want each node's configuration to be a typed Pydantic model, so that invalid configs are caught before execution and I get clear error messages.

### Acceptance Criteria

1. Each `Node` subclass SHALL declare a class-level `Config` attribute that is a `NodeConfig` subclass (`pydantic.BaseModel`). `Node.__init__` SHALL accept a single `config` parameter whose value MUST be an instance of that `Config` class.
2. WHEN a raw `dict` is passed as the `config` argument to `Node.__init__`, `Node.__init__` SHALL coerce it by calling `self.Config.model_validate(dict)` and SHALL raise `pydantic.ValidationError` on failure.
3. `self.config` SHALL be typed as the concrete `Config` subclass declared by that node, not as the base `NodeConfig`.
4. WHEN a `NodeConfig` is instantiated with invalid field values, it SHALL raise `pydantic.ValidationError` with field-level error details.
5. `NodeConfig` SHALL support lossless serialisation via `model_dump(mode="json")` and deserialisation via `model_validate_json(json_str)`.
6. Optional fields in a `NodeConfig` subclass SHALL declare a default value at the class level. Fields without a default are required; callers that omit a required field SHALL receive a `pydantic.ValidationError`.

---

## Requirement 2: Multi-Port Typed I/O

**User Story:** As a pipeline builder, I want nodes to declare named, typed input and output ports — including multiple ports of different types — so that the system can verify compatibility for any topology (single-input, multi-input, multi-output, fan-in, fan-out) at build time.

### Acceptance Criteria

#### 2A — Port Declaration

1. THE `Node` SHALL declare class-level attributes `input_ports: dict[str, InputPort]` and `output_ports: dict[str, OutputPort]`. Each key is the port name (a non-empty string); each value is an `InputPort` or `OutputPort` instance.
2. `InputPort` SHALL be a Pydantic model with fields:
   - `name: str` — matches the dict key; non-empty.
   - `data_type: type | None` — the PortType this port accepts. `None` means the port accepts no data (source node).
   - `cardinality: Literal["single", "multi"]` — `"single"` means exactly one upstream connection; `"multi"` means one or more upstream connections, and the port receives a `list` of values.
   - `required: bool` — defaults to `True`. Optional ports (`required=False`) do not need to be connected.
   - `description: str` — defaults to `""`.
3. `OutputPort` SHALL be a Pydantic model with fields:
   - `name: str` — matches the dict key; non-empty.
   - `data_type: type | None` — the PortType this port produces. `None` means the port produces no data (sink node).
   - `description: str` — defaults to `""`.
4. `data_type` on any port MUST be one of: a concrete Python built-in type (`int`, `str`, `float`, `bool`, `bytes`), a generic alias (`list[X]`, `dict[K, V]`, `tuple[X, ...]`), a `pydantic.BaseModel` subclass, or `None`. No other values are permitted.
5. A `Node` subclass MAY declare zero input ports (source node) or zero output ports (sink node).

#### 2B — SISO Convenience Shorthand

6. A `Node` subclass that declares exactly one input port named `"input"` and exactly one output port named `"output"` is a SISO node. SISO nodes MAY override `process(self, data: InputT) -> OutputT` instead of `process(self, inputs: dict[str, Any]) -> dict[str, Any]`. The runtime SHALL automatically wrap the SISO `process` signature into the multi-port calling convention.
7. THE `Node` base class SHALL expose class-level properties `input_type: type | None` and `output_type: type | None` as convenience accessors that return `input_ports["input"].data_type` and `output_ports["output"].data_type` respectively for SISO nodes, and raise `AttributeError` for non-SISO nodes.

#### 2C — Process Signature

8. The canonical `process` signature for multi-port nodes is `process(self, inputs: dict[str, Any]) -> dict[str, Any]`, where each key is a port name and each value is the data received on that port. For `"multi"` cardinality input ports, the value is a `list` of items (one per upstream connection).
9. The return value of `process` MUST be a `dict` whose keys are a subset of the node's declared output port names. Output ports not present in the return dict are treated as producing `None`.

#### 2D — Compatibility Checking

10. THE `CompatibilityChecker` SHALL expose `are_compatible(output_type: type | None, input_type: type | None) -> bool` with the following rules:
    - `are_compatible(None, None)` → `True`
    - `are_compatible(X, None)` → `False` for any non-`None` `X`
    - `are_compatible(None, X)` → `False` for any non-`None` `X`
    - Both plain classes: `True` if `issubclass(output_type, input_type)`
    - Either is a generic alias: `True` if `get_origin(A) is get_origin(B)` AND each pair of corresponding `get_args` elements is compatible by recursive `are_compatible`
11. THE `CompatibilityChecker` SHALL expose `check_connection(src_node: Node, src_port: str, dst_node: Node, dst_port: str) -> None` that raises `NodeTypeError` if the output port's `data_type` is not compatible with the input port's `data_type`, or if either port name does not exist on the respective node.
12. WHEN a `"multi"` cardinality input port receives connections from N upstream output ports, `check_connection` SHALL be called once per upstream connection; all N output types must be compatible with the input port's `data_type`.
13. Type identity SHALL be determined by Python object identity of the class (not by name string). Two classes with the same name from different modules are always distinct; `issubclass` on the actual class objects enforces this.

#### 2E — Schema Introspection

14. THE `Node` SHALL expose `port_schemas() -> dict` as a `@classmethod` that returns a dict with keys `"inputs"` and `"outputs"`, each mapping port names to their JSON Schema (via `model_json_schema()` when `data_type` is a Pydantic model, or a minimal `{"type": "<python_type_name>"}` for built-ins, or `null` for `None`).

---

## Requirement 9: Universal Domain Support

**User Story:** As a developer building non-audio pipelines, I want the Node base class to be domain-agnostic, so that I can use the same infrastructure for ML, data transformation, work automation, and other workflows.

### Acceptance Criteria

1. THE `Node` base class SHALL NOT import or reference any audio-specific types (`AudioSample`, `librosa`, `soundfile`, etc.).
2. THE `Node` base class SHALL be defined as `class Node(Generic[InputT, OutputT])` where `InputT` and `OutputT` are `TypeVar`s bound to `Any`, so that concrete subclasses can narrow the types.
3. WHEN a node declares zero input ports, `CompatibilityChecker` SHALL treat it as a source node. No upstream connection is required or permitted.
4. WHEN a node declares zero output ports, `CompatibilityChecker` SHALL treat it as a sink node. No downstream connection is required or permitted.
5. THE `NodeRegistry` SHALL support nodes from multiple domains coexisting under distinct `category` values (e.g. `"Audio"`, `"ML"`, `"Data"`, `"Automation"`, `"Video"`).
6. A node MAY declare ports with `required=False` to represent optional data paths (e.g. an optional side-channel input). The pipeline runtime SHALL pass `None` for unconnected optional input ports.
