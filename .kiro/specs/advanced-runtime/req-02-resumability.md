# req-02 — Resumability

## Overview

Phase 3 makes the existing checkpoint mechanism readable for run resumption. A failed or interrupted run can be restarted from the last successful node, skipping already-completed work.

---

## Current State

`_write_checkpoint()` in `app/core/pipeline.py` writes per-node WAV files + `manifest.json` to `workspace/runs/<run_id>/checkpoints/node_<node_id>/`. This data is written but never read back — there is no resume path.

`RunManager` writes `meta.json` with `status: "running"/"completed"/"failed"` but has no `resume_state.json`.

---

## Design: Resume State File

### Schema

`workspace/runs/<run_id>/resume_state.json`:

```json
{
  "schema_version": "1.0",
  "run_id": "abc12345",
  "completed_nodes": ["input_0", "clean_0"],
  "graph_hash": "<sha256 of the GraphIR JSON>"
}
```

`graph_hash` is used to detect if the graph changed between the original run and the resume attempt (warn but do not block).

### Write Path

After each node completes successfully (inside the execution loop), `RunManager.update_resume_state(node_id)` is called when `checkpoint=True`:

```python
def update_resume_state(self, node_id: str) -> None:
    state = self._load_resume_state()
    state["completed_nodes"].append(node_id)
    path = os.path.join(self.base_path, "resume_state.json")
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
```

### Read Path

When `resume_run_id` is provided:

```python
prior_run_path = os.path.join(workspace, "runs", resume_run_id)
resume_state_path = os.path.join(prior_run_path, "resume_state.json")

if not os.path.exists(prior_run_path):
    raise ResumeError(f"Resume run '{resume_run_id}' not found at {prior_run_path}")
if not os.path.exists(resume_state_path):
    raise ResumeError(f"No resume_state.json found for run '{resume_run_id}'")

with open(resume_state_path) as f:
    state = json.load(f)

completed_nodes: set[str] = set(state.get("completed_nodes", []))
```

### Checkpoint Loading

For each node in `completed_nodes`, load outputs from the prior run's checkpoint:

```python
checkpoint_dir = os.path.join(prior_run_path, "checkpoints", f"node_{node_id}")
manifest_path = os.path.join(checkpoint_dir, "manifest.json")

if not os.path.exists(manifest_path):
    logger.warning(f"Checkpoint missing for node '{node_id}' — will re-execute")
    completed_nodes.discard(node_id)
else:
    node_outputs[node_id] = _load_checkpoint(checkpoint_dir)
```

### New RunManager Methods

```python
def init_resume_state(self, graph_hash: str) -> None:
    """Create initial resume_state.json for this run."""

def update_resume_state(self, node_id: str) -> None:
    """Append node_id to completed_nodes in resume_state.json."""

def load_resume_state(self, run_id: str) -> dict:
    """Load resume_state.json from a prior run. Raises ResumeError on failure."""
```

### New Error Class

```python
class ResumeError(RuntimeError):
    """Raised when a resume operation cannot be completed."""
```

Defined in `app/core/pipeline.py`, exported from `app/core/__init__.py`.

### New Logger Event

```python
def node_skip(self, node_id: str, node_type: str, reason: str):
    self._emit_structured({
        "type": "node_skip",
        "node_id": node_id,
        "node_type": node_type,
        "reason": reason,
        "timestamp": self._timestamp(),
    })
```

### New `meta.json` Fields

```json
{
  "resumed_from": "abc12345",
  "skipped_nodes": ["input_0", "clean_0"],
  "executed_nodes": ["augment_0"]
}
```

---

## Files Modified

| File | Change |
|---|---|
| `app/core/pipeline.py` | Add `ResumeError`; add resume logic to `run_pipeline_ir_async()` |
| `app/core/run_manager.py` | Add `init_resume_state()`, `update_resume_state()`, `load_resume_state()` |
| `app/core/logger.py` | Add `node_skip()` method |

## Files Created

| File | Purpose |
|---|---|
| `tests/test_resumability.py` | Tests for resume path, `ResumeError`, checkpoint loading |
