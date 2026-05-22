# Implementation Plan: MCP + Agent-Native Architecture (Phase 2)

## Overview

Introduce `app/mcp/` as a thin delegation shell over the Phase 1 SDK and core components. The module exposes 8 MCP tools via stdio transport, adds `pipeline_done` / `pipeline_error` to `PipelineLogger`, and wires a new `audiobuilder mcp` CLI subcommand. Zero modifications to any Phase 1 file except `app/core/logger.py` (two method additions) and `app/cli/main.py` (one subcommand addition). All 421 Phase 1 tests must continue to pass.

---

## Tasks

- [x] 1. Extend `PipelineLogger` with Phase 2 event methods
  - [x] 1.1 Add `pipeline_done(run_id, duration)` and `pipeline_error(message)` methods to `app/core/logger.py`
    - Implement `pipeline_done`: calls `_emit_structured` with `{"type": "done", "run_id": run_id, "duration_s": duration, "timestamp": ...}`
    - Implement `pipeline_error`: calls `_emit_structured` with `{"type": "error", "message": message, "timestamp": ...}`
    - Both methods follow the existing `_emit_structured` pattern — no plain-text print, appended to `self.logs`, forwarded to `self.queue` if set
    - _Requirements: 4.7, 4.8_

  - [x] 1.2 Write unit tests for `pipeline_done` and `pipeline_error`
    - Verify `done` event is appended to `logger.logs` with correct fields
    - Verify `error` event is appended to `logger.logs` with correct fields
    - Verify both events are forwarded to the queue when one is set
    - _Requirements: 4.7, 4.8_

- [x] 2. Scaffold the `app/mcp/` package
  - [x] 2.1 Create `app/mcp/__init__.py` (empty) and `app/mcp/__main__.py`
    - `__init__.py`: empty file marking the package
    - `__main__.py`: single import and `if __name__ == "__main__": main()` calling `app.mcp.server.main`
    - Create `app/mcp/handlers/__init__.py` (empty)
    - _Requirements: 1.5_

  - [x] 2.2 Implement `app/mcp/auth.py` — token authentication middleware
    - Read `GRAPHYN_API_TOKEN` from environment at module import time into `_TOKEN`
    - Implement `check_auth(arguments) -> dict | None`: returns `None` when auth passes or is unconfigured; returns `{"error": True, "error_type": "unauthorized", "message": ...}` when token is missing or wrong
    - Token is read from `arguments.get("_meta", {}).get("auth_token", "")`
    - _Requirements: 1.9, 1.10, 8.9_

  - [x] 2.3 Write unit tests for `check_auth`
    - Test: `GRAPHYN_API_TOKEN` unset → `check_auth({})` returns `None`
    - Test: token set, correct token provided → returns `None`
    - Test: token set, wrong token → returns dict with `error_type: "unauthorized"`
    - Test: token set, `_meta` absent → returns dict with `error_type: "unauthorized"`
    - _Requirements: 1.9, 1.10_

- [x] 3. Implement `app/mcp/server.py` — MCP server core
  - [x] 3.1 Implement the MCP server module with tool dispatch
    - Import `mcp.server.lowlevel.Server`, `mcp.server.stdio.stdio_server`, `mcp.types`, `mcp.server.models.InitializationOptions`
    - Create `_server = Server("audiobuilder-mcp")` and `_TOOLS: dict[str, dict]` at module level
    - Implement `_register(name, description, input_schema, handler)` to populate `_TOOLS`
    - Implement `@_server.list_tools()` handler returning `[types.Tool(...) for name, info in _TOOLS.items()]`
    - Implement `@_server.call_tool()` handler: run `check_auth` → unknown tool check → dispatch via `run_in_executor(None, lambda: handler(arguments))` → return `[types.TextContent(type="text", text=json.dumps(result))]`
    - Implement `_startup()`: calls `register_all_tools(_register)`, exits with code 1 on failure
    - Implement `main()`: configures `logging.basicConfig` to `stderr`, calls `_startup()`, then `asyncio.run(_run_server())`
    - Log all tool invocations at INFO level to stderr: `tool=<name> outcome=<success|error_type>`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 1.9, 1.11_

  - [x] 3.2 Write unit tests for server dispatch
    - Test: unknown tool name → response contains `error_type: "unknown_tool"` and `available_tools` list
    - Test: auth failure → response contains `error_type: "unauthorized"` without executing handler
    - Test: valid tool dispatch → handler is called and result is JSON-serialized in `TextContent`
    - _Requirements: 1.4, 1.9_

- [x] 4. Implement `app/mcp/tool_registry.py`
  - [x] 4.1 Implement `register_all_tools(register)` to wire all 8 handlers
    - Import all handler functions, schemas, and descriptions from `handlers/discovery.py`, `handlers/graph.py`, `handlers/execution.py`, `handlers/artifacts.py`
    - Call `register(...)` for each of the 8 tools in order: `list_nodes`, `generate_graph`, `validate_graph`, `get_graph_schema`, `get_graph_capability_summary`, `get_event_schema`, `execute_pipeline`, `inspect_run`
    - _Requirements: 1.1, 1.2, 1.7_

- [x] 5. Implement `app/mcp/handlers/discovery.py` — `list_nodes` tool
  - [x] 5.1 Implement `list_nodes_handler` with all filter modes
    - Define `LIST_NODES_DESCRIPTION`, `LIST_NODES_SCHEMA`, and `_CAPABILITY_FIELDS` frozenset
    - Implement `_resolve_capability(ir_node_cap, node_meta) -> dict` using the two-step rule (IRNode override → NodeMetadata fallback)
    - Implement `_serialize_node_metadata(meta) -> dict` returning all 10 required fields: `node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`, `config_schema`, `capability_metadata`
    - Implement dispatch table in `list_nodes_handler`: `list_types` → port type names; `node_type + schema_only` → config schema only; `node_type` alone → full single-node schema; `output_type + direction` → compatible nodes; `capability_filter` validation → `invalid_filter_key` error; `category` filter; capability filter; no args → all nodes
    - Delegate all registry queries to `get_registry()` — no separate catalogue
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11_

  - [x] 5.2 Write unit tests for `list_nodes_handler`
    - Test: no args → returns all registered nodes with all 10 fields present
    - Test: `category` filter → all returned nodes have matching category
    - Test: `capability_filter` with valid key → all returned nodes satisfy filter
    - Test: `capability_filter` with invalid key → `error_type: "invalid_filter_key"`
    - Test: `node_type` for registered type → returns single node full schema
    - Test: `node_type` for unregistered type → `error_type: "unknown_node_type"` with `available_types`
    - Test: `node_type + schema_only: true` → returns only `config_schema`
    - Test: `list_types: true` → returns `port_data_types` list
    - Test: `output_type + direction: "output"` → returns compatible nodes
    - Test: `output_type + direction: "invalid"` → `error_type: "invalid_direction"`
    - _Requirements: 2.1–2.11_

  - [x] 5.3 Write property test for category filter correctness (Property 1)
    - **Property 1: Category filter returns only matching nodes**
    - Use `@given(category=st.sampled_from(...))` over all categories in the registry
    - Assert every returned node has `category == category`
    - Tag: `# Feature: mcp-agent-native, Property 1: Category filter returns only matching nodes`
    - **Validates: Requirements 2.3**

  - [x] 5.4 Write property test for capability filter correctness (Property 2)
    - **Property 2: Capability filter returns only matching nodes**
    - Use `@given(capability_filter=st.fixed_dictionaries({}, optional={k: st.booleans() for k in _CAPABILITY_KEYS}))` 
    - Assert every returned node's `capability_metadata` satisfies all filter key-value pairs
    - Tag: `# Feature: mcp-agent-native, Property 2: Capability filter returns only matching nodes`
    - **Validates: Requirements 2.4, 7.2, 7.3, 7.4**

- [x] 6. Implement `app/mcp/handlers/graph.py` — graph tools
  - [x] 6.1 Implement `generate_graph_handler`
    - Define `GENERATE_GRAPH_DESCRIPTION` and `GENERATE_GRAPH_SCHEMA` (JSON Schema with `nodes` required, optional `edges`, `seed`, `name`, `description`, `_meta`)
    - Validate all `node_type` values against registry before construction; return `error_type: "unknown_node_type"` on first unknown type
    - Validate all node `config` dicts via `node_class.Config.model_validate(config)`; return `error_type: "invalid_node_config"` with `node_type` and `validation_errors` on failure
    - Construct via `Pipeline(nodes=[PipelineNode(...)], seed=..., name=..., description=...)` and call `pipeline.to_ir()`
    - If explicit `edges` provided, rebuild `GraphIR` with `IREdge` objects replacing auto-chained edges
    - Validate final graph via `load_ir(dump_ir(graph))`; return `error_type: "ir_validation_error"` on failure
    - Return `dump_ir(graph)` on success
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.10, 3.12_

  - [x] 6.2 Implement `validate_graph_handler`
    - Define `VALIDATE_GRAPH_DESCRIPTION` and `VALIDATE_GRAPH_SCHEMA`
    - Call `load_ir(graph_dict)` inside try/except; catch `IRVersionError`, `pydantic.ValidationError`, `ValueError`, and generic `Exception`
    - Return `{"valid": True, "node_count": len(graph.nodes), "errors": []}` on success
    - Return `{"valid": False, "node_count": 0, "errors": [...]}` on any failure
    - _Requirements: 3.6, 3.7, 3.8, 3.9, 3.11_

  - [x] 6.3 Implement `get_graph_schema_handler`, `get_graph_capability_summary_handler`, and `get_event_schema_handler`
    - `get_graph_schema_handler`: return `GraphIR.model_json_schema()` directly
    - `get_graph_capability_summary_handler`: call `load_ir(graph_dict)`, iterate nodes applying two-step capability resolution, return `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, `all_deterministic`; return `error_type: "unknown_node_type"` if any node type is unregistered
    - `get_event_schema_handler`: return static dict describing all 6 NDJSON event types (`pipeline_start`, `node_start`, `node_end`, `node_error`, `done`, `error`) with their field names and types
    - Define all schemas and descriptions for each tool
    - _Requirements: 3.13, 7.5, 7.6, 7.7, 7.8, 7.9_

  - [x] 6.4 Write unit tests for graph tool handlers
    - Test `generate_graph_handler`: valid node list → returns dict with `schema_version`, `nodes`, `edges`
    - Test `generate_graph_handler`: unknown node type → `error_type: "unknown_node_type"`
    - Test `generate_graph_handler`: invalid node config → `error_type: "invalid_node_config"`
    - Test `generate_graph_handler`: explicit edges → graph uses provided edges not auto-chain
    - Test `validate_graph_handler`: valid graph dict → `{"valid": True, "node_count": N, "errors": []}`
    - Test `validate_graph_handler`: duplicate node ID → `valid: false` with error string
    - Test `validate_graph_handler`: invalid edge reference → `valid: false` with error string
    - Test `validate_graph_handler`: wrong major version → `valid: false` with version error
    - Test `get_graph_schema_handler`: returns dict with `"title": "GraphIR"`
    - Test `get_graph_capability_summary_handler`: valid graph → returns all 4 boolean fields
    - Test `get_graph_capability_summary_handler`: unknown node type in graph → `error_type: "unknown_node_type"`
    - Test `get_event_schema_handler`: returns dict with `event_types` list of 6 entries
    - _Requirements: 3.1–3.13, 7.5–7.9_

  - [x] 6.5 Write property test for graph generation round-trip (Property 4)
    - **Property 4: Graph generation round-trip**
    - Use `@given(node_types=st.lists(...), seed=st.integers(...))` over registered node types
    - Assert `load_ir(dump_ir(graph)).model_dump(mode="json") == graph_dict` for all valid generated graphs
    - Skip (return early) if `generate_graph_handler` returns an error (invalid configs)
    - Tag: `# Feature: mcp-agent-native, Property 4: Graph generation round-trip`
    - **Validates: Requirements 3.12**

  - [x] 6.6 Write property test for capability summary consistency (Property 7)
    - **Property 7: Capability summary consistency**
    - Use `@given(node_types=st.lists(..., min_size=1, max_size=5))` over registered node types
    - Compute expected values by calling `list_nodes_handler({"node_type": nt})` for each node type
    - Assert `get_graph_capability_summary_handler` result matches manually computed aggregates
    - Tag: `# Feature: mcp-agent-native, Property 7: Capability summary consistency`
    - **Validates: Requirements 7.9**

- [x] 7. Checkpoint — verify graph tools and discovery
  - Ensure all tests pass so far, ask the user if questions arise.

- [x] 8. Implement `app/mcp/handlers/execution.py` — `execute_pipeline` tool
  - [x] 8.1 Implement `execute_pipeline_handler`
    - Define `EXECUTE_PIPELINE_DESCRIPTION` and `EXECUTE_PIPELINE_SCHEMA` (JSON Schema with `graph` required, optional `use_cache`, `streaming`, `_meta`)
    - Validate `graph_dict` via `load_ir(graph_dict)`; return `{"valid": False, "errors": [...]}` on failure without starting execution
    - Allocate `RunManager()` to get `run_id`
    - Create `PipelineLogger(queue=event_queue)` with a `queue.Queue`
    - Submit `run_pipeline_ir(graph, logger=logger, use_cache=use_cache, checkpoint=False, streaming=streaming, observer=None, run_manager=run_manager)` to a `ThreadPoolExecutor(max_workers=1)`
    - Return `{"run_id": run_id, "status": "started"}` immediately (within 500 ms)
    - _Requirements: 4.1, 4.2, 4.9, 4.10, 4.11, 4.12, 4.13_

  - [x] 8.2 Write unit tests for `execute_pipeline_handler`
    - Test: invalid graph dict → returns `{"valid": False, "errors": [...]}` without starting execution
    - Test: valid graph dict → returns dict with `run_id` (string) and `status: "started"`
    - Test: `use_cache: false` → passed through to `run_pipeline_ir`
    - Test: response is returned before execution completes (timing check: < 500 ms)
    - _Requirements: 4.1, 4.2, 4.11, 4.14_

  - [x] 8.3 Write property test for validation/execution consistency (Property 5)
    - **Property 5: Validation and execution consistency**
    - Use `@given(node_types=st.lists(..., min_size=1, max_size=3))` over registered node types
    - For each generated graph where `validate_graph_handler` returns `valid: true`, assert `execute_pipeline_handler` returns a dict containing `run_id`
    - Skip if `generate_graph_handler` or `validate_graph_handler` returns an error
    - Tag: `# Feature: mcp-agent-native, Property 5: Validation and execution consistency`
    - **Validates: Requirements 4.14**

- [x] 9. Implement `app/mcp/handlers/artifacts.py` — `inspect_run` tool
  - [x] 9.1 Implement `inspect_run_handler`
    - Define `INSPECT_RUN_DESCRIPTION` and `INSPECT_RUN_SCHEMA`
    - Resolve workspace path via `os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")` — use `Path(_WORKSPACE) / "runs"` as `_RUNS_DIR`
    - List mode (no `run_id`): iterate `_RUNS_DIR`, read each `meta.json`, return `{"runs": [...]}` sorted newest-first; return `{"runs": []}` if directory does not exist
    - Single run mode: check `run_dir.exists()` → `error_type: "unknown_run_id"` if not found
    - `status_only: true` → read `meta.json`, return `{"status": ...}`
    - `logs: true` → read `logs.json`; return `error_type: "artifact_not_found"` with `artifact: "logs.json"` if missing
    - `graph: true` → read `graph.json`; return `error_type: "artifact_not_found"` with `artifact: "graph.json"` if missing
    - `checkpoints: true` → list `checkpoints/` subdirectories, return `{"checkpoints": [node_ids]}`
    - `node_id` provided → read `checkpoints/node_{node_id}/manifest.json`; return `error_type: "checkpoint_not_found"` if missing
    - Default (run_id only) → return full `meta.json` contents
    - Wrap every file read in try/except; never raise unhandled exceptions
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12_

  - [x] 9.2 Write unit tests for `inspect_run_handler`
    - Test: no `run_id` → returns `{"runs": [...]}` list
    - Test: no `run_id`, no runs directory → returns `{"runs": []}`
    - Test: unknown `run_id` → `error_type: "unknown_run_id"`
    - Test: valid `run_id`, no flags → returns `meta.json` contents
    - Test: `status_only: true` → returns `{"status": "completed"}`
    - Test: `logs: true`, logs exist → returns `{"logs": [...]}`
    - Test: `logs: true`, logs missing → `error_type: "artifact_not_found"`, `artifact: "logs.json"`
    - Test: `graph: true`, graph exists → returns `{"graph": {...}}`
    - Test: `graph: true`, graph missing → `error_type: "artifact_not_found"`, `artifact: "graph.json"`
    - Test: `checkpoints: true` → returns `{"checkpoints": [...]}`
    - Test: `node_id` with existing checkpoint → returns `{"manifest": {...}}`
    - Test: `node_id` with missing checkpoint → `error_type: "checkpoint_not_found"`
    - _Requirements: 5.1–5.12_

  - [x] 9.3 Write property test for run inspection exception safety (Property 6)
    - **Property 6: Run inspection exception safety**
    - Use `@given(flags=st.fixed_dictionaries({}, optional={"logs": st.booleans(), "graph": st.booleans(), "checkpoints": st.booleans(), "status_only": st.booleans()}))`
    - List all runs, pick first run ID, call `inspect_run_handler({"run_id": run_id, **flags})`
    - Assert result is a `dict` and if `result.get("error")` then `"error_type"` and `"message"` are present
    - Must never raise an unhandled exception
    - Tag: `# Feature: mcp-agent-native, Property 6: Run inspection exception safety`
    - **Validates: Requirements 5.11**

- [x] 10. Add `audiobuilder mcp` CLI subcommand to `app/cli/main.py`
  - [x] 10.1 Add `cmd_mcp` function and `mcp` subparser to `build_parser()`
    - Implement `cmd_mcp(args)`: calls `from app.mcp.server import main; main()` in-process (preferred over subprocess to share the NodeRegistry singleton)
    - Add `mcp_parser = subparsers.add_parser("mcp", help="Start the MCP server (stdio transport)", description=...)` in `build_parser()`
    - Set `mcp_parser.set_defaults(func=cmd_mcp)`
    - This is the only change to `app/cli/main.py`
    - _Requirements: 1.6, 8.1_

  - [x] 10.2 Write unit test for CLI `mcp` subcommand registration
    - Test: `build_parser()` includes `mcp` in available subcommands
    - Test: `args.func` for `mcp` subcommand is `cmd_mcp`
    - _Requirements: 1.6_

- [x] 11. Checkpoint — verify all handlers and CLI wiring
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Write integration tests in `tests/mcp/test_integration.py`
  - [x] 12.1 Implement end-to-end integration tests
    - Test: `list_nodes` returns same `capability_metadata` as `GET /api/v1/nodes` for all node types (node discovery consistency)
    - Test: `generate_graph` → `validate_graph` → `execute_pipeline` → `inspect_run` full chain works end-to-end
    - Test: auth — when `GRAPHYN_API_TOKEN` is set, tool invocations without token return `error_type: "unauthorized"`
    - Test: auth — when `GRAPHYN_API_TOKEN` is unset, tool invocations without token succeed
    - Test: `python -m app.mcp.server` import succeeds without error (startup smoke test)
    - _Requirements: 1.9, 1.10, 2.11, 4.14, 8.2, 8.3, 8.4_

- [x] 13. Write property tests in `tests/mcp/test_properties.py`
  - [x] 13.1 Consolidate all 7 property-based tests into `tests/mcp/test_properties.py`
    - Property 1: Category filter correctness (from task 5.3)
    - Property 2: Capability filter correctness (from task 5.4)
    - Property 3: Node discovery consistency — `list_nodes` vs `GET /api/v1/nodes` capability_metadata field-for-field identical for any registered node type
    - Property 4: Graph generation round-trip (from task 6.5)
    - Property 5: Validation/execution consistency (from task 8.3)
    - Property 6: Run inspection exception safety (from task 9.3)
    - Property 7: Capability summary consistency (from task 6.6)
    - Each test uses `@settings(max_examples=100)` minimum
    - Each test has the tag comment: `# Feature: mcp-agent-native, Property N: <text>`
    - _Requirements: 2.3, 2.4, 2.11, 3.12, 4.14, 5.11, 7.9_

  - [x] 13.2 Write property test for node discovery consistency (Property 3)
    - **Property 3: Node discovery consistency with REST API**
    - Use `@given(node_type=st.sampled_from([m.node_type for m in get_registry().list_nodes()]))`
    - Call `list_nodes_handler({"node_type": node_type})` and `api_list_nodes()` (from `app.api.routers.nodes`)
    - Assert `mcp_cap == api_cap` for the same node type
    - Tag: `# Feature: mcp-agent-native, Property 3: Node discovery consistency with REST API`
    - **Validates: Requirements 2.11**

- [x] 14. Write unit tests in `tests/mcp/test_unit.py`
  - [x] 14.1 Consolidate all handler unit tests into `tests/mcp/test_unit.py`
    - Collect unit tests from tasks 2.3, 3.2, 5.2, 6.4, 8.2, 9.2, 10.2 into a single organized test file
    - Add `tests/mcp/__init__.py` (empty) to make it a package
    - Organize tests by handler module using test classes or clear section comments
    - Ensure all error branches for all 8 tools are covered
    - _Requirements: 1.4, 1.9, 1.10, 2.1–2.11, 3.1–3.13, 4.1–4.14, 5.1–5.12, 7.5–7.9_

- [x] 15. Non-regression verification
  - [x] 15.1 Run the full Phase 1 test suite and confirm zero regressions
    - Run `venv/bin/pytest tests/ -v --ignore=tests/mcp` and verify all 421 tests pass
    - Fix any import-time side effects introduced by `app/mcp/` that could affect Phase 1 tests
    - _Requirements: 8.2, 8.3, 8.4, 8.7_

  - [x] 15.2 Run the full test suite including Phase 2 tests
    - Run `venv/bin/pytest tests/ -v` and verify all tests pass (421 Phase 1 + new Phase 2 tests)
    - _Requirements: 8.7_

- [x] 16. Final checkpoint — all tests pass
  - Ensure all 421 Phase 1 tests pass with zero regressions, all 7 property-based tests pass with 100+ iterations each, and `audiobuilder mcp` starts without error. Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- The design uses Python throughout — no language selection needed
- `app/core/logger.py` and `app/cli/main.py` are the only existing files modified; all other Phase 1 files are import-only
- All MCP handlers are synchronous Python functions dispatched via `run_in_executor` — the asyncio event loop is never blocked
- Logging goes to `stderr`; `stdout` is reserved for JSON-RPC framing (Req 1.11)
- The `mcp` Python library must be installed: `venv/bin/pip install mcp`
- Property tests in `tests/mcp/test_properties.py` each require `@settings(max_examples=100)` minimum
- Checkpoints at tasks 7 and 11 validate incremental progress before integration testing

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "2.3"] },
    { "id": 2, "tasks": ["3.1", "4.1"] },
    { "id": 3, "tasks": ["3.2", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4", "6.1", "6.2", "6.3"] },
    { "id": 5, "tasks": ["6.4", "6.5", "6.6", "8.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 8, "tasks": ["10.2", "12.1", "13.1"] },
    { "id": 9, "tasks": ["13.2", "14.1"] },
    { "id": 10, "tasks": ["15.1"] },
    { "id": 11, "tasks": ["15.2"] }
  ]
}
```
