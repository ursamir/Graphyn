# Node System

The node system is the core abstraction of the pipeline engine. Every processing step is a `Node` — a typed, self-describing, Pydantic-validated Python class.

---

## Directory Layout

```
app/core/nodes/
├── __init__.py      ← singleton registry + AutoDiscovery bootstrap
├── base.py          ← Node base class
├── catalogue.py     ← TypeCatalogue
├── compat.py        ← CompatibilityChecker
├── config.py        ← NodeConfig
├── discovery.py     ← AutoDiscovery
├── errors.py        ← exception hierarchy
├── metadata.py      ← NodeMetadata + capability fields
├── observers.py     ← NodeObserver
├── ports.py         ← InputPort, OutputPort, PortDataType
├── registry.py      ← NodeRegistry singleton
└── retry.py         ← RetryPolicy
```

All production node implementations live in `PluginPackage/`. There are no `audio/` or `ml/` subdirectories — those have been removed. Nodes are registered via the plugin system.

---

## `PortDataType` — Base for Data Types

All data types that flow between ports must subclass `PortDataType`:

```python
from app.core.nodes.ports import PortDataType

class PortDataType(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
```

AutoDiscovery registers every `PortDataType` subclass in `TypeCatalogue` automatically. Platform-core types live in `app/models/`. Plugin-domain types live in the plugin's `types.py`.

---

## `InputPort` and `OutputPort`

```python
InputPort(name, data_type, cardinality="single", required=True, description="")
OutputPort(name, data_type, description="")
```

- `cardinality="multi"` — runtime passes a list of values from multiple upstream connections
- `required=False` — runtime passes `None` if unconnected
- `data_type=None` — source node (no input) or sink node (no output)

---

## `NodeConfig`

```python
class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, populate_by_name=True)
```

Every node declares `class Config(NodeConfig)`. Unknown fields raise `ValidationError` immediately.

---

## `NodeMetadata`

```python
class NodeMetadata(BaseModel):
    node_type: str; label: str; description: str; category: str
    version: str = "1.0.0"; tags: list[str] = []
    input_ports: dict = {}; output_ports: dict = {}   # populated by AutoDiscovery

    # Capability fields — machine-readable for MCP/agents/schedulers
    requires_gpu: bool = False
    supports_cpu: bool = True
    supports_edge: bool = False
    deterministic: bool = True       # identical inputs+seed → identical outputs
    cacheable: bool = True
    streaming_support: bool = False  # supports process_stream()
    realtime_support: bool = False
    memory_requirements: str | None = None   # e.g. "512MB"
    dependency_requirements: list[str] = []  # e.g. ["torch>=2.0"]
    batch_support: bool = False
```

All capability fields default to safe values. Nodes that don't declare them get the defaults automatically.

---

## `Node` Base Class

```python
class Node(Generic[InputT, OutputT]):
    node_type: ClassVar[str] = ""
    metadata: ClassVar[NodeMetadata]          # REQUIRED on every subclass
    input_ports: ClassVar[dict[str, InputPort]] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {}
    retry_policy: ClassVar[RetryPolicy | None] = None

    class Config(NodeConfig): pass

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    async def process_stream(self, inputs) -> AsyncGenerator[dict, None]: ...

    # Lifecycle hooks (all no-op by default)
    def setup(self) -> None: ...      # once before first execution
    def on_start(self) -> None: ...   # before each process()
    def on_end(self) -> None: ...     # after successful process()
    def on_error(self, exc) -> None: ...
    def teardown(self) -> None: ...   # once after final execution
```

### SISO Shorthand

Nodes with exactly one `"input"` and one `"output"` port use `def process(self, data)` — the framework unpacks/repacks automatically.

### Lifecycle Order

```
setup()                    ← once
  on_start() → process() → on_end()    ← per execution
  on_error()               ← on failure
teardown()                 ← once
```

---

## `RetryPolicy`

```python
RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0)
# wait = backoff_seconds * backoff_multiplier^attempt_index
```

---

## `NodeRegistry`

```python
from app.core.nodes import registry
# or
from app.core.registry_runtime import get_registry
registry = get_registry()
```

| Method | Description |
|---|---|
| `get_class(node_type)` | Node subclass — raises `NodeNotFoundError` |
| `get_metadata(node_type)` | `NodeMetadata` — raises `NodeNotFoundError` |
| `list_nodes(category=None)` | `list[NodeMetadata]` |
| `find_compatible_nodes(port_type, direction)` | `list[NodeMetadata]` |
| `get_config_schema(node_type)` | JSON Schema dict |
| `unregister(node_type)` | Remove a node type (no-op if not registered) |
| `"node_type" in registry` | `bool` |

---

## `AutoDiscovery`

Runs at import via `app/core/nodes/__init__.py`. Scans:

1. `app/core/nodes/` — framework files only (no node implementations here)
2. `app/models/` — registers `PortDataType` subclasses in `TypeCatalogue`
3. `plugins/` (or `GRAPHYN_PLUGINS_DIR`) — loads all enabled plugins via `PluginLoader`

**Registration rules:**
- `node_type` from `cls.node_type` if set, else PascalCase → snake_case (strips `_node` suffix)
- Class must have `metadata: ClassVar[NodeMetadata]` — missing → warning + skip
- Duplicate `node_type` → `DuplicateNodeTypeError` (server fails to start)
- Import error → warning + skip

---

## `TypeCatalogue`

```python
catalogue = registry.type_catalogue
catalogue.resolve("app.models.audio_sample.AudioSample")  # → AudioSample class
catalogue.list_types()   # sorted FQN strings
```

---

## `CompatibilityChecker`

```python
CompatibilityChecker.are_compatible(output_type, input_type) → bool
CompatibilityChecker.check_connection(src_node, src_port, dst_node, dst_port)  # raises NodeTypeError
```

Rules: `(None, None)` → True; `(X, None)` → False; plain classes → `issubclass`; generics → origins + args.

---

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
```

---

## Data Types

Platform-core types in `app/models/` — always available:

| Type | Key Fields | Produced by |
|---|---|---|
| `DataSample` | `id`, `source`, `metadata` | Base type |
| `AudioSample` | `path`, `sample_rate`, `data` (float32), `label`, `metadata` | `dataset_ingest`, `stream_ingest` |
| `FeatureArray` | `data` (float32 [T,F]), `label`, `sample_rate`, `feature_type`, `metadata` | `feature_frontend` |
| `TensorBatch` | `data` (float32 [N,...]), `labels`, `split`, `source_ids`, `metadata` | Dataset assembly nodes |
| `ModelArtifact` | `model_path`, `labels`, `history`, `metrics` | `trainer`, `evaluator` |
| `TFLiteArtifact` | `tflite_path`, `labels`, `quantisation`, `file_size_bytes` | `edge_optimizer` (TFLite) |
| `PredictionResult` | `source_path`, `predicted_label`, `probabilities`, `metadata` | `realtime_inference`, `audio_classifier` |
| `DeploymentArtifact` | `artifact_path`, `model_format`, `target_hardware`, `quantization`, `labels`, `metadata` | `deployment_packager`, `edge_optimizer` |

Plugin-owned types — registered only when the owning plugin is installed:

| Type | Plugin | Key Fields |
|---|---|---|
| `DatasetArtifact` | `Common/dataset_builder` | `X_train/val/test`, `y_train/val/test`, `labels`, `input_shape`, `n_classes`, `version`, `hash` |
| `EmbeddingVector` | `Common/embedding_generator` | `embedding` (float32 [D]), `source_path`, `label`, `embedding_model`, `pooling` |
| `ExperimentArtifact` | `Common/experiment_tracker` | `run_id`, `experiment_name`, `parameters`, `metrics`, `artifact_paths`, `backend` |
