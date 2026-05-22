# Design Document — Enhanced Node System

← [Back to requirements](requirements.md)

---

## Sub-Documents

| Sub-document | Topics |
|---|---|
| [design-01-node-contract.md](design-01-node-contract.md) | Node base class · NodeConfig · InputPort / OutputPort · SISO wrapper · CompatibilityChecker · AudioSample migration |
| [design-02-registration.md](design-02-registration.md) | AutoDiscovery · NodeRegistry singleton · NodeMetadata · TypeCatalogue |
| [design-03-runtime.md](design-03-runtime.md) | Lifecycle hooks · RetryPolicy · Streaming (AsyncGenerator) · NodeObserver |
| [design-04-serialisation.md](design-04-serialisation.md) | Round-trip serialisation · Config schema export · Pipeline DAG executor migration |

---

## Overview

The Enhanced Node System replaces the current hand-written `NODE_REGISTRY` dict and minimal `Node` base class with a fully typed, auto-discovering, Pydantic-v2-native node infrastructure. The redesign has five goals:

1. **Type safety at build time** — every port carries a real Python type; `CompatibilityChecker` uses `issubclass` / `get_origin` / `get_args` instead of string comparison.
2. **Zero-boilerplate registration** — dropping a `.py` file into `app/core/nodes/` (or the configured plugins directory) is sufficient; `AutoDiscovery` handles the rest.
3. **Domain agnosticism** — the `Node` base class has no audio imports; `AudioSample` becomes a `PortDataType` subclass registered like any other type.
4. **Rich runtime capabilities** — lifecycle hooks, retry with exponential back-off, streaming via `AsyncGenerator`, and structured observability are first-class features of the base class.
5. **Full serialisability** — every node's config schema and port definitions are exportable as JSON Schema via Pydantic v2's `model_json_schema()`.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  app/core/nodes/                                                     │
│                                                                      │
│  __init__.py  ──► AutoDiscovery.run()  ──► NodeRegistry (singleton) │
│                        │                        │                    │
│                        │ scans                  │ stores             │
│                        ▼                        ▼                    │
│              *.py node files            NodeMetadata[]               │
│              plugins/ dir               TypeCatalogue                │
│                        │                                             │
│                        │ registers                                   │
│                        ▼                                             │
│              Node subclasses  ◄──── NodeConfig (Pydantic)           │
│              PortDataType subclasses                                 │
│                                                                      │
│  base.py          ports.py         config.py       errors.py        │
│  registry.py      discovery.py     metadata.py     observers.py     │
│  catalogue.py     compat.py        retry.py                         │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ used by
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  app/core/pipeline.py  (DAG executor)                               │
│                                                                      │
│  PipelineGraph  ──► topological sort  ──► NodeExecutor              │
│       │                                        │                    │
│       │ edges = (src_node, src_port,            │ calls              │
│       │          dst_node, dst_port)            ▼                   │
│       │                              setup → on_start → process     │
│       │                                    → on_end → teardown      │
│       │                              (with retry + observer hooks)  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## File Layout After Redesign

```
app/core/nodes/
├── __init__.py          # AutoDiscovery.run(); exports NodeRegistry singleton
├── base.py              # Node[InputT, OutputT] base class
├── ports.py             # InputPort, OutputPort, PortDataType
├── config.py            # NodeConfig base (pydantic.BaseModel)
├── metadata.py          # NodeMetadata (pydantic.BaseModel)
├── registry.py          # NodeRegistry singleton class
├── catalogue.py         # TypeCatalogue
├── discovery.py         # AutoDiscovery
├── compat.py            # CompatibilityChecker
├── retry.py             # RetryPolicy
├── observers.py         # NodeObserver ABC, LoggingObserver, CompositeObserver
├── errors.py            # All custom exceptions
│
│   ── audio nodes (migrated, SISO shorthand) ──
├── input.py             # InputNode
├── mic_input.py         # MicInputNode
├── clean.py             # CleanNode, TrimNode, ResampleNode, …
├── augment.py           # AugmentNode, PitchShiftNode, …
├── process.py           # FilterNode, FadeNode, DenoiseNode
├── compose.py           # ConcatenateNode, TagNode, DuplicateNode
├── compress.py          # CompressionNode, VADNode, PaddingNode, SilenceDetectorNode
├── segment.py           # SegmentNode
├── spectrogram.py       # SpectrogramNode
├── split.py             # SplitNode
├── stratified_split.py  # StratifiedSplitNode
├── export.py            # ExportNode
├── hf_export.py         # HFExportNode
├── tfrecord_export.py   # TFRecordExportNode
└── noise_mix.py         # NoiseMixNode

app/models/
└── audio_sample.py      # AudioSample(PortDataType) — Pydantic BaseModel

app/core/
├── pipeline.py          # DAG-based PipelineGraph + NodeExecutor (replaces linear list)
└── validation.py        # Updated: uses CompatibilityChecker, removes string checks
```

---

## Key Design Decisions

### 1. `PortDataType` as the registration hook

Rather than requiring node authors to call a registration function, any class that subclasses `PortDataType` is automatically picked up by `AutoDiscovery` and entered into `TypeCatalogue`. `PortDataType` itself is a thin `pydantic.BaseModel` subclass with `model_config = ConfigDict(arbitrary_types_allowed=True)` so that numpy arrays and other non-Pydantic fields can be carried as port data.

### 2. SISO wrapper via `__init_subclass__`

When a `Node` subclass is defined with exactly one input port named `"input"` and one output port named `"output"`, `Node.__init_subclass__` wraps the subclass's `process` method at class-creation time. The wrapper unpacks `inputs["input"]`, calls the original `process(self, data)`, and re-packs the result as `{"output": result}`. This means SISO nodes never need to change their `process` signature.

### 3. DAG execution in `pipeline.py`

The current linear list executor is replaced by `PipelineGraph`, which stores edges as `(src_node_id, src_port, dst_node_id, dst_port)` tuples. Execution order is determined by Kahn's topological sort. Each node's `inputs` dict is assembled from the outputs of its upstream nodes before `process` is called.

### 4. `AudioSample` migration

`AudioSample` becomes a `pydantic.BaseModel` subclass of `PortDataType`. The `numpy.ndarray` field uses `Annotated` with a custom `BeforeValidator` that accepts `None` and converts it to an empty array, plus `arbitrary_types_allowed=True` in the model config. All existing audio nodes continue to receive and return `list[AudioSample]` — only the class definition changes.

### 5. Pydantic v2 throughout

All models use `model_validate()` (not `parse_obj()`), `model_dump(mode="json")` (not `.dict()`), and `model_json_schema()` (not `.schema()`). Port types that are not Pydantic models are represented in JSON Schema as `{"type": "<python_type_name>"}` or `null`.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

See [design-04-serialisation.md § Correctness Properties](design-04-serialisation.md#correctness-properties) for the full list. A summary:

| # | Property | Validates |
|---|---|---|
| 1 | `are_compatible(A, B)` implies `issubclass(A, B)` for plain classes | R2.10 |
| 2 | `are_compatible` is reflexive: `are_compatible(T, T)` is always `True` for non-`None` T | R2.10 |
| 3 | TypeCatalogue round-trip: `resolve(fqn(T)) is T` | R13A.3 |
| 4 | Registry completeness: every discovered class is retrievable | R3.2, R4.4 |
| 5 | SISO wrapper equivalence: `siso_node.process({"input": x})["output"] == siso_node._raw_process(x)` | R2B.6 |
| 6 | Retry backoff formula: wait before attempt `i` equals `backoff_seconds * backoff_multiplier ** i` | R6.3 |
| 7 | NodeMetadata round-trip: `NodeMetadata.model_validate(m.model_dump(mode="json")) == m` | R11.2 |
| 8 | Config schema idempotence: `get_config_schema(t) == get_config_schema(t)` | R12.3 |

---

## Error Taxonomy

All custom exceptions live in `app/core/nodes/errors.py`:

```python
class NodeSystemError(Exception): ...          # base

class NodeNotFoundError(NodeSystemError): ...
class DuplicateNodeTypeError(NodeSystemError): ...
class NodeMetadataError(NodeSystemError): ...
class NodeTypeError(NodeSystemError): ...       # port compatibility failure
class PortTypeNotFoundError(NodeSystemError): ...
class DuplicatePortTypeError(NodeSystemError): ...
class PipelineGraphError(NodeSystemError): ...  # cycle, missing port, etc.
```

---

## Migration Strategy for Existing Nodes

All existing audio nodes are SISO. Migration steps per node:

1. Add `node_type: ClassVar[str]` (or rely on auto-derived name).
2. Add `metadata: ClassVar[NodeMetadata]` with `label`, `description`, `category`.
3. Add `input_ports` and `output_ports` class attributes using `InputPort` / `OutputPort` with `data_type=list[AudioSample]` (or `None` for source/sink).
4. Replace `REQUIRED_CONFIG = [...]` with a concrete `Config(NodeConfig)` Pydantic model.
5. Change `__init__(self, config: dict, seed: int)` to `__init__(self, config: Config | dict, seed: int)`.
6. Keep `process(self, data)` unchanged — the SISO wrapper handles the multi-port convention automatically.

The old `registry.py` is deleted. `registry_runtime.py` is updated to import the `NodeRegistry` singleton from `app.core.nodes`.

Full migration details and per-node `Config` class definitions are in [design-01-node-contract.md](design-01-node-contract.md).
