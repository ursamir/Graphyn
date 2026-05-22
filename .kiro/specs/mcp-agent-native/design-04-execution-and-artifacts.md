# Design 04 — Pipeline Execution and Artifact Inspection

## Overview

This sub-document covers:
- `app/mcp/handlers/execution.py` — the `execute_pipeline` tool
- `app/mcp/handlers/artifacts.py` — the `inspect_run` tool

---

## 1. Tool: `execute_pipeline`

### Schema

```python
EXECUTE_PIPELINE_DESCRIPTION = (
    "Execute a pipeline from a GraphIR JSON document. Returns run_id within 500ms. "
    "Execution proceeds asynchronously in a background thread. Use inspect_run to "
    "retrieve artifacts and logs after completion."
)

EXECUTE_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "graph": {
            "type": "object",
            "description": "A validated GraphIR JSON document.",
        },
        "use_cache": {
            "type": "boolean",
            "description": "Whether to use PipelineCache for node outputs (default true).",
            "default": True,
        },
        "streaming": {
            "type": "boolean",
            "description": (
                "Whether to use streaming execution mode via NodeExecutor.execute_stream "
                "(default false)."
            ),
            "default": False,
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["graph"],
    "additionalProperties": False,
}
```

### Handler

```python
# app/mcp/handlers/execution.py
"""execute_pipeline tool handler.

Req 4.1–4.14
"""
from __future__ import annotations

import concurrent.futures
import queue
import time
from typing import Any

from app.core.ir.loader import load_ir
from app.core.logger import PipelineLogger
from app.core.pipeline import run_pipeline_ir
from app.core.run_manager import RunManager


def execute_pipeline_handler(arguments: dict[str, Any]) -> Any:
    """Execute a pipeline asynchronously (Req 4.1–4.14).

    Returns run_id within 500 ms (Req 4.2).
    Delegates to run_pipeline_ir() (Req 4.1, 4.13).
    """
    graph_dict = arguments.get("graph")
    use_cache = arguments.get("use_cache", True)
    streaming = arguments.get("streaming", False)

    # ── Validate graph ─────────────────────────────────────────────────────────
    try:
        graph = load_ir(graph_dict)
    except Exception as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
        }

    # ── Allocate run_id ────────────────────────────────────────────────────────
    run_manager = RunManager()
    run_id = run_manager.run_id

    # ── Launch execution in background thread ──────────────────────────────────
    # Use a queue to bridge PipelineLogger events to the MCP response.
    # The queue is not returned to the agent — it's for internal event bridging only.
    # Agents retrieve events via inspect_run after execution completes.
    event_queue: queue.Queue = queue.Queue()
    logger = PipelineLogger(queue=event_queue)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        run_pipeline_ir,
        graph,
        logger=logger,
        use_cache=use_cache,
        checkpoint=False,
        streaming=streaming,
        observer=None,
        run_manager=run_manager,
    )

    # ── Return run_id within 500 ms ────────────────────────────────────────────
    # The future is not awaited here — execution proceeds in the background.
    # The agent can poll inspect_run to check status.
    return {
        "run_id": run_id,
        "status": "started",
    }
```

**Design notes:**
- The `event_queue` is created but not returned to the agent. It's used internally by `PipelineLogger` to emit structured events. Agents retrieve events via `inspect_run` after execution completes (Req 4.3–4.8).
- The `future` is not awaited. The thread runs in the background. The agent polls `inspect_run` to check status.
- The 500 ms constraint (Req 4.2) is met because the handler returns immediately after submitting the task to the executor.

---

## 2. NDJSON Event Streaming

The existing `PipelineLogger` in `app/core/logger.py` already emits structured events via `_emit_structured()`. These events are stored in `logger.logs` and saved to `workspace/runs/<run_id>/logs.json` by `RunManager.save_logs()`.

The MCP layer does not introduce a separate event streaming mechanism (Req 6.7). Agents retrieve events by calling `inspect_run` with `logs: true` after execution completes.

### Event Order Guarantee (Req 4.3)

The event order is guaranteed by the sequential execution model in `run_pipeline_ir()`:
1. `pipeline_start` is emitted first
2. For each node in topological order: `node_start` → (`node_end` | `node_error`)
3. Exactly one terminal event: `done` | `error`

This order is enforced by the existing `PipelineLogger` implementation and does not require MCP-specific logic.

### Event Schema (Req 4.4–4.8)

The event schema is defined by the existing `PipelineLogger` methods:
- `pipeline_start(total_nodes)` → `{"type": "pipeline_start", "total_nodes": int, "timestamp": str}`
- `node_start(node_type, index)` → `{"type": "node_start", "node_type": str, "node_index": int, "timestamp": str}`
- `node_end(node_type, index, duration, output_count)` → `{"type": "node_end", "node_type": str, "node_index": int, "duration_s": float, "timestamp": str}`
- `node_error(node_type, index, error)` → `{"type": "node_error", "node_type": str, "node_index": int, "error_message": str, "error_type": str, "timestamp": str}`
- `summary()` → `{"type": "done", "run_id": str, "duration_s": float, "timestamp": str}` (added to `PipelineLogger` in Phase 2)
- Pipeline failure → `{"type": "error", "message": str, "timestamp": str}` (added to `PipelineLogger` in Phase 2)

**Phase 2 additions to `PipelineLogger`:**

```python
# Addition to app/core/logger.py

def pipeline_done(self, run_id: str, duration: float):
    """Emit a 'done' event (Req 4.7)."""
    self._emit_structured({
        "type": "done",
        "run_id": run_id,
        "duration_s": duration,
        "timestamp": self._timestamp(),
    })

def pipeline_error(self, message: str):
    """Emit an 'error' event (Req 4.8)."""
    self._emit_structured({
        "type": "error",
        "message": message,
        "timestamp": self._timestamp(),
    })
```

These methods are called by `run_pipeline_ir()` at the appropriate points:
- `logger.pipeline_done(run_id, duration)` after successful execution
- `logger.pipeline_error(str(exc))` on execution failure

---

## 3. Tool: `inspect_run`

### Schema

```python
INSPECT_RUN_DESCRIPTION = (
    "Inspect a pipeline run's metadata, logs, graph snapshot, and artifacts. "
    "Supports listing all runs, retrieving run metadata, logs, graph.json, "
    "checkpoint manifests, and status-only queries."
)

INSPECT_RUN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "description": "Run ID to inspect. Omit to list all runs.",
        },
        "logs": {
            "type": "boolean",
            "description": "Return logs.json contents (requires run_id).",
            "default": False,
        },
        "graph": {
            "type": "boolean",
            "description": "Return graph.json contents (requires run_id).",
            "default": False,
        },
        "checkpoints": {
            "type": "boolean",
            "description": "Return list of node IDs with checkpoints (requires run_id).",
            "default": False,
        },
        "node_id": {
            "type": "string",
            "description": "Return checkpoint manifest for this node (requires run_id).",
        },
        "status_only": {
            "type": "boolean",
            "description": "Return only the run status (requires run_id).",
            "default": False,
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}
```

### Handler

```python
# app/mcp/handlers/artifacts.py
"""inspect_run tool handler.

Req 5.1–5.12
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_WORKSPACE = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
_RUNS_DIR = Path(_WORKSPACE) / "runs"


def inspect_run_handler(arguments: dict[str, Any]) -> Any:
    """Inspect run artifacts (Req 5.1–5.12).

    Delegates to RunManager workspace path conventions (Req 5.10, 6.5).
    """
    run_id = arguments.get("run_id")

    # ── List all runs ──────────────────────────────────────────────────────────
    if run_id is None:
        if not _RUNS_DIR.exists():
            return {"runs": []}

        runs = []
        for run_dir in sorted(_RUNS_DIR.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                with meta_path.open("r") as f:
                    meta = json.load(f)
                runs.append({
                    "run_id": meta.get("run_id", run_dir.name),
                    "status": meta.get("status", "unknown"),
                    "created_at": meta.get("created_at"),
                    "duration_s": meta.get("duration_s"),
                    "num_nodes": meta.get("num_nodes", 0),
                })
            except Exception:
                runs.append({
                    "run_id": run_dir.name,
                    "status": "unknown",
                    "created_at": None,
                    "duration_s": None,
                    "num_nodes": 0,
                })
        return {"runs": runs}

    # ── Single run inspection ──────────────────────────────────────────────────
    run_dir = _RUNS_DIR / run_id
    if not run_dir.exists():
        return {
            "error": True,
            "error_type": "unknown_run_id",
            "message": f"Run directory not found: {run_id}",
        }

    # ── status_only ────────────────────────────────────────────────────────────
    if arguments.get("status_only"):
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            return {"status": "unknown"}
        try:
            with meta_path.open("r") as f:
                meta = json.load(f)
            return {"status": meta.get("status", "unknown")}
        except Exception:
            return {"status": "unknown"}

    # ── logs ───────────────────────────────────────────────────────────────────
    if arguments.get("logs"):
        logs_path = run_dir / "logs.json"
        if not logs_path.exists():
            return {
                "error": True,
                "error_type": "artifact_not_found",
                "message": "logs.json not found for this run.",
                "artifact": "logs.json",
            }
        try:
            with logs_path.open("r") as f:
                logs = json.load(f)
            return {"logs": logs}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
            }

    # ── graph ──────────────────────────────────────────────────────────────────
    if arguments.get("graph"):
        graph_path = run_dir / "graph.json"
        if not graph_path.exists():
            return {
                "error": True,
                "error_type": "artifact_not_found",
                "message": "graph.json not found for this run.",
                "artifact": "graph.json",
            }
        try:
            with graph_path.open("r") as f:
                graph = json.load(f)
            return {"graph": graph}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
            }

    # ── checkpoints ────────────────────────────────────────────────────────────
    if arguments.get("checkpoints"):
        checkpoints_dir = run_dir / "checkpoints"
        if not checkpoints_dir.exists():
            return {"checkpoints": []}
        node_ids = [
            d.name.replace("node_", "")
            for d in checkpoints_dir.iterdir()
            if d.is_dir() and d.name.startswith("node_")
        ]
        return {"checkpoints": sorted(node_ids)}

    # ── node_id checkpoint manifest ────────────────────────────────────────────
    node_id = arguments.get("node_id")
    if node_id:
        checkpoint_dir = run_dir / "checkpoints" / f"node_{node_id}"
        manifest_path = checkpoint_dir / "manifest.json"
        if not manifest_path.exists():
            return {
                "error": True,
                "error_type": "checkpoint_not_found",
                "message": f"Checkpoint not found for node '{node_id}'.",
                "node_id": node_id,
            }
        try:
            with manifest_path.open("r") as f:
                manifest = json.load(f)
            return {"manifest": manifest}
        except Exception as exc:
            return {
                "error": True,
                "error_type": "artifact_read_error",
                "message": str(exc),
            }

    # ── Default: return full metadata ──────────────────────────────────────────
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return {
            "error": True,
            "error_type": "artifact_not_found",
            "message": "meta.json not found for this run.",
            "artifact": "meta.json",
        }
    try:
        with meta_path.open("r") as f:
            meta = json.load(f)
        return meta
    except Exception as exc:
        return {
            "error": True,
            "error_type": "artifact_read_error",
            "message": str(exc),
        }
```

---

## 4. Consistency Property (Req 4.14)

For all GraphIR documents for which `validate_graph` returns `valid: true`, the `execute_pipeline` tool must accept and begin executing the document without returning a validation error.

This is guaranteed structurally because both tools delegate to `load_ir()` for validation. If `validate_graph` returns `valid: true`, then `load_ir()` succeeded. If `execute_pipeline` calls `load_ir()` on the same document, it will also succeed.

---

## 5. Consistency Property (Req 5.11)

For all run IDs returned by `inspect_run`'s list operation, a subsequent invocation of `inspect_run` with that `run_id` must return either the run metadata or a structured error — it must not raise an unhandled exception.

This is guaranteed by the handler's exception handling: every file read is wrapped in a `try/except` block that returns a structured error dict on failure.
