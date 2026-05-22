# req-05 — Event-Driven Execution

## Overview

Event-driven execution binds pipeline nodes to external event sources (file system, timers, queues) so that pipelines react to real-world triggers rather than being invoked once and terminating.

---

## Current State

`run_pipeline_ir()` executes a pipeline once and returns. There is no mechanism for continuous or reactive execution.

---

## Design

### `EventSource` Abstract Base Class

`app/core/events.py`:

```python
from __future__ import annotations
import abc
from typing import AsyncGenerator


class EventSource(abc.ABC):
    """Abstract base for event sources that trigger node execution."""

    @abc.abstractmethod
    async def watch(self) -> AsyncGenerator[dict, None]:
        """Yield event payload dicts indefinitely until cancelled."""
        ...

    async def close(self) -> None:
        """Release resources. Called when the event-driven run ends."""
        pass
```

### Built-in Implementations

#### `FileWatcherSource`

```python
class FileWatcherSource(EventSource):
    def __init__(self, path: str, pattern: str = "*"):
        self.path = path
        self.pattern = pattern

    async def watch(self) -> AsyncGenerator[dict, None]:
        # Uses watchfiles.awatch() if available, else polling fallback
        import watchfiles
        async for changes in watchfiles.awatch(self.path):
            for change_type, file_path in changes:
                if fnmatch.fnmatch(os.path.basename(file_path), self.pattern):
                    yield {
                        "path": file_path,
                        "event": "created" if change_type == watchfiles.Change.added
                                 else "modified",
                    }
```

#### `TimerSource`

```python
class TimerSource(EventSource):
    def __init__(self, interval_s: float):
        self.interval_s = interval_s
        self._tick = 0

    async def watch(self) -> AsyncGenerator[dict, None]:
        while True:
            await asyncio.sleep(self.interval_s)
            self._tick += 1
            yield {
                "tick": self._tick,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
```

#### `QueueSource`

```python
class QueueSource(EventSource):
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    async def watch(self) -> AsyncGenerator[dict, None]:
        while True:
            payload = await self._queue.get()
            yield payload
```

### `IRNode` Extension

`app/core/ir/models.py` — `IRNode` gains one optional field:

```python
class IRNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    node_type: str
    config: dict[str, Any] = {}
    label: str | None = None
    capability_metadata: IRCapabilityMetadata | None = None
    event_trigger: dict | None = None  # NEW — Phase 3
    # Schema: {"source_type": "file_watcher"|"timer"|"queue", "source_config": {...}}
```

### Event Source Factory

`app/core/events.py`:

```python
_SOURCE_REGISTRY: dict[str, type[EventSource]] = {
    "file_watcher": FileWatcherSource,
    "timer": TimerSource,
    "queue": QueueSource,
}

def create_event_source(source_type: str, source_config: dict) -> EventSource:
    cls = _SOURCE_REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(f"Unknown event source type '{source_type}'")
    return cls(**source_config)
```

### Event-Driven Execution Loop

When `run_pipeline_ir_async(..., event_driven=True)`:

```python
# Identify trigger nodes
trigger_nodes = {
    node.id: node.event_trigger
    for node in graph.nodes
    if node.event_trigger is not None
}

# Create event sources
sources = {
    node_id: create_event_source(
        trigger["source_type"], trigger["source_config"]
    )
    for node_id, trigger in trigger_nodes.items()
}

trigger_count = 0

async def _handle_source(node_id: str, source: EventSource):
    nonlocal trigger_count
    async for payload in source.watch():
        logger.event_received(
            source_type=trigger_nodes[node_id]["source_type"],
            node_id=node_id,
            payload_keys=list(payload.keys()),
        )
        # Inject payload as input and execute node + downstream
        overrides = {node_id: {"input": payload}}
        await _execute_from_node(node_id, overrides)
        trigger_count += 1

# Run all source watchers concurrently
try:
    await asyncio.gather(*[
        _handle_source(nid, src) for nid, src in sources.items()
    ])
except asyncio.CancelledError:
    pass
finally:
    for src in sources.values():
        await src.close()
    run.save_metadata({
        "event_driven": True,
        "trigger_count": trigger_count,
    })
```

### New Logger Event

```python
def event_received(self, source_type: str, node_id: str, payload_keys: list[str]):
    self._emit_structured({
        "type": "event_received",
        "source_type": source_type,
        "node_id": node_id,
        "payload_keys": payload_keys,
        "timestamp": self._timestamp(),
    })
```

---

## Files Modified

| File | Change |
|---|---|
| `app/core/ir/models.py` | Add `event_trigger: dict | None = None` to `IRNode` |
| `app/core/pipeline.py` | Add event-driven execution path to `run_pipeline_ir_async()` |
| `app/core/logger.py` | Add `event_received()` method |

## Files Created

| File | Purpose |
|---|---|
| `app/core/events.py` | `EventSource` ABC, `FileWatcherSource`, `TimerSource`, `QueueSource`, factory |
| `tests/test_event_driven.py` | Tests using `QueueSource` (deterministic), `TimerSource` (short interval) |
