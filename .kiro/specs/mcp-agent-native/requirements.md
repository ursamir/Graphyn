# Requirements Document — MCP + Agent-Native Architecture (Phase 2)

## Introduction

This document captures the requirements for **Phase 2** of the six-phase platform evolution roadmap.

Phase 2 makes the platform natively operable by AI agents via the **Model Context Protocol (MCP)**. The MCP layer is introduced as first-class architecture — not an adapter bolted onto existing interfaces. It exposes node schemas, graph schemas, capability metadata, execution APIs, validation APIs, and artifact APIs through a machine-readable interface that allows agents to discover nodes, generate workflows, validate graphs, execute pipelines, and inspect artifacts without any frontend interaction.

Phase 2 builds directly on the Phase 1 foundations:
- `GraphIR` / `IRNode` / `IREdge` / `IRCapabilityMetadata` (canonical graph contract)
- `run_pipeline_ir()` (primary execution entry point)
- `NodeMetadata` capability fields (`requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`)
- NDJSON event streaming (extended to MCP event streams)
- `GraphIR` stored per run at `workspace/runs/<run_id>/graph.json` (artifact MCP will expose)

All 421 Phase 1 tests must not regress. All existing public APIs, SDK surface, CLI commands, and REST endpoints must remain fully functional throughout this phase.

---

## Glossary

- **MCP** — Model Context Protocol. The open protocol that standardises how AI agents interact with tools and data sources. The MCP layer in this platform exposes tools that agents call to operate the workflow engine.
- **MCP_Server** — The server process that implements the MCP protocol and registers all platform tools. Lives at `app/mcp/server.py`.
- **MCP_Tool** — A named, schema-described callable exposed by the MCP_Server. Agents invoke tools by name with structured arguments.
- **MCP_Tool_Registry** — The component that registers all MCP tools at server startup and maps tool names to handler functions.
- **Tool_Handler** — A Python function that implements the logic for a single MCP tool. All Tool_Handlers delegate to the SDK or existing core components.
- **Node_Discovery_Tool** — The MCP tool that returns the full catalogue of registered node types with their schemas and capability metadata.
- **Graph_Generation_Tool** — The MCP tool that accepts a structured workflow description and returns a validated `GraphIR` JSON document.
- **Graph_Validation_Tool** — The MCP tool that accepts a `GraphIR` JSON document and returns a structured validation result.
- **Execution_Tool** — The MCP tool that accepts a `GraphIR` JSON document and executes the pipeline, returning a run ID and streaming events.
- **Artifact_Tool** — The MCP tool that exposes run metadata, logs, graph snapshots, and output artifacts for a given run ID.
- **Capability_Filter** — A query mechanism that allows agents to filter nodes by capability metadata fields (e.g. `supports_edge=true`, `requires_gpu=false`).
- **MCP_Event_Stream** — The NDJSON event stream produced during pipeline execution, extended with MCP-compatible framing for agent consumption.
- **GraphIR** — The canonical graph intermediate representation defined in `app/core/ir/models.py`. The contract between all platform interfaces.
- **IRCapabilityMetadata** — The Pydantic model in `app/core/ir/models.py` carrying machine-readable capability hints for a node instance.
- **NodeMetadata** — The Pydantic model in `app/core/nodes/metadata.py` describing a node's identity, ports, config schema, and capability fields.
- **SDK** — The Python SDK at `app/core/sdk.py`. The single source of truth for all business logic. MCP delegates to the SDK.
- **run_pipeline_ir** — The primary execution entry point in `app/core/pipeline.py`. All execution paths, including MCP, delegate here.
- **RunManager** — The component in `app/core/run_manager.py` managing run lifecycle, metadata, and artifact persistence.
- **NodeRegistry** — The singleton registry populated by AutoDiscovery at startup. Maps node type strings to node classes and metadata.
- **REST_API** — The existing FastAPI application at `app/api/main.py`. Preserved and unchanged by this phase.
- **NDJSON** — Newline-delimited JSON. The streaming event format used by the existing pipeline execution path and extended for MCP.
- **Run_Artifact** — Any file produced by a pipeline run: `graph.json`, `meta.json`, `logs.json`, checkpoint manifests.
- **Workspace** — The runtime data root at `workspace/` (configurable via `GRAPHYN_PROJECT_DIR`). Runs are stored at `workspace/runs/<run_id>/`.

---

## Current Architecture (Preserved — Must Not Regress)

The following Phase 1 components are the foundation for Phase 2 and must remain fully functional:

| Component | Location | Phase 2 Role |
|---|---|---|
| `GraphIR`, `IRNode`, `IREdge`, `IRCapabilityMetadata` | `app/core/ir/models.py` | MCP graph schema source of truth |
| `load_ir()`, `dump_ir()` | `app/core/ir/loader.py` | MCP graph serialization/deserialization |
| `run_pipeline_ir()` | `app/core/pipeline.py` | MCP execution delegate |
| `NodeMetadata` with capability fields | `app/core/nodes/metadata.py` | MCP node schema and capability exposure |
| `NodeRegistry`, `AutoDiscovery` | `app/core/nodes/registry.py`, `discovery.py` | MCP node catalogue source |
| `Pipeline`, `PipelineNode` | `app/core/sdk.py` | MCP graph construction delegate |
| `RunManager` | `app/core/run_manager.py` | MCP artifact access |
| NDJSON event streaming | `app/core/logger.py` | Extended for MCP event streams |
| `GraphIR` stored at `workspace/runs/<run_id>/graph.json` | `app/core/run_manager.py` | MCP artifact exposure |
| REST API (`/api/v1/`) | `app/api/` | Preserved, unchanged |
| CLI (`audiobuilder`) | `app/cli/main.py` | Preserved, unchanged |
| 421 passing tests | `tests/` | Must not regress |

---

## Requirements

### Requirement 1: MCP Server

**User Story:** As an AI agent operator, I want a running MCP server that exposes all platform capabilities as named tools, so that agents can discover and invoke platform operations through a standard protocol without writing custom integration code.

#### Acceptance Criteria

1. THE MCP_Server SHALL implement the Model Context Protocol using the `mcp` Python library and register all platform tools at startup before accepting any tool invocations.
2. THE MCP_Server SHALL expose a tool manifest — accessible via the MCP `tools/list` method — listing all registered MCP tools with their names, descriptions, and JSON Schema input schemas.
3. IF any tool registration fails during startup, THEN THE MCP_Server SHALL log the failure at ERROR level and exit with a non-zero status code rather than starting in a partially-registered state.
4. IF a tool invocation references an unregistered tool name, THEN THE MCP_Server SHALL return a structured MCP error response containing `error_type: "unknown_tool"`, the unrecognised tool name, and a `available_tools` list of all registered tool names.
5. THE MCP_Server SHALL be launchable as a standalone process via `python -m app.mcp.server` independently of the REST API.
6. THE MCP_Server SHALL be launchable via a CLI entry point (`audiobuilder mcp`) without requiring the REST API to be running.
7. WHILE the MCP_Server is running, THE MCP_Server SHALL delegate all business logic to the SDK or existing core components and SHALL NOT duplicate pipeline execution, validation, or registry logic.
8. THE MCP_Server SHALL support stdio transport as the primary MCP transport mechanism, reading JSON-RPC messages from stdin and writing responses to stdout.
9. WHERE an `GRAPHYN_API_TOKEN` environment variable is set and non-empty, THE MCP_Server SHALL require the token to be present in the `_meta.auth_token` field of every tool invocation; IF the token is absent or incorrect, THEN THE MCP_Server SHALL return a structured error with `error_type: "unauthorized"` without executing the tool.
10. WHERE `GRAPHYN_API_TOKEN` is unset or empty, THE MCP_Server SHALL execute tool invocations without requiring authentication.
11. THE MCP_Server SHALL log all tool invocations (tool name, timestamp) and their outcomes (success or error type) at INFO level to stderr, using the existing structured logging format from `app/core/logger.py`.

---

### Requirement 2: Node Discovery

**User Story:** As an AI agent, I want to discover all available node types with their full schemas and capability metadata, so that I can select appropriate nodes when generating workflows without needing access to source code or documentation.

#### Acceptance Criteria

1. THE Node_Discovery_Tool SHALL return the complete list of registered node types from the NodeRegistry, including for each node: `node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`, `config_schema`, and `capability_metadata`.
2. THE Node_Discovery_Tool SHALL return capability metadata for each node using the same seven boolean fields exposed by the existing REST API: `requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`.
3. WHEN a `category` filter argument is provided to the Node_Discovery_Tool, THE Node_Discovery_Tool SHALL return only nodes whose `category` field exactly matches the provided string value; WHEN the filter matches no nodes, THE Node_Discovery_Tool SHALL return an empty list (not an error).
4. WHEN a `capability_filter` argument is provided to the Node_Discovery_Tool as a dict mapping capability field names to boolean values, THE Node_Discovery_Tool SHALL return only nodes whose resolved capability metadata has each specified field equal to the specified boolean value; IF a `capability_filter` key is not one of the seven capability fields, THEN THE Node_Discovery_Tool SHALL return a structured error with `error_type: "invalid_filter_key"` and the unrecognised key name.
5. WHEN a `node_type` argument is provided to the Node_Discovery_Tool without other flags, THE Node_Discovery_Tool SHALL return the full schema for that single node type.
6. IF a `node_type` argument references an unregistered node type, THEN THE Node_Discovery_Tool SHALL return a structured error with `error_type: "unknown_node_type"`, the unrecognised type string, and an `available_types` list of all registered node type names.
7. WHEN a `node_type` argument and a `schema_only: true` flag are provided to the Node_Discovery_Tool, THE Node_Discovery_Tool SHALL return only the config JSON Schema for that node type, derived from the node's `NodeConfig` Pydantic model via `model_json_schema()`.
8. WHEN a `list_types: true` flag is provided to the Node_Discovery_Tool, THE Node_Discovery_Tool SHALL return a list of all registered port data type class names from the NodeRegistry.
9. WHEN an `output_type` argument and a `direction` argument of `"input"` or `"output"` are provided to the Node_Discovery_Tool, THE Node_Discovery_Tool SHALL return all node types whose port in the specified direction accepts or produces the given data type name; IF `direction` is not `"input"` or `"output"`, THEN THE Node_Discovery_Tool SHALL return a structured error with `error_type: "invalid_direction"`.
10. THE Node_Discovery_Tool SHALL delegate all registry queries to the NodeRegistry singleton via `get_registry()` and SHALL NOT maintain a separate node catalogue.
11. FOR ALL node types registered in the NodeRegistry, the capability metadata returned by the Node_Discovery_Tool SHALL be field-for-field identical to the `capability_metadata` object returned by `GET /api/v1/nodes` for the same node type (consistency property).

---

### Requirement 3: Graph Generation and Validation

**User Story:** As an AI agent, I want to construct and validate workflow graphs using structured tool calls, so that I can programmatically generate correct, executable pipelines without relying on a visual editor or manual JSON authoring.

#### Acceptance Criteria

1. THE Graph_Generation_Tool SHALL accept a `nodes` argument — a list of node specifications each containing `node_type` (string) and optional `config` (dict) — and an optional `edges` argument — a list of edge specifications each containing `src_id`, `src_port`, `dst_id`, and `dst_port` — and SHALL return a validated `GraphIR` JSON document on success.
2. WHEN no `edges` argument is provided to the Graph_Generation_Tool and the `nodes` list contains two or more entries, THE Graph_Generation_Tool SHALL auto-chain nodes in the order provided, connecting each node's `output` port to the next node's `input` port; WHEN the `nodes` list contains exactly one entry, THE Graph_Generation_Tool SHALL generate a single-node graph with no edges.
3. THE Graph_Generation_Tool SHALL validate the generated `GraphIR` against the IR schema via `load_ir()` before returning it; IF validation fails, THE Graph_Generation_Tool SHALL return a structured error with `error_type: "ir_validation_error"` and an `errors` list.
4. IF the Graph_Generation_Tool receives a node specification with a `node_type` not registered in the NodeRegistry, THEN THE Graph_Generation_Tool SHALL return a structured error with `error_type: "unknown_node_type"` and the invalid type name, without attempting graph construction.
5. IF the Graph_Generation_Tool receives a node specification with a `config` that fails the node's `NodeConfig` Pydantic validation, THEN THE Graph_Generation_Tool SHALL return a structured error with `error_type: "invalid_node_config"`, the failing `node_type`, the failing field name, and the Pydantic validation message.
6. THE Graph_Validation_Tool SHALL accept a `graph` argument containing a `GraphIR` JSON document and SHALL return a structured result containing: `valid` (boolean), `node_count` (integer, 0 when `valid` is false), and `errors` (list of error strings, empty when `valid` is true).
7. WHEN the Graph_Validation_Tool receives a `GraphIR` document with a duplicate node ID, THE Graph_Validation_Tool SHALL return `valid: false` with an error string identifying the duplicate ID.
8. WHEN the Graph_Validation_Tool receives a `GraphIR` document with an edge whose `src_id` or `dst_id` does not match any node ID in the graph, THE Graph_Validation_Tool SHALL return `valid: false` with an error string identifying the invalid reference.
9. WHEN the Graph_Validation_Tool receives a `GraphIR` document whose `schema_version` major component does not match the supported major version in `app/core/ir/loader.py`, THE Graph_Validation_Tool SHALL return `valid: false` with an error string identifying the version mismatch; a minor version difference SHALL produce `valid: true` with no errors (matching loader behavior).
10. THE Graph_Generation_Tool SHALL delegate graph construction to `Pipeline` and `PipelineNode` in `app/core/sdk.py` and SHALL NOT reimplement IR construction logic.
11. THE Graph_Validation_Tool SHALL delegate validation to `load_ir()` from `app/core/ir/loader.py` and SHALL NOT reimplement IR validation logic.
12. FOR ALL valid `GraphIR` documents produced by the Graph_Generation_Tool, calling `load_ir(dump_ir(graph))` SHALL produce a `GraphIR` object whose `model_dump(mode="json")` is equal to the original document's `model_dump(mode="json")` (round-trip property).
13. THE MCP_Server SHALL expose a `get_graph_schema` tool that returns the JSON Schema for the `GraphIR` model, generated via `GraphIR.model_json_schema()`, enabling agents to understand the graph format without invoking the generation tool.

---

### Requirement 4: Pipeline Execution

**User Story:** As an AI agent, I want to execute a pipeline by submitting a GraphIR document and receive structured execution events, so that I can monitor progress and detect errors programmatically without polling a UI.

#### Acceptance Criteria

1. THE Execution_Tool SHALL accept a `graph` argument containing a `GraphIR` JSON document and execute the pipeline by delegating to `run_pipeline_ir()`.
2. WHEN the Execution_Tool is invoked with a valid `GraphIR` document, THE Execution_Tool SHALL return a response containing `run_id` within 500 milliseconds and execute the pipeline asynchronously in a background thread.
3. WHILE a pipeline is executing, THE MCP_Event_Stream SHALL emit NDJSON events in the following order: `pipeline_start` as the first event, zero or more interleaved `node_start`, `node_end`, and `node_error` events, and exactly one terminal event (`done` or `error`) as the final event.
4. THE MCP_Event_Stream SHALL use the same event schema as the existing NDJSON streaming protocol: each event is a JSON object with `type` (string) and `timestamp` (UTC ISO 8601 string) fields plus event-specific fields.
5. WHEN a `node_start` event is emitted, THE MCP_Event_Stream SHALL include `node_type` (string) and `node_index` (integer) fields. WHEN a `node_end` event is emitted, THE MCP_Event_Stream SHALL include `node_type` (string), `node_index` (integer), and `duration_s` (float) fields.
6. WHEN a `node_error` event is emitted, THE MCP_Event_Stream SHALL include `node_type` (string), `node_index` (integer), `error_message` (string), and `error_type` (string) fields.
7. WHEN execution completes successfully, THE MCP_Event_Stream SHALL emit a `done` event as the final event containing `run_id` (string) and `duration_s` (float) fields.
8. WHEN execution fails, THE MCP_Event_Stream SHALL emit an `error` event as the final event containing a `message` (string) field.
9. WHEN the `streaming` argument is omitted or set to false, THE Execution_Tool SHALL use the standard `run_pipeline_ir()` execution path. WHEN the `streaming` argument is set to true, THE Execution_Tool SHALL use streaming execution mode via `NodeExecutor.execute_stream`.
10. THE Execution_Tool SHALL accept an optional `use_cache` boolean argument (default `true`) and pass it to `run_pipeline_ir()`.
11. IF the Execution_Tool receives a `graph` argument that fails `load_ir()` validation, THEN THE Execution_Tool SHALL return a structured error with `valid: false` and an `errors` list without starting execution.
12. THE Execution_Tool SHALL store the `GraphIR` in the run directory at `workspace/runs/<run_id>/graph.json` via the existing `RunManager.save_graph_ir()` method.
13. THE Execution_Tool SHALL NOT duplicate execution logic from `run_pipeline_ir()` and SHALL NOT reimplement node lifecycle management, caching, or checkpointing.
14. FOR ALL `GraphIR` documents for which the Graph_Validation_Tool returns `valid: true`, the Execution_Tool SHALL accept and begin executing the document without returning a validation error (consistency property).

---

### Requirement 5: Run Inspection and Artifact Access

**User Story:** As an AI agent, I want to inspect completed pipeline runs and access their artifacts, so that I can retrieve outputs, diagnose failures, and use run results as inputs to subsequent agent decisions.

#### Acceptance Criteria

1. THE Artifact_Tool SHALL return a list of all runs in the workspace (regardless of status), ordered newest first by `created_at`, with each entry containing: `run_id`, `status`, `created_at`, `duration_s`, and `num_nodes`.
2. WHEN the Artifact_Tool is invoked with a `run_id` argument and no other flags, THE Artifact_Tool SHALL return the full contents of `workspace/runs/<run_id>/meta.json` as a structured object.
3. WHEN the Artifact_Tool is invoked with a `run_id` argument and `logs: true`, THE Artifact_Tool SHALL return the contents of `workspace/runs/<run_id>/logs.json` as a structured object; IF `logs.json` does not exist, THE Artifact_Tool SHALL return a structured error with `error_type: "artifact_not_found"` and `artifact: "logs.json"`.
4. WHEN the Artifact_Tool is invoked with a `run_id` argument and `graph: true`, THE Artifact_Tool SHALL return the contents of `workspace/runs/<run_id>/graph.json` as a structured object.
5. IF a `run_id` argument references a directory that does not exist under `workspace/runs/`, THEN THE Artifact_Tool SHALL return a structured error with `error_type: "unknown_run_id"` and the unrecognised run ID string.
6. IF a `run_id` argument references a run directory that exists but does not contain a `graph.json` file, THEN THE Artifact_Tool SHALL return a structured error with `error_type: "artifact_not_found"` and `artifact: "graph.json"`.
7. WHEN the Artifact_Tool is invoked with a `run_id` argument and `checkpoints: true`, THE Artifact_Tool SHALL return the list of node IDs for which a checkpoint directory exists under `workspace/runs/<run_id>/checkpoints/`.
8. WHEN the Artifact_Tool is invoked with a `run_id` argument and a `node_id` argument, THE Artifact_Tool SHALL return the checkpoint manifest for that node from `workspace/runs/<run_id>/checkpoints/<node_id>/manifest.json`; IF the `node_id` does not have a checkpoint, THE Artifact_Tool SHALL return a structured error with `error_type: "checkpoint_not_found"` and the `node_id`.
9. WHEN the Artifact_Tool is invoked with a `run_id` argument and `status_only: true`, THE Artifact_Tool SHALL return a single-field response `{"status": "<value>"}` where `<value>` is one of `"running"`, `"completed"`, or `"failed"`, read from `meta.json`.
10. THE Artifact_Tool SHALL resolve all workspace paths using `os.path.join(os.environ.get("GRAPHYN_PROJECT_DIR", "workspace"), "runs", run_id)` and SHALL NOT introduce any other file system access pattern.
11. FOR ALL run IDs returned by the Artifact_Tool's list operation, a subsequent invocation of the Artifact_Tool with that `run_id` SHALL return either the run metadata or a structured error — it SHALL NOT raise an unhandled exception (consistency property).
12. IF a `run_id` argument references a run directory that exists but does not contain a `logs.json` file and `logs: true` is set, THEN THE Artifact_Tool SHALL return a structured error with `error_type: "artifact_not_found"` and `artifact: "logs.json"`.

---

### Requirement 6: SDK Delegation Constraint

**User Story:** As a platform maintainer, I want all MCP tool handlers to delegate business logic to the SDK and existing core components, so that the MCP layer remains a thin interface and business logic is never duplicated across interfaces.

#### Acceptance Criteria

1. THE MCP_Server SHALL NOT contain pipeline execution logic; WHEN a pipeline execution is requested, THE MCP_Server SHALL delegate to `run_pipeline_ir()` in `app/core/pipeline.py`.
2. THE MCP_Server SHALL NOT contain graph construction logic; WHEN a graph is to be constructed, THE MCP_Server SHALL delegate to `Pipeline` and `PipelineNode` in `app/core/sdk.py`.
3. THE MCP_Server SHALL NOT contain graph validation logic; WHEN a graph is to be validated, THE MCP_Server SHALL delegate to `load_ir()` in `app/core/ir/loader.py`.
4. THE MCP_Server SHALL NOT contain node registry logic; WHEN node metadata is to be queried, THE MCP_Server SHALL delegate to the `NodeRegistry` singleton via `get_registry()`.
5. THE MCP_Server SHALL NOT contain run artifact access logic; WHEN run artifacts are to be accessed, THE MCP_Server SHALL use the same workspace path conventions as `RunManager` (i.e., `workspace/runs/<run_id>/`).
6. WHEN the SDK or core components raise a `ValidationError`, `IRVersionError`, `IRValidationError`, or any other exception, THE MCP_Server SHALL catch the exception and return a structured MCP error response containing `error_type` (the exception class name), `message` (the string representation of the exception), and SHALL NOT propagate the raw exception to the agent.
7. THE MCP_Server SHALL use the existing `PipelineLogger` for structured event emission during execution and SHALL NOT implement a separate logging mechanism.
8. THE MCP_Server SHALL use the existing `RunManager` for run lifecycle management and SHALL NOT implement a separate run tracking mechanism.
9. IF a new node type is registered in the NodeRegistry within the same running process instance, THEN the Node_Discovery_Tool SHALL return that node type in subsequent discovery calls without requiring any changes to the MCP layer (registry-driven extensibility property).

---

### Requirement 7: Machine Operability Design

**User Story:** As an AI agent, I want all node schemas, graph schemas, and capability metadata to be structured for machine consumption, so that I can reason about node compatibility, hardware requirements, and execution constraints without parsing human-readable documentation.

#### Acceptance Criteria

1. THE MCP_Server SHALL expose all node config schemas as JSON Schema documents conforming to JSON Schema Draft 2020-12, generated via Pydantic's `model_json_schema()`, containing no free-text descriptions as the sole source of constraint information.
2. THE MCP_Server SHALL expose the seven `IRCapabilityMetadata` boolean fields (`requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`) as a structured filter interface in the Node_Discovery_Tool's `capability_filter` argument, allowing agents to query nodes by any combination of those fields.
3. WHEN an agent queries the Node_Discovery_Tool with `capability_filter: {"supports_edge": true}`, THE Node_Discovery_Tool SHALL return only nodes whose resolved capability metadata has `supports_edge` equal to `true`; the resolution rule in criterion 8 applies.
4. WHEN an agent queries the Node_Discovery_Tool with `capability_filter: {"requires_gpu": false}`, THE Node_Discovery_Tool SHALL return only nodes whose resolved capability metadata has `requires_gpu` equal to `false`; the resolution rule in criterion 8 applies.
5. THE MCP_Server SHALL expose a `get_graph_schema` tool that returns the JSON Schema for the `GraphIR` model generated via `GraphIR.model_json_schema()`, so that agents can validate self-generated graphs before submitting them for execution.
6. THE MCP_Server SHALL expose a `get_event_schema` tool that returns a structured document describing the six NDJSON event types (`pipeline_start`, `node_start`, `node_end`, `node_error`, `done`, `error`) with their field names and types, so that agents can parse execution events without hardcoding field names.
7. WHEN the `get_graph_capability_summary` tool is invoked with a `graph` argument containing a `GraphIR` JSON document, THE MCP_Server SHALL return a structured response containing: `any_requires_gpu` (true if any node requires GPU), `all_support_cpu` (true if all nodes support CPU), `all_support_edge` (true if all nodes support edge deployment), and `all_deterministic` (true if all nodes are deterministic); IF any node type in the graph is not registered, THE MCP_Server SHALL return a structured error with `error_type: "unknown_node_type"`.
8. THE MCP_Server SHALL resolve capability metadata for each node using the following two-step rule: (1) if the `IRNode.capability_metadata` field is non-null, use those values; (2) otherwise, use the corresponding fields from the `NodeMetadata` returned by the NodeRegistry for that node type. This rule is identical to `_resolve_capability()` in `app/core/pipeline.py`.
9. FOR ALL `GraphIR` documents, the `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, and `all_deterministic` values returned by `get_graph_capability_summary` SHALL be derivable by applying the resolution rule in criterion 8 to each node's capability metadata as returned by the Node_Discovery_Tool for the same node types (consistency property).

---

### Requirement 8: Backward Compatibility and Non-Regression

**User Story:** As a platform user, I want the introduction of the MCP layer to have no impact on existing REST API, SDK, and CLI interfaces, so that current integrations continue to work without modification.

#### Acceptance Criteria

1. THE MCP_Server SHALL be introduced as a new, independent process and SHALL NOT modify any existing REST API router, SDK method, or CLI command.
2. WHEN the MCP_Server is not running, THE REST_API SHALL produce responses identical to its pre-Phase-2 behavior for all existing endpoints, as verified by the 421-test suite passing without modification.
3. WHEN the MCP_Server is not running, THE SDK SHALL produce outputs identical to its pre-Phase-2 behavior for all existing methods, as verified by the 421-test suite passing without modification.
4. WHEN the MCP_Server is not running, THE CLI SHALL produce outputs identical to its pre-Phase-2 behavior for all existing commands, as verified by the 421-test suite passing without modification.
5. THE MCP_Server SHALL NOT modify `app/core/pipeline.py`, `app/core/sdk.py`, `app/core/ir/models.py`, or `app/core/ir/loader.py`; it SHALL only import from these modules.
6. THE MCP_Server SHALL NOT modify any existing REST API router file; it SHALL be implemented entirely within `app/mcp/`.
7. IF the 421 Phase 1 tests are run after Phase 2 implementation with no changes to test source files or runner configuration, THEN all 421 tests SHALL pass.
8. THE MCP_Server SHALL use the same `GRAPHYN_PROJECT_DIR` environment variable as the rest of the platform for workspace root resolution.
9. WHERE `GRAPHYN_API_TOKEN` is set and non-empty, THE MCP_Server SHALL require the token for authentication; WHERE `GRAPHYN_API_TOKEN` is unset or empty, THE MCP_Server SHALL not require authentication — matching the REST API's behavior exactly.
