# Design 03 — Runtime: Lifecycle, Retry, Streaming, Observability

← [Back to design.md](design.md) | ← [Back to requirements](req-03-runtime.md)

---

## 1. `RetryPolicy`

```python
# app/core/nodes/retry.py
from __future__ import annotations

from pydantic import BaseModel, field_validator


class RetryPolicy(BaseModel):
    """Exponential back-off retry configuration for a node.

    Wait before attempt i (0-indexed, where i=0 is the first retry):
        wait_i = backoff_seconds * (backoff_multiplier ** i)

    Examples (backoff_seconds=1.0, backoff_multiplier=2.0):
        Before 2nd attempt (i=0): 1.0 * 2.0^0 = 1.0 s
        Before 3rd attempt (i=1): 1.0 * 2.0^1 = 2.0 s
        Before 4th attempt (i=2): 1.0 * 2.0^2 = 4.0 s
    """

    max_attempts: int = 1
    backoff_seconds: float = 0.0
    backoff_multiplier: float = 1.0

    @field_validator("max_attempts")
    @classmethod
    def _min_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_attempts must be >= 1")
        return v

    @field_validator("backoff_seconds")
    @classmethod
    def _non_negative_backoff(cls, v: float) -> float:
        if v < 0:
            raise ValueError("backoff_seconds must be >= 0")
        return v

    @field_validator("backoff_multiplier")
    @classmethod
    def _min_multiplier(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")
        return v

    def wait_before_attempt(self, attempt_index: int) -> float:
        """Return the wait time in seconds before retry attempt_index (0-indexed).

        attempt_index=0 → wait before the 2nd overall attempt (first retry).
        """
        return self.backoff_seconds * (self.backoff_multiplier ** attempt_index)
```

---

## 2. `NodeObserver` and Implementations

```python
# app/core/nodes/observers.py
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any


class NodeObserver(ABC):
    """Abstract interface for node execution event callbacks."""

    @abstractmethod
    def on_node_start(self, node_type: str, run_id: str) -> None:
        """Called immediately before process() is invoked."""

    @abstractmethod
    def on_node_end(
        self,
        node_type: str,
        run_id: str,
        duration_s: float,
        input_counts: dict[str, int],
        output_counts: dict[str, int],
    ) -> None:
        """Called after process() returns successfully."""

    @abstractmethod
    def on_node_error(
        self,
        node_type: str,
        run_id: str,
        exc: Exception,
    ) -> None:
        """Called when process() raises an exception."""


class LoggingObserver(NodeObserver):
    """Writes one structured JSON line per event to a Python logger."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("node_observer")

    def on_node_start(self, node_type: str, run_id: str) -> None:
        self._log.info(json.dumps({
            "event": "node_start",
            "node_type": node_type,
            "run_id": run_id,
        }))

    def on_node_end(
        self,
        node_type: str,
        run_id: str,
        duration_s: float,
        input_counts: dict[str, int],
        output_counts: dict[str, int],
    ) -> None:
        self._log.info(json.dumps({
            "event": "node_end",
            "node_type": node_type,
            "run_id": run_id,
            "duration_s": duration_s,
            "input_counts": input_counts,
            "output_counts": output_counts,
        }))

    def on_node_error(self, node_type: str, run_id: str, exc: Exception) -> None:
        self._log.error(json.dumps({
            "event": "node_error",
            "node_type": node_type,
            "run_id": run_id,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }))


class CompositeObserver(NodeObserver):
    """Fans out all events to a list of child NodeObserver instances."""

    def __init__(self, observers: list[NodeObserver]) -> None:
        self._observers = list(observers)

    def on_node_start(self, node_type: str, run_id: str) -> None:
        for obs in self._observers:
            obs.on_node_start(node_type, run_id)

    def on_node_end(
        self,
        node_type: str,
        run_id: str,
        duration_s: float,
        input_counts: dict[str, int],
        output_counts: dict[str, int],
    ) -> None:
        for obs in self._observers:
            obs.on_node_end(node_type, run_id, duration_s, input_counts, output_counts)

    def on_node_error(self, node_type: str, run_id: str, exc: Exception) -> None:
        for obs in self._observers:
            obs.on_node_error(node_type, run_id, exc)
```

---

## 3. `NodeExecutor` — Lifecycle + Retry + Observability

The `NodeExecutor` is the runtime component that drives a single node through its full lifecycle. It is called by `PipelineGraph` (see design-04) for each node in topological order.

```python
# app/core/pipeline.py  (NodeExecutor section)
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

from app.core.nodes.base import Node
from app.core.nodes.observers import NodeObserver
from app.core.nodes.retry import RetryPolicy

log = logging.getLogger(__name__)


def _count_port_items(port_data: Any) -> int:
    """Return the number of items on a port (1 for single, N for list)."""
    if isinstance(port_data, list):
        return len(port_data)
    if port_data is None:
        return 0
    return 1


class NodeExecutor:
    """Drives a single node through setup → (on_start → process → on_end)* → teardown.

    Handles:
      - Lifecycle hook sequencing
      - Retry with exponential back-off
      - Observer event emission
      - Streaming vs. batch execution
    """

    def __init__(self, node: Node, run_id: str = "") -> None:
        self._node = node
        self._run_id = run_id
        self._setup_done = False

    def setup(self) -> None:
        """Call node.setup() once before first execution."""
        if not self._setup_done:
            self._node.setup()
            self._setup_done = True

    def teardown(self) -> None:
        """Call node.teardown() once after final execution."""
        self._node.teardown()

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the node synchronously with full lifecycle + retry.

        Returns the outputs dict from node.process(inputs).
        """
        node = self._node
        policy: RetryPolicy | None = node.retry_policy
        max_attempts = policy.max_attempts if policy else 1
        observer: NodeObserver | None = node.observer
        node_type = type(node).__name__

        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            # Wait before retry (not before first attempt)
            if attempt > 0 and policy:
                wait = policy.wait_before_attempt(attempt - 1)
                if wait > 0:
                    time.sleep(wait)

            # on_start
            try:
                node.on_start()
                if observer:
                    observer.on_node_start(node_type, self._run_id)
            except Exception as exc:
                node.on_error(exc)
                if observer:
                    observer.on_node_error(node_type, self._run_id, exc)
                last_exc = exc
                continue  # retry

            # process
            t0 = time.perf_counter()
            try:
                outputs = node.process(inputs)
            except Exception as exc:
                node.on_error(exc)
                if observer:
                    observer.on_node_error(node_type, self._run_id, exc)
                last_exc = exc
                continue  # retry

            duration = time.perf_counter() - t0

            # on_end
            node.on_end()
            input_counts = {k: _count_port_items(v) for k, v in inputs.items()}
            output_counts = {k: _count_port_items(v) for k, v in outputs.items()}
            if observer:
                observer.on_node_end(
                    node_type, self._run_id, duration, input_counts, output_counts
                )

            if attempt > 0:
                log.info(
                    "Node '%s' succeeded after %d attempt(s).",
                    node_type,
                    attempt + 1,
                )

            return outputs

        # All attempts exhausted
        assert last_exc is not None
        node.on_error(last_exc)
        if observer:
            observer.on_node_error(node_type, self._run_id, last_exc)
        self.teardown()
        raise last_exc

    async def execute_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute the node in streaming mode.

        If the node overrides process_stream, calls it directly.
        Otherwise wraps process() as a single-item async generator.
        """
        node = self._node
        node.on_start()
        try:
            async for item in node.process_stream(inputs):
                yield item
        except Exception as exc:
            node.on_error(exc)
            raise
        node.on_end()
```

---

## 4. Lifecycle Sequence Diagrams

### Batch execution (no retry)

```
PipelineGraph          NodeExecutor           Node
     │                      │                  │
     │── executor.setup() ──►│── node.setup() ──►│
     │                      │                  │
     │── executor.execute(inputs) ─────────────►│
     │                      │── on_start() ────►│
     │                      │── process(inputs)─►│
     │                      │◄─ outputs ─────────│
     │                      │── on_end() ───────►│
     │◄─ outputs ───────────│                  │
     │                      │                  │
     │── executor.teardown()─►│── teardown() ───►│
```

### Batch execution (with retry, 2nd attempt succeeds)

```
NodeExecutor                    Node
     │                           │
     │── on_start() ────────────►│
     │── process(inputs) ───────►│ ← raises TransientError
     │── on_error(exc) ─────────►│
     │                           │
     │   [sleep backoff_seconds * backoff_multiplier^0]
     │                           │
     │── on_start() ────────────►│  (retry)
     │── process(inputs) ───────►│ ← succeeds
     │── on_end() ──────────────►│
     │   log.info("succeeded after 2 attempts")
```

### Streaming execution (two connected streaming nodes)

```
PipelineGraph
     │
     │  async for item in node_A.process_stream(inputs_A):
     │      async for out in node_B.process_stream({"input": item}):
     │          yield out
     │
     │  (items flow one-at-a-time; no full-list materialisation)
```

---

## 5. Streaming Node Example

```python
# Example: a streaming node that yields one AudioSample at a time
from __future__ import annotations

from typing import Any, AsyncGenerator, ClassVar
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample


class StreamingCleanNode(Node):
    """Streaming variant of CleanNode — yields one sample at a time."""

    node_type: ClassVar[str] = "streaming_clean"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="streaming_clean",
        label="Streaming Clean",
        description="Streaming resample + normalize.",
        category="Preprocessing",
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample])
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=AudioSample)
    }

    class Config(NodeConfig):
        sample_rate: int = 16000

    async def process_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        import librosa
        from copy import deepcopy

        samples: list[AudioSample] = inputs["input"]
        for s in samples:
            new = deepcopy(s)
            if new.sample_rate != self.config.sample_rate:
                new.data = librosa.resample(
                    y=new.data,
                    orig_sr=new.sample_rate,
                    target_sr=self.config.sample_rate,
                )
                new.sample_rate = self.config.sample_rate
            yield {"output": new}
```

---

## 6. `is_streaming` Detection

```python
# In Node base class:
@classmethod
@property
def is_streaming(cls) -> bool:
    """True when this class overrides process_stream."""
    return cls.process_stream is not Node.process_stream
```

The pipeline executor checks `node.is_streaming` to decide whether to call `execute()` or `execute_stream()`.

---

## 7. Observer Attachment

Observers are passed at node construction time:

```python
from app.core.nodes.observers import LoggingObserver, CompositeObserver
import logging

obs = LoggingObserver(logging.getLogger("pipeline"))
node = CleanNode(config={"sample_rate": 16000}, seed=42, observer=obs)
```

Or composed:

```python
composite = CompositeObserver([
    LoggingObserver(),
    MetricsObserver(),   # custom implementation
])
node = CleanNode(config={}, seed=0, observer=composite)
```

The pipeline executor is responsible for injecting observers when constructing nodes from a pipeline config.
