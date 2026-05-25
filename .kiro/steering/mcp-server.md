---
inclusion: fileMatch
fileMatchPattern: "app/mcp/**"
---

# MCP Server

Thin delegation shell — all business logic stays in SDK/core. No handler should exceed ~30 lines.

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

## Start

```bash
graphyn mcp                                          # via CLI
python -m app.mcp.server                             # direct
GRAPHYN_API_TOKEN=s graphyn mcp                      # with auth
```

Transport: **stdio** — JSON-RPC on stdin/stdout. Logs to stderr only.

## Auth (`auth.py`)

Token from `GRAPHYN_API_TOKEN` env var. Expected at `arguments._meta.auth_token`. Empty token = no auth. Wrong/absent = `{"error_type": "unauthorized"}`.

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

## `list_nodes` Dispatch (priority order)

| Arguments | Returns |
|---|---|
| `list_types: true` | `{"port_data_types": [...]}` |
| `node_type` + `schema_only: true` | `{"config_schema": {...}}` |
| `node_type` alone | Full 10-field node schema |
| `output_type` + `direction` | Compatible nodes |
| `capability_filter` (invalid key) | `{"error_type": "invalid_filter_key"}` |
| `category` / `capability_filter` | Filtered node list |
| no args | All nodes |

**10 capability fields:** `requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`, `memory_requirements`, `dependency_requirements`, `batch_support`.

**`get_graph_capability_summary` returns:** `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, `all_deterministic`, `any_batch_support`.

## `inspect_run` Dispatch

| Arguments | Returns |
|---|---|
| no `run_id` | `{"runs": [...]}` newest-first |
| `run_id` only | full `meta.json` |
| `run_id` + `status_only: true` | `{"status": "..."}` |
| `run_id` + `logs: true` | `{"logs": [...]}` |
| `run_id` + `graph: true` | `{"graph": {...}}` |
| `run_id` + `checkpoints: true` | `{"checkpoints": [...]}` |
| `run_id` + `node_id` | `{"manifest": {...}}` |

## Error Contract

All handlers return structured JSON. Never raw exceptions.

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
| `missing_argument` | Required argument absent from input |
| `graph_not_found` | `graph.json` missing for the given run |
| `store_error` | `ArtifactStore` or `ProvenanceStore` raised an exception |
| `replay_error` | Unexpected error during replay setup |

## Open Issues in This Area

> All previously listed issues in this area have been resolved. See `docs/MASTER_ISSUE_REGISTRY.md` Resolved table.
