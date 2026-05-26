# Functional Review — app/mcp/handlers/graph.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/graph.py
FUNCTION:    generate_graph_handler
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Generate a validated GraphIR from a node list. Step 1: validate all
node_type values. Step 2: validate all node configs. Step 3: construct
via Pipeline/PipelineNode.

WHAT IT ACTUALLY DOES:
Step 1 iterates over `node_specs` and checks `if node_type not in registry`.
If `node_type` is `None` (the caller omitted the `node_type` key from a
node spec), `spec.get("node_type")` returns `None`. The check
`if None not in registry` evaluates to `True` (None is not a registered
type), so the handler returns `{"error_type": "unknown_node_type",
"message": "Node type 'None' is not registered."}`.

This is technically correct behavior (None is not a valid node type), but
the error message `"Node type 'None' is not registered."` is confusing —
it should say `"node_type is required for each node specification"`.

More critically: Step 2 calls `spec.get("node_type")` again and then
`registry.get_class(node_type)`. If `node_type` is `None` and Step 1
somehow passed (e.g. if the registry check is bypassed), `registry.get_class(None)`
would raise a `KeyError` or `TypeError`. But since Step 1 catches `None`
first, this is not reachable in practice.

THE BUG / RISK:
Misleading error message when `node_type` is missing from a node spec.
The message says `"Node type 'None' is not registered"` instead of
`"node_type is required"`.

EVIDENCE:
Lines ~130–137:
```python
for spec in node_specs:
    node_type = spec.get("node_type")  # returns None if key absent
    if node_type not in registry:
        return {
            "error_type": "unknown_node_type",
            "message": f"Node type '{node_type}' is not registered.",
            ...
        }
```

REPRODUCTION SCENARIO:
Call `generate_graph` with `{"nodes": [{"config": {}}]}` (no `node_type`).
Response: `{"error_type": "unknown_node_type", "message": "Node type 'None' is not registered."}`.

IMPACT:
Confusing error message. No functional impact — the error is returned correctly.

FIX DIRECTION:
```python
node_type = spec.get("node_type")
if not node_type:
    return {"error": True, "error_type": "missing_argument",
            "message": "Each node specification must include a 'node_type' field."}
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/graph.py
FUNCTION:    generate_graph_handler
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle explicit edges (Step 4): rebuild GraphIR with explicit edges,
preserving all other fields.

WHAT IT ACTUALLY DOES:
When `edges` is provided, calls `pipeline.to_ir()` to get the auto-chained
graph, then rebuilds `GraphIR` with the explicit edges. The auto-chained
edges from `pipeline.to_ir()` are discarded and replaced with `ir_edges`.

However, if `edges` is an empty list `[]` (not `None`), the condition
`if edges is not None:` is `True`, so the handler enters the explicit-edges
branch and rebuilds `GraphIR` with zero edges. This produces a valid
GraphIR with no connections between nodes — which may or may not be what
the caller intended.

THE BUG / RISK:
Ambiguous semantics: `edges=[]` means "no edges" (disconnected graph),
while `edges=None` (omitted) means "auto-chain". A caller that passes
`edges=[]` expecting auto-chaining gets a disconnected graph instead.
This is a silent wrong result — the graph is valid but not what was intended.

EVIDENCE:
Lines ~175–176:
```python
if edges is not None:
    # ... rebuild with ir_edges (which is empty if edges=[])
```

REPRODUCTION SCENARIO:
Call `generate_graph` with `{"nodes": [...], "edges": []}`. Response is
a valid GraphIR with no edges — nodes are disconnected. Execution would
produce no data flow between nodes.

IMPACT:
Silent wrong result: caller gets a disconnected graph when they may have
intended auto-chaining. The graph passes validation (disconnected graphs
are valid IR), so no error is raised.

FIX DIRECTION:
Document that `edges=[]` means "no edges" (disconnected graph). Or treat
`edges=[]` the same as `edges=None` (auto-chain):
```python
if edges:  # truthy check — empty list falls through to auto-chain
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/graph.py
FUNCTION:    generate_graph_handler
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate the final graph via `load_ir()` before returning (Step 5).

WHAT IT ACTUALLY DOES:
Calls `dump_ir(graph)` to serialise the graph to a dict, then calls
`load_ir(graph_dict)` to re-parse and validate it. This is a round-trip
serialisation: construct → serialise → deserialise → validate. The
`load_ir` call is redundant if `GraphIR` construction already validates
via Pydantic's `model_validator`. The double validation adds latency for
large graphs.

THE BUG / RISK:
Performance: double serialisation/deserialisation for every `generate_graph`
call. For a 29-node graph, this is two full Pydantic model constructions.
Not a correctness bug — the validation is correct.

EVIDENCE:
Lines ~196–200:
```python
graph_dict = dump_ir(graph)
load_ir(graph_dict)  # second full parse
```

REPRODUCTION SCENARIO:
Generate a 29-node graph. Two full Pydantic model constructions occur.

IMPACT:
Latency overhead. Not a correctness bug.

FIX DIRECTION:
The double validation is intentional (defense in depth). Accept the
overhead or remove the `load_ir` call if `GraphIR` construction is
already fully validated.
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/graph.py
FUNCTION:    get_graph_capability_summary_handler
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Aggregate capability metadata for a graph. Returns five boolean fields.

WHAT IT ACTUALLY DOES:
For each `ir_node` in `graph.nodes`, if `ir_node.capability_metadata` is
`None`, calls `registry.get_metadata(ir_node.node_type)`. If the node type
is not registered, returns `{"error_type": "unknown_node_type", ...}` and
stops processing. This means if node 5 of 10 is unregistered, the first
4 nodes are processed and then the function returns an error — the partial
results are discarded.

This is correct behavior (can't aggregate if a node is unknown). However,
the error return is inside the `for` loop, which means the function returns
immediately on the first unknown node type. This is documented behavior.

THE BUG / RISK:
No bug — the behavior is correct. However, the error response uses
`"error_type": "unknown_node_type"` which is consistent with the error
contract. The only concern is that the error message says "Node type '...'
is not registered" but does not indicate which node in the graph caused
the error (no `node_index` or `node_id` field).

EVIDENCE:
Lines ~280–287:
```python
except Exception:
    return {
        "error": True,
        "error_type": "unknown_node_type",
        "message": f"Node type '{ir_node.node_type}' is not registered.",
        "node_type": ir_node.node_type,
    }
```
No `node_id` field in the error response.

REPRODUCTION SCENARIO:
Graph has 10 nodes; node 5 has an unregistered type. Error response
includes `node_type` but not `node_id` (the IR node's ID field).

IMPACT:
Caller cannot identify which node in the graph caused the error without
cross-referencing `node_type` against the graph. Minor UX issue.

FIX DIRECTION:
Add `"node_id": ir_node.id` to the error response.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `edges=[]` (empty list) is treated as "no edges" rather than "auto-chain" — produces a silently disconnected graph that passes validation but has no data flow between nodes. |
