# Example 21 — Runtime Control via REST API and SDK

Demonstrates live control over a running pipeline — pause, inspect, resume, and cancel — through both the Python SDK and the REST API.

---

## What This Demonstrates

- `RunManager.pause()` / `resume()` / `cancel()` — SDK-level control
- `POST /api/v1/runs/{run_id}/pause` → `{"status": "paused"}`
- `POST /api/v1/runs/{run_id}/resume` → `{"status": "running"}`
- `POST /api/v1/runs/{run_id}/cancel` → `{"status": "cancelled"}`
- `GET /api/v1/runs/{run_id}/status` — polling for status + `progress_pct`
- `_ACTIVE_RUNS` registry — how active runs are tracked in memory
- MCP equivalents: `pause_run`, `resume_run`, `cancel_run` tools

All three interfaces (SDK, REST API, MCP) delegate to the same `RunManager` implementation.

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

# SDK-only demo (no HTTP server needed)
venv/bin/python examples/21_runtime_control_api/runtime_control_demo.py --sdk-only

# Full demo including REST API (requires API server)
# Terminal 1:
venv/bin/uvicorn app.api.main:app --reload --port 8001

# Terminal 2:
venv/bin/python examples/21_runtime_control_api/runtime_control_demo.py
```

---

## Expected Output

```
Demo A — SDK Runtime Control (no HTTP server needed)
  Pipeline started — run_id: f9538ea5
  → Calling run_mgr.pause()...
  → Calling run_mgr.resume()...
  ✓ Resumed
  → Calling run_mgr.cancel()...
  ✓ Final status: cancelled

Demo B — REST API Runtime Control
  ✓ Run started — run_id: ddec5a9e
  ✓ Paused:    {'run_id': 'ddec5a9e', 'status': 'paused'}
  → Status: paused  progress: 25%
  ✓ Resumed:   {'run_id': 'ddec5a9e', 'status': 'running'}
  ✓ Cancelled: {'run_id': 'ddec5a9e', 'status': 'cancelled'}
  ✓ Final status: cancelled
```

---

## SDK Usage

```python
from app.core.sdk import Pipeline, PipelineNode
import threading

pipeline = Pipeline([...], seed=42)

# Run in background thread so we can control it
result_holder = [None]
run_mgr_ref   = [None]

def _run():
    result, run_mgr = pipeline.run_with_manager()
    result_holder[0] = result
    run_mgr_ref[0]   = run_mgr

thread = threading.Thread(target=_run, daemon=True)
thread.start()

# Wait for run_manager to be allocated
import time
while run_mgr_ref[0] is None:
    time.sleep(0.05)

run_mgr = run_mgr_ref[0]
print(f"run_id: {run_mgr.run_id}")

# Control the running pipeline
run_mgr.pause()    # pause after current node completes
time.sleep(1)
run_mgr.resume()   # resume execution
time.sleep(1)
run_mgr.cancel()   # cancel after current node completes

thread.join(timeout=30)
```

---

## REST API Usage

```python
import httpx, time

# Start a long-running pipeline
resp = httpx.post("http://localhost:8001/api/v1/pipelines/run-async", json=graph)
run_id = resp.json()["run_id"]

# Pause
httpx.post(f"http://localhost:8001/api/v1/runs/{run_id}/pause")

# Check status
status = httpx.get(f"http://localhost:8001/api/v1/runs/{run_id}/status").json()
print(f"Status: {status['status']}, Progress: {status.get('progress_pct') or 0:.0f}%")

# Resume
httpx.post(f"http://localhost:8001/api/v1/runs/{run_id}/resume")

# Cancel
httpx.post(f"http://localhost:8001/api/v1/runs/{run_id}/cancel")
```

---

## MCP Usage

```json
// Pause
{"tool": "pause_run", "arguments": {"run_id": "abc12345"}}
// → {"run_id": "abc12345", "status": "paused"}

// Resume
{"tool": "resume_run", "arguments": {"run_id": "abc12345"}}
// → {"run_id": "abc12345", "status": "running"}

// Cancel
{"tool": "cancel_run", "arguments": {"run_id": "abc12345"}}
// → {"run_id": "abc12345", "status": "cancelled"}
```

---

## How It Works

Control signals are checked **between nodes** — the pipeline never interrupts a node mid-execution. After each node completes, the executor checks:

1. Is `cancel` set? → stop execution, mark run as cancelled
2. Is `pause` set? → block until `resume` is called

This guarantees that node outputs are always complete and consistent — no partial writes.

The `_ACTIVE_RUNS` dict in `run_manager.py` maps `run_id → RunManager` for all currently executing pipelines. `get_active_run(run_id)` looks up a run by ID. Once a run completes (success, failure, or cancellation), it is removed from `_ACTIVE_RUNS`.
