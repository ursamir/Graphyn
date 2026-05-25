---
inclusion: fileMatch
fileMatchPattern: "app/core/nodes/base.py,app/core/nodes/ports.py,app/core/nodes/config.py,app/core/nodes/retry.py,app/core/nodes/observers.py,app/core/nodes/metadata.py"
---

# Node Base — Core Abstractions

## `Node` Base Class (`base.py`)

```python
class Node(Generic[InputT, OutputT]):
    node_type: ClassVar[str] = ""
    metadata: ClassVar[NodeMetadata]          # REQUIRED
    input_ports: ClassVar[dict[str, InputPort]] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {}
    retry_policy: ClassVar[RetryPolicy | None] = None

    class Config(NodeConfig): pass

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    async def process_stream(self, inputs) -> AsyncGenerator[dict, None]: ...  # uses get_running_loop(); CPU-bound nodes should override and use ProcessPoolExecutor (SA-B3)

    # Lifecycle hooks — base implementations fire observer events when set
    def setup(self) -> None: ...      # once before first execution
    def on_start(self) -> None: ...   # before each process(); calls observer.on_node_start()
    def on_end(self) -> None: ...     # after successful process(); calls observer.on_node_end()
    def on_error(self, exc) -> None: ...  # calls observer.on_node_error(); observer errors are swallowed
    def teardown(self) -> None: ...   # once after final execution
```

**SISO shorthand:** nodes with exactly one `"input"` and one `"output"` port use `def process(self, data)` — the framework unpacks/repacks automatically.

## `NodeMetadata` (`metadata.py`)

```python
class NodeMetadata(BaseModel):
    node_type: str; label: str; description: str; category: str
    version: str = "1.0.0"; tags: list[str] = []

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

All capability fields default to safe values — nodes without them get defaults automatically.

## `InputPort` / `OutputPort` (`ports.py`)

```python
InputPort(name, data_type, cardinality="single", required=True, description="")
OutputPort(name, data_type, description="")
```

- `cardinality="multi"` → runtime passes a list
- `required=False` → runtime passes `None` if unconnected
- `data_type=None` → source node (no input) or sink node (no output)

## `NodeConfig` (`config.py`)

```python
class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, populate_by_name=True)
```

Every node declares `class Config(NodeConfig)`. Unknown fields raise `ValidationError`.

**Always add validators for constrained fields.** Example pattern:

```python
import pydantic

class Config(NodeConfig):
    overlap: float = 0.0   # [0, 1)
    mode: str = "fixed"

    @pydantic.field_validator("overlap")
    @classmethod
    def _overlap_range(cls, v: float) -> float:
        if not (0.0 <= v < 1.0):
            raise ValueError(f"overlap must be in [0, 1), got {v}")
        return v

    @pydantic.model_validator(mode="after")
    def _cross_field_check(self) -> "MyNode.Config":
        if self.min_ms >= self.max_ms:
            raise ValueError("min_ms must be < max_ms")
        return self
```

Validation fires at node construction (`Node.__init__` calls `Config.model_validate(config)`), not at `process()` time.

## `RetryPolicy` (`retry.py`)

```python
RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0)
# wait = backoff_seconds * backoff_multiplier^attempt_index
```

## Minimal Node Template

For plugin nodes use the full template in `plugin-development.md` — it includes all capability flags and the backend config pattern.

```python
from typing import ClassVar
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

class MyNode(Node):
    node_type: ClassVar[str] = "my_node"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="my_node", label="My Node",
        description="What it does.", category="Processing",
    )
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        param: float = 1.0

    def process(self, samples):   # SISO shorthand
        return [transform(s) for s in samples]
```

## Open Issues in This Area

> All previously listed issues in this area have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.
