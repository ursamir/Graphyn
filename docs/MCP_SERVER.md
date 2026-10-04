# MCP Server

> **Inventory (2026-09-28):** `tool_registry.py` registers **~77 tools** (+`accept_proposal` when human-approval enabled). Legacy `secrets_list` / `secrets_set` removed — use credential tools. See [`MCP_AGENT_PACK_COVERAGE.md`](./MCP_AGENT_PACK_COVERAGE.md).


The MCP server makes the platform natively operable by AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/). It exposes **~77 tools by default** (+1 when `GRAPHYN_MCP_HUMAN_APPROVAL=1`, which enables `accept_proposal`) over stdio transport. Prefer `tool_registry.py` / MCP_AGENT_PACK_COVERAGE.md as source of truth.

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
├── server.py          # startup, stdio loop, tool dispatch, get_tool()
├── auth.py            # check_auth() — Bearer token middleware
├── tool_registry.py   # register_all_tools() — ~77 tools
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
    ├── credentials.py  # list/create/get/update/revoke_credential
    ├── proposals.py    # propose_graph, list/get/accept/reject_proposal
    └── journey/        # pipelines, runs, templates, models, schedules,
                        #   readiness, catalog, notifications (one file each)
```

---

## Authentication

Token from `GRAPHYN_API_TOKEN`. Expected at `arguments._meta.auth_token`. In development, empty token = no auth. `GRAPHYN_AUTH_REQUIRED=1` or `GRAPHYN_ENV=production|staging` forbids an empty token (fail-closed). Wrong/absent = `{"error_type": "unauthorized"}`.

---

## Tool inventory (see MCP_AGENT_PACK_COVERAGE for full list)

> **77 tools** are registered by default (78 `register("` calls in `app/mcp/tool_registry.py`; `accept_proposal` is registered only when `GRAPHYN_MCP_HUMAN_APPROVAL=1`). The historical “29 tools” table below is **partial** — journey/ship/audit/credentials/notifications tools were added later; full list in [MCP_AGENT_PACK_COVERAGE.md](./MCP_AGENT_PACK_COVERAGE.md).

### Core tools (original set)

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
| `replay_run` | `provenance.py` | `app.core.runs.run_replay.start_replay()` → `get_backend().execute()` |
| `optimize_execution` | `optimization.py` | `PipelineGraph`, `_resolve_capability()` |
| `install_plugin` | `plugins.py` | `PluginManager.install` + `load_enabled_plugins` |
| `list_plugins` | `plugins.py` | `PluginManager.list_installed` |
| `manage_plugin` | `plugins.py` | `enable` / `disable` / `uninstall` |
| `list_credentials` | `credentials.py` | redacted connection metadata |
| `create_credential` | `credentials.py` | create connection; never echoes secrets |
| `get_credential` | `credentials.py` | redacted |
| `update_credential` | `credentials.py` | rotate/update; never echoes secrets |
| `revoke_credential` | `credentials.py` | soft-revoke or delete |
| `propose_graph` | `proposals.py` | `create_proposal` (agentic store) |
| `list_proposals` | `proposals.py` | `list_proposals` |
| `get_proposal` | `proposals.py` | `get_proposal` |
| `accept_proposal` | `proposals.py` | `accept_proposal` (same as UI; **only registered when `GRAPHYN_MCP_HUMAN_APPROVAL=1`**) |
| `reject_proposal` | `proposals.py` | `reject_proposal` (same as UI) |
| `list_experiments` | `workspace.py` | `experiments.list_experiments` |
| `get_trace` | `workspace.py` | `trace.assemble_trace` |
| `list_projects` | `workspace.py` | datasets/output folder listing |
| `list_data_inputs` | `workspace.py` | datasets/input label listing |

---

## Intentional omissions

Schedules (`list_schedules`, `upsert_schedule`, `enable_schedule`, `delete_schedule`, `run_schedule_now`) and worker/job observe (`list_workers`, `list_jobs`) are MCP tools as well as REST. Document ingest remains REST-oriented; see `API_REFERENCE.md` for the HTTP routes.

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

IR validation uses the shared helper `validate_graph_ir()` (registry types, configs, ports, cycles) — same depth as `graphyn validate --graph`.

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

Before execution the graph goes through the same shared preparation as REST `/pipelines/run*`, the SDK and the CLI (`app/core/execution/graph_prepare.py`): workspace path rewire (`examples/**/data` → `workspace/datasets/input/<slug>/…`, outputs → `workspace/artifacts/<slug>/…`), project / version_tag stamping, inline-secret refusal, and deep validation (VAL-003 — error findings refuse the run). A `run.start` audit event is recorded (`actor` argument, default `mcp`).

**Arguments:** `graph` (required), `use_cache` (default `true`), `streaming` (default `false`), optional `project`, `version_tag`, `actor`.

**Returns:** `{"run_id": "...", "status": "pending", "accepted": true}` (same `pending` vocabulary as REST `run-async`; `accepted` replaces the legacy `status: "started"` ack) or `{"valid": false, "errors": [...], "error": true, "error_type": "ir_validation_error"}` / `{"error_type": "inline_secret_error"}`

---

### `inspect_run`

Inspect run metadata, logs, graph, and checkpoints. `run_id` may be a unique prefix (≥ 8 chars) — as for `get_run`, `get_run_outputs`, `register_model` and `request_model_prod` (the registry stores the full id); an ambiguous prefix returns a validation error listing the matches.

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

Re-execute a prior run from its stored **logical** graph (`graph.logical.json`, or `graph.json` with run scoping undone) — same seed/config, re-scoped to the new run. Shares `app/core/runs/run_replay.start_replay` with REST `POST /runs/{id}/replay`.

**Arguments:** `run_id` (required), `check_inputs`, `force`, `actor` (default `mcp`).

**Returns:** `{"run_id": "...", "replay_of": "...", "status": "pending", "graph_hash": "...", "accepted": true}`, or `{"error_type": "graph_not_found" | "unknown_run_id" | "inputs_changed" (with "changes") | "replay_error"}`. The new run carries `replay_of` / `trigger: "replay"`; audit `run.replay`.

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


### Credential tools

Use `list_credentials` / `create_credential` / `get_credential` / `update_credential` / `revoke_credential`. Raw secrets are never returned. Ops env bootstrap: CLI `graphyn secrets` (see `docs/ops/CREDENTIAL_STORE.md`). Legacy `secrets_list` / `secrets_set` are removed.

### `secrets_set`

**Arguments:** `name` (required), `value` (required; accepted for local MCP).

**Returns:** `{"ok": true, "name": "..."}` — value is not echoed.

---

### `propose_graph`

Create a human-in-the-loop GraphIR proposal (does **not** mutate the live Builder canvas).

**Arguments:** `summary` (required), `graph` (required GraphIR object), optional `actor`, `base_graph`, `base_graph_hash`.

**Returns:** proposal id + status `pending`. Accept/reject via MCP
`accept_proposal` / `reject_proposal` or REST (`POST /api/v1/proposals/{id}/accept|reject`).

### `list_proposals` / `get_proposal`

List (optional `status` filter) or fetch one proposal by id.

### `accept_proposal` / `reject_proposal`

Resolve a pending proposal (same core as the console). **Arguments:** `id` (required);
optional `actor`; `reject_proposal` also accepts `reason`.

---

## Error Contract

All handlers return structured JSON — never raw exceptions. Every failure is
returned as a `CallToolResult` with **`isError: true`**: auth failures,
unknown tools, handler exceptions (`{"error": true, "error_type": "<ExceptionClass>", "message": …}`),
and handler `{"error": true, …}` envelopes. Successful results carry
`isError: false`. The server log line is `outcome=success|error|exception|unauthorized|unknown_tool`.

`list_runs` uses the shared run lister (`app/core/runs/run_listing.py`) — same
order as REST `GET /runs` and `graphyn runs list` (`created_at` desc,
`run_id` tiebreak), project filter with graph.json inference, and the
PERS-020 store guard (`error_type: store_corrupt`).

| `error_type` | Trigger |
|---|---|
| `unknown_tool` | Unregistered tool |
| `store_corrupt` | PERS-020 readiness reports a corrupt critical index (`list_runs`) |
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


## Dependency pin (API image)

Install the MCP client/server SDK via the package extra only:

```bash
pip install -e ".[mcp]"   # pins mcp==1.27.0
```

Do **not** run unconstrained `pip install mcp` inside the `graphyn-api` image:
newer SDK releases may pull incompatible `fastapi`/`starlette` and break the API.
Prefer a host venv for MCP agentic selftests (`examples/mcp_agent_selftest/`).
