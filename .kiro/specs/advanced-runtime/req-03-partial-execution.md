# req-03 — Partial Execution

## Overview

Partial execution allows running only a named subset of nodes from a `GraphIR`, enabling targeted testing, debugging, and re-running of individual pipeline stages.

---

## Current State

`run_pipeline_ir()` always executes all nodes in the graph. There is no mechanism to skip nodes or inject pre-computed inputs.

---

## Design

### API

Two new mutually exclusive parameters on `run_pipeline_ir()` / `run_pipeline_ir_async()`:

```python
include_nodes: list[str] | None = None   # run only these nodes
exclude_nodes: list[str] | None = None   # run all except these nodes
input_overrides: dict[str, dict[str, Any]] | None = None  # inject inputs
```

Mutual exclusion check (raises `ValueError` immediately):

```python
if include_nodes is not None and exclude_nodes is not None:
    raise ValueError("include_nodes and exclude_nodes are mutually exclusive")
```

### Node Set Resolution

```python
all_node_ids = {n.id for n in graph.nodes}

# Validate all provided IDs exist
for nid in (include_nodes or []) + (exclude_nodes or []):
    if nid not in all_node_ids:
        raise ValueError(f"Unknown node ID '{nid}' in partial execution request")

if include_nodes is not None:
    active_nodes = set(include_nodes)
elif exclude_nodes is not None:
    active_nodes = all_node_ids - set(exclude_nodes)
else:
    active_nodes = all_node_ids
```

### Input Resolution for Boundary Nodes

A "boundary node" is a node in `active_nodes` whose upstream node is NOT in `active_nodes`. For boundary nodes, inputs are sourced in this priority order:

1. `input_overrides[node_id][port_name]` — caller-provided value
2. Checkpoint from the most recent completed run containing that node (looked up via `RunManager.find_latest_checkpoint(node_id)`)
3. `None` (port receives no data; node must handle gracefully or will error)

```python
def _resolve_boundary_input(
    node_id: str,
    port_name: str,
    input_overrides: dict,
    run_manager: RunManager,
) -> Any:
    if node_id in input_overrides and port_name in input_overrides[node_id]:
        return input_overrides[node_id][port_name]
    checkpoint = run_manager.find_latest_checkpoint(node_id)
    if checkpoint is not None:
        return checkpoint.get(port_name)
    return None
```

### `pipeline_start` Event Extension

```python
logger.pipeline_start(
    total_nodes=len(active_nodes),
    partial=True,
    included_nodes=sorted(active_nodes),
)
```

The `pipeline_start` event gains optional `partial` (bool) and `included_nodes` (list) fields. Existing consumers that don't read these fields are unaffected.

### `meta.json` Extension

```json
{
  "partial_execution": true,
  "included_nodes": ["augment_0", "export_0"],
  "excluded_nodes": null
}
```

### New `RunManager` Method

```python
def find_latest_checkpoint(self, node_id: str) -> dict | None:
    """Search workspace/runs/ for the most recent run containing a checkpoint
    for node_id. Returns the loaded outputs dict or None."""
```

---

## Files Modified

| File | Change |
|---|---|
| `app/core/pipeline.py` | Add partial execution logic to `run_pipeline_ir_async()` |
| `app/core/run_manager.py` | Add `find_latest_checkpoint()` |
| `app/core/logger.py` | Extend `pipeline_start()` with `partial` and `included_nodes` kwargs |

## Files Created

| File | Purpose |
|---|---|
| `tests/test_partial_execution.py` | Tests for `include_nodes`, `exclude_nodes`, `input_overrides`, mutual exclusion |
