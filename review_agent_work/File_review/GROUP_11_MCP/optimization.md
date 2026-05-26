# Functional Review — app/mcp/handlers/optimization.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/optimization.py
FUNCTION:    optimize_execution_handler
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Analyse a GraphIR and return execution optimization recommendations.
Handles graphs with no parallelism (linear chains) — group-specific
focus area.

WHAT IT ACTUALLY DOES:
```python
max_wave_size = max((len(w) for w in waves), default=0)
can_parallelize = max_wave_size > 1
```
For a linear chain (every wave has exactly 1 node), `max_wave_size = 1`
and `can_parallelize = False`. This is correct.

However, for a graph with zero nodes (empty graph), `waves` is an empty
list. `max((len(w) for w in []), default=0)` returns `0`. `can_parallelize`
is `False`. `wave_summary` is `[]`. `source_nodes` and `sink_nodes` are
both `[]`. The function returns a valid response with all-zero/empty fields
and the recommendation "No specific optimizations identified."

This is correct behavior for an empty graph. No bug here.

THE REAL BUG — single-node graph:
For a graph with exactly one node and no edges, `waves = [[node_id]]`.
`source_nodes = [node_id]` (not in `all_dst_ids`). `sink_nodes = [node_id]`
(not in `all_src_ids`). The same node appears in BOTH `source_nodes` AND
`sink_nodes`. This is technically correct (a single node is both a source
and a sink), but it may confuse callers that expect these lists to be
disjoint.

THE BUG / RISK:
A single-node graph produces `source_nodes = [node_id]` AND
`sink_nodes = [node_id]` — the same node in both lists. Callers that
assume source_nodes and sink_nodes are disjoint sets will get wrong
results.

EVIDENCE:
Lines ~100–103:
```python
all_dst_ids = {e.dst_id for e in graph.edges}
all_src_ids = {e.src_id for e in graph.edges}
source_nodes = [n.id for n in graph.nodes if n.id not in all_dst_ids]
sink_nodes = [n.id for n in graph.nodes if n.id not in all_src_ids]
```
For a single-node graph with no edges: `all_dst_ids = {}`, `all_src_ids = {}`.
Every node is both a source and a sink.

REPRODUCTION SCENARIO:
Call `optimize_execution` with a graph containing exactly one node and
no edges. Response: `source_nodes = ["node_1"]`, `sink_nodes = ["node_1"]`.

IMPACT:
Caller confusion — the same node appears in both lists. Not a crash or
data loss, but a misleading response.

FIX DIRECTION:
Document that source_nodes and sink_nodes can overlap for single-node
graphs. Or add a note in the response:
```python
"is_single_node": len(graph.nodes) == 1,
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/optimization.py
FUNCTION:    optimize_execution_handler
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Analyse each node's capability metadata using `_resolve_capability`.

WHAT IT ACTUALLY DOES:
```python
try:
    cap = _resolve_capability(ir_node, registry)
except Exception:
    cap = None
```
If `_resolve_capability` raises for a node, `cap` is set to `None` and
`analysis["capability"] = None`. The node is still included in the
response but with `capability = null`. The node is NOT added to any of
the capability-specific lists (`requires_gpu_nodes`, `edge_compatible_nodes`,
etc.).

This means: if capability resolution fails for a GPU-requiring node, that
node is silently excluded from `requires_gpu_nodes`. The recommendation
"Nodes [...] require a GPU" will not mention this node. The caller may
deploy to a CPU-only environment thinking it's safe, when in fact a node
requires a GPU.

THE BUG / RISK:
Silent omission from capability lists: nodes with failed capability
resolution are excluded from `requires_gpu_nodes`, `non_cacheable_nodes`,
etc. without any warning. The recommendations are silently incomplete.

EVIDENCE:
Lines ~79–82:
```python
except Exception:
    cap = None
# ... later:
if cap is not None:
    if cap.requires_gpu:
        requires_gpu_nodes.append(ir_node.id)
    # ... etc.
```
Nodes with `cap = None` are silently skipped in all capability lists.

REPRODUCTION SCENARIO:
A node's `_resolve_capability` raises (e.g. registry inconsistency).
The node requires a GPU but is not in `requires_gpu_nodes`. The
recommendation does not mention GPU requirements. Caller deploys to
CPU-only hardware and the pipeline fails at runtime.

IMPACT:
Silent wrong recommendation: GPU requirements may be missed. Could lead
to runtime failures in production deployments.

FIX DIRECTION:
Track nodes with failed capability resolution and include a warning:
```python
unknown_capability_nodes: list[str] = []
# in the except block:
unknown_capability_nodes.append(ir_node.id)
# in recommendations:
if unknown_capability_nodes:
    recommendations.append(
        f"WARNING: Could not resolve capability metadata for nodes "
        f"{unknown_capability_nodes} — hardware requirements unknown."
    )
# include in response:
"unknown_capability_nodes": unknown_capability_nodes,
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/optimization.py
FUNCTION:    optimize_execution_handler
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Import `resolve_capability` from `app.core.registry_runtime` as
`_resolve_capability`. The docstring says "BC3 resolve_capability (via
registry_runtime.resolve_capability — NOT orchestrator)".

WHAT IT ACTUALLY DOES:
```python
from app.core.registry_runtime import get_registry, resolve_capability as _resolve_capability
```
`registry_runtime.resolve_capability` has signature:
`resolve_capability(ir_node, registry) -> IRCapabilityMetadata`

The handler calls it as:
```python
cap = _resolve_capability(ir_node, registry)
```
This is correct. `resolve_capability` returns an `IRCapabilityMetadata`
object (not a dict). The handler then accesses `cap.requires_gpu`,
`cap.supports_cpu`, etc. — all valid attribute accesses on
`IRCapabilityMetadata`.

However, `registry_runtime.resolve_capability` has a fallback:
```python
except Exception:
    return IRCapabilityMetadata()  # default values
```
This means it NEVER raises — it always returns a valid object with
default values. The `try/except Exception: cap = None` in the handler
is therefore dead code — `_resolve_capability` will never raise.

THE BUG / RISK:
Dead code: the `except Exception: cap = None` branch in the handler is
unreachable because `registry_runtime.resolve_capability` catches all
exceptions internally and returns `IRCapabilityMetadata()` defaults.
This means nodes with unknown types get default capability values
(all False/empty) rather than `cap = None`. The `capability = null`
path in the response is never reached.

This is a contract mismatch between the handler's assumption (resolve_capability
can raise) and the actual implementation (it never raises).

EVIDENCE:
`registry_runtime.py` lines ~50–55:
```python
except Exception:
    return IRCapabilityMetadata()
```
Handler lines ~79–82:
```python
except Exception:
    cap = None  # unreachable
```

REPRODUCTION SCENARIO:
Pass a graph with an unregistered node type. `_resolve_capability` returns
`IRCapabilityMetadata()` (all defaults) instead of raising. The handler
treats the node as having default capabilities (e.g. `requires_gpu=False`),
not as having unknown capabilities. The `capability = null` response path
is never reached.

IMPACT:
Nodes with unknown types silently get default capability values (all False)
instead of being flagged as unknown. The `unknown_capability_nodes` warning
(from the fix above) would never fire. Recommendations may be wrong for
unregistered node types.

FIX DIRECTION:
Either:
1. Remove the `try/except` in the handler (since it's dead code), and
   document that unknown nodes get default capabilities.
2. Or change `registry_runtime.resolve_capability` to raise for unknown
   node types, and handle the exception in the handler to flag them.
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/optimization.py
FUNCTION:    optimize_execution_handler
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Build execution waves via `PipelineGraph(pipeline_cfg).execution_waves`.

WHAT IT ACTUALLY DOES:
Calls `_ir_to_pipeline_config(graph)` then `PipelineGraph(pipeline_cfg)`.
For a graph with no edges (disconnected nodes), `PipelineGraph` should
produce one wave per node (each node is independent). The `max_wave_size`
would be `len(graph.nodes)` and `can_parallelize` would be `True` if
there are 2+ nodes.

This is correct behavior — disconnected nodes CAN be parallelised.
However, the recommendation says "Enable parallel=True: N wave(s) contain
multiple independent nodes" — for a disconnected graph, this is technically
correct but potentially misleading (the nodes are disconnected, not just
parallel branches of a DAG).

THE BUG / RISK:
Low severity: the recommendation is technically correct but may mislead
callers into thinking the graph has meaningful parallel branches when it
is actually disconnected (no data flow between nodes).

EVIDENCE:
Lines ~115–120: wave summary and parallelism recommendation.

REPRODUCTION SCENARIO:
Pass a graph with 3 nodes and no edges. Response: `can_parallelize=True`,
recommendation says "Enable parallel=True: 1 wave contains 3 independent nodes."
The nodes are disconnected, not parallel branches.

IMPACT:
Potentially misleading recommendation. No functional impact.

FIX DIRECTION:
Add a check: if `len(graph.edges) == 0 and len(graph.nodes) > 1`, add a
note that the graph is disconnected.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `resolve_capability` never raises (it returns defaults for unknown types), making the handler's `except Exception: cap = None` dead code — nodes with unknown types silently get default capability values instead of being flagged, producing wrong recommendations. |
