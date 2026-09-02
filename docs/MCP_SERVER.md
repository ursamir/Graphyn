# MCP Server

The MCP server makes the platform natively operable by AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/). It exposes 20 tools over stdio transport.

**File:** `app/mcp/`  
**Transport:** stdio (JSON-RPC on stdin/stdout, logs to stderr)  
**Auth:** `GRAPHYN_API_TOKEN`; fail-closed when `GRAPHYN_AUTH_REQUIRED=1` or `GRAPHYN_ENV=production`

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
├── tool_registry.py   # register_all_tools() — 20 tools
├── handlers/
    ├── discovery.py   # list_nodes
    ├── graph.py       # generate_graph, validate_graph, get_graph_schema,
    │                  #   get_graph_capability_summary, get_event_schema
    ├── execution.py   # execute_pipeline
    ├── artifacts.py   # inspect_run
    ├── run_control.py # pause_run, resume_run, cancel_run
    ├── provenance.py  # list_artifacts, get_artifact_lineage, replay_run
    ├── optimization.py # optimize_execution
    ├── plugins.py      # install_plugin, list_plugins, manage_plugin
    └── secrets.py      # secrets_list, secrets_set
```

---

## Authentication

Token from `GRAPHYN_API_TOKEN`. Expected at `arguments._meta.auth_token`. In development, empty token = no auth. `GRAPHYN_AUTH_REQUIRED=1` or `GRAPHYN_ENV=production|staging` forbids an empty token (fail-closed). Wrong/absent = `{"error_type": "unauthorized"}`.

---

## All 20 Tools

| Tool | Handler | Delegates to |
|---|---|---|
| `list_nodes` | `discovery.py` | `get_registry()` |
| `generate_graph` | `graph.py` | `Pipeline`, `PipelineNode`, `load_ir` |
| `validate_graph` | `graph.py` | `load_ir()` |
| `get_graph_schema` | `graph.py` | `GraphIR.model_json_schema()` |
| `get_graph_capability_summary` | `graph.py` | registry + two-step resolution |
| `get_event_schema` | `graph.py` | static dict |
| `execute_pipeline` | `execution.py` | `get_backend().execute()`, `RunManager` |
| `inspect_run` | `artifacts.py` | workspace filesystem |
| `pause_run` | `run_control.py` | `get_active_run(run_id).pause()` |
| `resume_run` | `run_control.py` | `get_active_run(run_id).resume()` |
| `cancel_run` | `run_control.py` | `get_active_run(run_id).cancel()` |
| `list_artifacts` | `provenance.py` | `ArtifactStore.list()` |
| `get_artifact_lineage` | `provenance.py` | `ProvenanceStore.get_lineage()` |
| `replay_run` | `provenance.py` | `load_ir_from_file()`, `get_backend().execute()`, `RunManager` |
| `optimize_execution` | `optimization.py` | `PipelineGraph`, `_resolve_capability()` |
| `install_plugin` | `plugins.py` | `PluginManager.install` + `load_enabled_plugins` |
| `list_plugins` | `plugins.py` | `PluginManager.list_installed` |
| `manage_plugin` | `plugins.py` | `enable` / `disable` / `uninstall` |
| `secrets_list` | `secrets.py` | names only under GRAPHYN_HOME/secrets |
| `secrets_set` | `secrets.py` | stores value; result does not echo it |

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

**Arguments:** `nodes` (required; each may include `id`, `config`, `event_trigger`), `edges` (optional — auto-chains if omitted; each may include `condition`), `seed`, `name`, `description`.

Node `id` and `event_trigger` and edge `condition` are preserved in the returned GraphIR (needed for IF branches and schedules).

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

Execute a pipeline. Returns `run_id` within 500ms; execution proceeds asynchronously in a background thread. If the background thread raises an unhandled exception, the run is marked failed in `meta.json`.

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

**`pause_run` returns:** `{"run_id": "...", "status": "paused"}` — the run will pause at the next node boundary.

**`resume_run` returns:** `{"run_id": "...", "status": "running"}`.

**`cancel_run` returns:** `{"run_id": "...", "status": "cancelled"}`.

**Error:** `{"error_type": "run_not_active"}` — distinguishes completed runs from runs that never existed.

`OSError` during pause/resume persistence is returned as `{"error_type": "run_control_error"}`.

---

### `list_artifacts`

Query the artifact store.

**Arguments:** `run_id` (optional), `node_type` (optional), `artifact_type` (optional), `limit` (optional, default `200`).

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

**Returns:** Wave analysis, capability hints, hardware placement recommendations. Includes `is_disconnected` field (true if the graph has no edges). Emits `unknown_capability_nodes` warning for node types not in the registry.

---

### `install_plugin`

Install a plugin from a local path, git URL, HTTP archive, or index name. Reloads enabled plugins so `list_nodes` sees new types in-process. Remote sources honor `GRAPHYN_PLUGIN_ALLOWED_SOURCES`.

**Arguments:** `source` (required), `upgrade` (default false), `expected_sha256` (optional).

**Returns:** `{name, version, enabled, node_types[]}`

### `list_plugins`

**Returns:** `{plugins: [{name, version, enabled, node_types[]}]}`

### `manage_plugin`

**Arguments:** `action` (`enable` | `disable` | `uninstall`), `name`.

### Agent loop (n8n-style)

1. `list_plugins` / `install_plugin` (local path or allowlisted source)
2. `list_nodes` — search/list node types including newly installed
3. `generate_graph` — branched edges (`condition`) and `event_trigger` for schedules
4. `validate_graph`
5. `execute_pipeline` → `inspect_run`

Native Slack/Email/GitHub nodes are out of v1; use `http_request` with `auth_env` (environment **variable names**, never secrets in IR) and `provider=mock` for tests.

---


### `secrets_list`

Returns `{"names": ["OPENAI_API_KEY", ...]}`. Never returns values.

### `secrets_set`

**Arguments:** `name` (required), `value` (required; accepted for local MCP).

**Returns:** `{"ok": true, "name": "..."}` — value is not echoed.

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
| `registry_error` | `registry.list_nodes()` failed in discovery handler |
| `invalid_action` | `manage_plugin` action not enable/disable/uninstall |
| `PluginInstallError` / `PluginNotFoundError` | plugin lifecycle failures |
