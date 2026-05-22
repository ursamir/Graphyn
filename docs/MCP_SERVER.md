# MCP Server

The MCP server makes the platform natively operable by AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/). It exposes 15 tools over stdio transport.

**File:** `app/mcp/`  
**Transport:** stdio (JSON-RPC on stdin/stdout, logs to stderr)  
**Auth:** optional `GRAPHYN_API_TOKEN` env var

---

## Starting the Server

```bash
graphyn mcp
GRAPHYN_API_TOKEN=secret graphyn mcp
python -m app.mcp.server
```

---

## Module Structure

```
app/mcp/
├── server.py          # startup, stdio loop, tool dispatch
├── auth.py            # check_auth() — Bearer token middleware
├── tool_registry.py   # register_all_tools() — 15 tools
└── handlers/
    ├── discovery.py   # list_nodes
    ├── graph.py       # generate_graph, validate_graph, get_graph_schema,
    │                  #   get_graph_capability_summary, get_event_schema
    ├── execution.py   # execute_pipeline
    ├── artifacts.py   # inspect_run
    ├── run_control.py # pause_run, resume_run, cancel_run
    ├── provenance.py  # list_artifacts, get_artifact_lineage, replay_run
    └── optimization.py # optimize_execution
```

---

## Authentication

Token from `GRAPHYN_API_TOKEN` env var. Expected at `arguments._meta.auth_token`. Empty token = no auth. Wrong/absent = `{"error_type": "unauthorized"}`.

---

## All 15 Tools

| Tool | Handler | Delegates to |
|---|---|---|
| `list_nodes` | `discovery.py` | `get_registry()` |
| `generate_graph` | `graph.py` | `Pipeline`, `PipelineNode`, `load_ir` |
| `validate_graph` | `graph.py` | `load_ir()` |
| `get_graph_schema` | `graph.py` | `GraphIR.model_json_schema()` |
| `get_graph_capability_summary` | `graph.py` | registry + two-step resolution |
| `get_event_schema` | `graph.py` | static dict |
| `execute_pipeline` | `execution.py` | `run_pipeline_ir()`, `RunManager` |
| `inspect_run` | `artifacts.py` | workspace filesystem |
| `pause_run` | `run_control.py` | `get_active_run(run_id).pause()` |
| `resume_run` | `run_control.py` | `get_active_run(run_id).resume()` |
| `cancel_run` | `run_control.py` | `get_active_run(run_id).cancel()` |
| `list_artifacts` | `provenance.py` | `ArtifactStore.list()` |
| `get_artifact_lineage` | `provenance.py` | `ProvenanceStore.get_lineage()` |
| `replay_run` | `provenance.py` | `load_ir_from_file()`, `run_pipeline_ir()`, `RunManager` |
| `optimize_execution` | `optimization.py` | `PipelineGraph`, `_resolve_capability()` |

---

## Tool Reference

### `list_nodes`

Discover registered node types with full schemas and capability metadata.

**Dispatch table (priority order):**

| Arguments | Returns |
|---|---|
| `list_types: true` | `{"port_data_types": [...]}` |
| `node_type` + `schema_only: true` | `{"config_schema": {...}}` |
| `node_type` alone | Full 10-field node schema |
| `output_type` + `direction` | Compatible nodes |
| `capability_filter` (invalid key) | `{"error_type": "invalid_filter_key"}` |
| `category` / `capability_filter` | Filtered node list |
| no args | All nodes |

**10 capability fields per node:** `requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`, `memory_requirements`, `dependency_requirements`, `batch_support`.

---

### `generate_graph`

Build a validated `GraphIR` from a node list.

**Arguments:** `nodes` (required), `edges` (optional — auto-chains if omitted), `seed`, `name`, `description`.

**Errors:** `unknown_node_type`, `invalid_node_config`, `ir_validation_error`

---

### `validate_graph`

**Arguments:** `graph` (required) — a GraphIR JSON dict.

**Returns:** `{"valid": true, "node_count": N, "errors": []}` or `{"valid": false, ...}`

---

### `get_graph_schema`

Returns the JSON Schema for the `GraphIR` model. No arguments.

---

### `get_graph_capability_summary`

Aggregate capability flags across all nodes in a graph.

**Arguments:** `graph` (required).

**Returns:** `{"any_requires_gpu", "all_support_cpu", "all_support_edge", "all_deterministic", "any_batch_support"}`

Uses two-step resolution: `IRNode.capability_metadata` override → `NodeMetadata` fallback.

---

### `get_event_schema`

Returns the schema for all NDJSON event types emitted during execution. No arguments.

---

### `execute_pipeline`

Execute a pipeline. Returns `run_id` within 500ms; execution proceeds asynchronously.

**Arguments:** `graph` (required), `use_cache` (default `true`), `streaming` (default `false`).

**Returns:** `{"run_id": "...", "status": "started"}` or `{"valid": false, "errors": [...]}`

---

### `inspect_run`

Inspect run metadata, logs, graph, and checkpoints.

| Arguments | Returns |
|---|---|
| no `run_id` | `{"runs": [...]}` newest-first |
| `run_id` only | full `meta.json` |
| `run_id` + `status_only: true` | `{"status": "..."}` |
| `run_id` + `logs: true` | `{"logs": [...]}` |
| `run_id` + `graph: true` | `{"graph": {...}}` |
| `run_id` + `checkpoints: true` | `{"checkpoints": [...]}` |
| `run_id` + `node_id` | `{"manifest": {...}}` |

---

### `pause_run` / `resume_run` / `cancel_run`

Control an active run. Only works on currently running pipelines (same process).

**Arguments:** `run_id` (required).

**Returns:** `{"run_id": "...", "status": "paused|running|cancelled"}` or `{"error_type": "run_not_active"}`

---

### `list_artifacts`

Query the artifact store.

**Arguments:** `run_id` (optional), `node_type` (optional), `artifact_type` (optional).

**Returns:** Array of `ArtifactRecord` objects.

---

### `get_artifact_lineage`

Get the upstream lineage tree for an artifact.

**Arguments:** `artifact_id` (required).

**Returns:** Lineage tree dict. Never raises — returns error nodes for missing records.

---

### `replay_run`

Re-execute a prior run using its stored `graph.json`.

**Arguments:** `run_id` (required).

**Returns:** `{"run_id": "...", "status": "started"}` or `{"error_type": "graph_not_found"}`

---

### `optimize_execution`

Analyze a graph and return hardware placement recommendations and wave analysis.

**Arguments:** `graph` (required).

**Returns:** Wave analysis, capability hints, hardware placement recommendations.

---

## Error Contract

All handlers return structured JSON — never raw exceptions.

| `error_type` | Trigger |
|---|---|
| `unknown_tool` | Unregistered tool |
| `unauthorized` | Bad/missing auth token |
| `unknown_node_type` | Node not in registry |
| `invalid_filter_key` | Unknown capability key |
| `invalid_direction` | Not `"input"` or `"output"` |
| `ir_validation_error` | `load_ir()` failure |
| `invalid_node_config` | Config Pydantic failure |
| `unknown_run_id` | Run dir doesn't exist |
| `artifact_not_found` | Artifact file missing |
| `checkpoint_not_found` | Node checkpoint missing |
| `run_not_active` | Run not in active registry |
| `missing_argument` | Required argument absent |
| `graph_not_found` | `graph.json` missing for the run |
| `store_error` | `ArtifactStore` or `ProvenanceStore` raised |
| `replay_error` | Unexpected error during replay setup |
