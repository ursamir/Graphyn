# req-06 — Runtime Control API

## Overview

The Runtime Control API exposes pause, resume, and cancel operations on active pipeline runs via `RunManager`, the REST API, and MCP tools.

---

## Current State

`RunManager` has no control methods. Once `run_pipeline_ir()` is called, it runs to completion (or failure) with no external intervention possible.

---

## Design

### `RunManager` Control Methods

`app/core/run_manager.py` gains a `threading.Event`-based control mechanism:

```python
import threading

class RunManager:
    def __init__(self, base_dir: str | None = None):
        ...
        self._pause_event = threading.Event()
        self._pause_event.set()   # not paused initially
        self._cancel_event = threading.Event()

    def pause(self) -> None:
        """Signal the executor to pause after the current node."""
        self._pause_event.clear()
        self._write_meta_field("status", "paused")

    def resume(self) -> None:
        """Signal the executor to continue from the pause point."""
        self._pause_event.set()
        self._write_meta_field("status", "running")

    def cancel(self) -> None:
        """Signal the executor to stop after the current node."""
        self._cancel_event.set()
        self._pause_event.set()   # unblock if paused

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def wait_if_paused(self) -> None:
        """Block until resumed. Called by executor between nodes."""
        self._pause_event.wait()

    def _write_meta_field(self, key: str, value: str) -> None:
        """Update a single field in meta.json without overwriting others."""
        meta_path = os.path.join(self.base_path, "meta.json")
        existing = {}
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                existing = json.load(f)
        existing[key] = value
        with open(meta_path, "w") as f:
            json.dump(existing, f, indent=2)
```

### Executor Integration

Between each node execution (or between waves in parallel mode):

```python
# Check pause
run.wait_if_paused()
if run.is_paused:
    logger.pipeline_paused(run_id=run.run_id)

# Check cancel
if run.is_cancelled:
    logger.pipeline_cancelled(
        run_id=run.run_id,
        nodes_completed=nodes_completed,
        nodes_remaining=nodes_remaining,
    )
    for exec_ in executors.values():
        exec_.teardown()
    run.mark_cancelled()
    return node_outputs.get(last_completed_id, {})
```

### Active Run Registry

A module-level dict in `app/core/run_manager.py` tracks active `RunManager` instances by `run_id`:

```python
_ACTIVE_RUNS: dict[str, "RunManager"] = {}

def register_active_run(run: "RunManager") -> None:
    _ACTIVE_RUNS[run.run_id] = run

def get_active_run(run_id: str) -> "RunManager | None":
    return _ACTIVE_RUNS.get(run_id)

def deregister_active_run(run_id: str) -> None:
    _ACTIVE_RUNS.pop(run_id, None)
```

`run_pipeline_ir_async()` calls `register_active_run(run)` at start and `deregister_active_run(run.run_id)` in a `finally` block.

### REST API Endpoints

New file `app/api/routers/run_control.py`:

```python
from fastapi import APIRouter, HTTPException
from app.core.run_manager import get_active_run

router = APIRouter(prefix="/api/v1/runs", tags=["run-control"])

@router.post("/{run_id}/pause")
async def pause_run(run_id: str):
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "run_not_active", "run_id": run_id})
    run.pause()
    return {"run_id": run_id, "status": "paused"}

@router.post("/{run_id}/resume")
async def resume_run(run_id: str):
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "run_not_active", "run_id": run_id})
    run.resume()
    return {"run_id": run_id, "status": "running"}

@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "run_not_active", "run_id": run_id})
    run.cancel()
    return {"run_id": run_id, "status": "cancelled"}
```

Registered in `app/api/main.py`.

### MCP Tools

Three new tools in `app/mcp/handlers/execution.py` (or a new `app/mcp/handlers/run_control.py`):

| Tool Name | Arguments | Delegates To |
|---|---|---|
| `pause_run` | `run_id: str` | `get_active_run(run_id).pause()` |
| `resume_run` | `run_id: str` | `get_active_run(run_id).resume()` |
| `cancel_run` | `run_id: str` | `get_active_run(run_id).cancel()` |

All three return `{"run_id": ..., "status": ...}` on success or `{"error_type": "run_not_active", "run_id": ...}` when the run is not found.

### New Logger Events

```python
def pipeline_paused(self, run_id: str):
    self._emit_structured({
        "type": "pipeline_paused",
        "run_id": run_id,
        "timestamp": self._timestamp(),
    })

def pipeline_resumed(self, run_id: str):
    self._emit_structured({
        "type": "pipeline_resumed",
        "run_id": run_id,
        "timestamp": self._timestamp(),
    })

def pipeline_cancelled(self, run_id: str, nodes_completed: int, nodes_remaining: int):
    self._emit_structured({
        "type": "pipeline_cancelled",
        "run_id": run_id,
        "nodes_completed": nodes_completed,
        "nodes_remaining": nodes_remaining,
        "timestamp": self._timestamp(),
    })
```

### `RunManager.mark_cancelled()`

```python
def mark_cancelled(self) -> None:
    duration = time.time() - self._start_time
    existing = self._read_meta()
    existing.update({
        "status": "cancelled",
        "duration_s": round(duration, 3),
    })
    self._write_meta(existing)
```

---

## Files Modified

| File | Change |
|---|---|
| `app/core/run_manager.py` | Add `pause()`, `resume()`, `cancel()`, `wait_if_paused()`, active run registry, `mark_cancelled()` |
| `app/core/pipeline.py` | Add pause/cancel check between nodes in `run_pipeline_ir_async()` |
| `app/core/logger.py` | Add `pipeline_paused()`, `pipeline_resumed()`, `pipeline_cancelled()` |
| `app/api/main.py` | Register `run_control` router |
| `app/mcp/tool_registry.py` | Register `pause_run`, `resume_run`, `cancel_run` tools |

## Files Created

| File | Purpose |
|---|---|
| `app/api/routers/run_control.py` | REST endpoints for pause/resume/cancel |
| `app/mcp/handlers/run_control.py` | MCP tool handlers for pause/resume/cancel |
| `tests/test_runtime_control.py` | Tests for pause, resume, cancel, active run registry |
