# req-01 — Parallel Execution and Async-Native Runtime

## Overview

This document details the design for parallel execution waves and the async-native runtime that replaces the current `asyncio.run()` bridge in `run_pipeline_ir()`.

---

## Current State

`run_pipeline_ir()` in `app/core/pipeline.py` executes nodes in a flat sequential loop:

```python
for idx, node_id in enumerate(graph_obj.execution_order):
    ...
    outputs = exec_.execute(inputs)   # blocking, one at a time
```

`PipelineGraph.execution_order` returns a flat `list[str]` from Kahn's algorithm. Nodes that have no data dependency on each other (parallel branches) are serialized unnecessarily.

Streaming nodes are bridged via `asyncio.run(_collect_stream(...))` which creates a new event loop per call — incompatible with running inside an existing event loop (FastAPI, MCP server).

---

## Design: Execution Waves

### Wave Computation

`PipelineGraph` gains an `execution_waves` property that groups the topological order into waves:

```
Wave 0: [A]          # no dependencies
Wave 1: [B, C]       # both depend only on A
Wave 2: [D]          # depends on B and C
```

Algorithm (level-based BFS):

```python
@property
def execution_waves(self) -> list[list[str]]:
    level: dict[str, int] = {}
    for node_id in self._topo_order:
        preds = [e.src_id for e in self._edges if e.dst_id == node_id]
        level[node_id] = max((level[p] + 1 for p in preds), default=0)
    max_level = max(level.values(), default=0)
    return [
        [nid for nid, lv in level.items() if lv == i]
        for i in range(max_level + 1)
    ]
```

The existing `execution_order` property is preserved and returns `list(itertools.chain(*self.execution_waves))`.

### Parallel Executor

When `run_pipeline_ir(..., parallel=True)`:

```python
async def _run_wave(wave: list[str], ...) -> None:
    tasks = [asyncio.create_task(_run_node(node_id, ...)) for node_id in wave]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # check for exceptions, cancel remaining, propagate first error
```

For sync nodes, `_run_node` wraps `exec_.execute(inputs)` in `loop.run_in_executor(thread_pool, ...)`.

For streaming nodes (`node.is_streaming`), `_run_node` calls `exec_.execute_stream(inputs)` natively.

### New Logger Events

```python
def wave_start(self, wave_index: int, node_ids: list[str]):
    self._emit_structured({
        "type": "wave_start",
        "wave_index": wave_index,
        "node_ids": node_ids,
        "timestamp": self._timestamp(),
    })

def wave_end(self, wave_index: int, node_ids: list[str], duration_s: float):
    self._emit_structured({
        "type": "wave_end",
        "wave_index": wave_index,
        "node_ids": node_ids,
        "duration_s": duration_s,
        "timestamp": self._timestamp(),
    })
```

---

## Design: Async-Native Runtime

### `run_pipeline_ir_async()`

New function in `app/core/pipeline.py`:

```python
async def run_pipeline_ir_async(
    graph: Any,
    logger: Any = None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    parallel: bool = False,
    observer: NodeObserver | None = None,
    run_manager: Any = None,
    max_workers: int | None = None,
    # Phase 3 new params (req-02, req-03, req-04, req-05):
    resume_run_id: str | None = None,
    include_nodes: list[str] | None = None,
    exclude_nodes: list[str] | None = None,
    input_overrides: dict | None = None,
    event_driven: bool = False,
    event_loop: Any = None,
) -> dict[str, Any]:
    ...
```

### `run_pipeline_ir()` updated signature

```python
def run_pipeline_ir(
    graph: Any,
    logger: Any = None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    parallel: bool = False,
    observer: NodeObserver | None = None,
    run_manager: Any = None,
    max_workers: int | None = None,
    resume_run_id: str | None = None,
    include_nodes: list[str] | None = None,
    exclude_nodes: list[str] | None = None,
    input_overrides: dict | None = None,
    event_driven: bool = False,
) -> dict[str, Any]:
    return asyncio.run(run_pipeline_ir_async(...))
```

All existing call sites pass no new arguments → default values reproduce current behavior exactly.

---

## Files Modified

| File | Change |
|---|---|
| `app/core/pipeline.py` | Add `execution_waves` to `PipelineGraph`; add `run_pipeline_ir_async()`; extend `run_pipeline_ir()` signature |
| `app/core/logger.py` | Add `wave_start()`, `wave_end()` methods |

## Files Created

| File | Purpose |
|---|---|
| `app/core/executor.py` | `ParallelExecutor` class — wave-based async execution |
| `tests/test_parallel_executor.py` | Unit + property tests for parallel execution |
| `tests/test_async_runtime.py` | Tests for `run_pipeline_ir_async()` |
