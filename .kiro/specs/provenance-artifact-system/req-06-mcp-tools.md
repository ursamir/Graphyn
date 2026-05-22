# req-06 — MCP Provenance Tools

## Introduction

This document specifies three new MCP tools added to the platform's MCP layer: `list_artifacts`, `get_artifact_lineage`, and `replay_run`. These tools are implemented in a new handler file `app/mcp/handlers/provenance.py` and registered in `app/mcp/tool_registry.py`.

All handlers follow the existing MCP pattern: thin delegation shells over `ArtifactStore`, `ProvenanceStore`, and `run_pipeline_ir`. No handler should exceed ~30 lines. All handlers return structured JSON dicts and never raise unhandled exceptions.

**Cross-references:** req-01 (`ArtifactStore` is the data source), req-02 (`ProvenanceStore` provides lineage), req-05 (REST API exposes the same operations).

---

## Requirement 1: `list_artifacts` Tool

**User Story:** As an AI agent, I want to list artifacts with optional filters, so that I can discover what a pipeline produced without reading the filesystem directly.

### Acceptance Criteria

1. THE MCP server SHALL expose a `list_artifacts` tool registered in `app/mcp/tool_registry.py`.

2. THE `list_artifacts` tool SHALL accept the following optional input parameters:
   - `run_id: str` — filter by run ID
   - `node_type: str` — filter by node type
   - `artifact_type: str` — filter by artifact type
   - `_meta: dict` — auth token (standard MCP auth field)

3. WHEN `list_artifacts` is called, THE handler SHALL call `ArtifactStore.list(run_id=..., node_type=..., artifact_type=...)` and return:
   ```json
   {
     "artifacts": [
       {
         "artifact_id": "...",
         "artifact_type": "...",
         "node_id": "...",
         "node_type": "...",
         "run_id": "...",
         "content_hash": "...",
         "created_at": "..."
       }
     ],
     "count": N
   }
   ```

4. WHEN no artifacts match the filters, THE handler SHALL return `{"artifacts": [], "count": 0}`.

5. THE handler SHALL never raise an unhandled exception — all errors SHALL be returned as `{"error": true, "error_type": "...", "message": "..."}`.

---

## Requirement 2: `get_artifact_lineage` Tool

**User Story:** As an AI agent, I want to retrieve the full lineage tree of an artifact, so that I can understand the provenance of any pipeline output.

### Acceptance Criteria

1. THE MCP server SHALL expose a `get_artifact_lineage` tool registered in `app/mcp/tool_registry.py`.

2. THE `get_artifact_lineage` tool SHALL accept the following input parameters:
   - `artifact_id: str` (required) — the artifact to trace
   - `_meta: dict` — auth token

3. WHEN `get_artifact_lineage` is called, THE handler SHALL call `ProvenanceStore.get_lineage(artifact_id)` and return:
   ```json
   {
     "artifact_id": "...",
     "lineage": { /* lineage tree as specified in req-02 §Requirement 4 */ }
   }
   ```

4. WHEN `artifact_id` is missing from the input, THE handler SHALL return `{"error": true, "error_type": "missing_argument", "message": "artifact_id is required"}`.

5. WHEN the provenance store has no record for `artifact_id`, THE handler SHALL return the partial lineage tree (not an error response) — consistent with req-02 §Requirement 4.3.

---

## Requirement 3: `replay_run` Tool

**User Story:** As an AI agent, I want to replay a run from its stored graph, so that I can reproduce results or re-run a pipeline programmatically.

### Acceptance Criteria

1. THE MCP server SHALL expose a `replay_run` tool registered in `app/mcp/tool_registry.py`.

2. THE `replay_run` tool SHALL accept the following input parameters:
   - `run_id: str` (required) — the original run to replay
   - `_meta: dict` — auth token

3. WHEN `replay_run` is called, THE handler SHALL:
   a. Locate `workspace/runs/{run_id}/graph.json`
   b. Load the graph via `load_ir_from_file()`
   c. Submit execution to a `ThreadPoolExecutor` (non-blocking, same pattern as `execute_pipeline_handler`)
   d. Return `{"run_id": "<new_run_id>", "status": "started"}` immediately

4. WHEN `run_id` is missing from the input, THE handler SHALL return `{"error": true, "error_type": "missing_argument", "message": "run_id is required"}`.

5. WHEN `workspace/runs/{run_id}/graph.json` does not exist, THE handler SHALL return `{"error": true, "error_type": "graph_not_found", "message": "graph.json not found for run <run_id>"}`.

6. WHEN `workspace/runs/{run_id}/` does not exist, THE handler SHALL return `{"error": true, "error_type": "unknown_run_id", "message": "Run <run_id> not found"}`.

---

## Requirement 4: Tool Registration

**User Story:** As a platform developer, I want the new MCP tools registered alongside the existing 11 tools, so that agents discover them automatically via `list_tools`.

### Acceptance Criteria

1. THE `register_all_tools()` function in `app/mcp/tool_registry.py` SHALL be updated to import and register `list_artifacts`, `get_artifact_lineage`, and `replay_run` from `app/mcp/handlers/provenance.py`.

2. THE total tool count after Phase 4 SHALL be 14 (11 existing + 3 new).

3. THE new tools SHALL follow the existing error contract defined in `mcp-server.md`:
   - New `error_type` values: `"graph_not_found"`, `"missing_argument"`
   - Existing `error_type` values (`"unknown_run_id"`, `"unauthorized"`) SHALL be reused where applicable.

4. THE `app/mcp/handlers/provenance.py` module SHALL define:
   - `LIST_ARTIFACTS_DESCRIPTION: str`
   - `LIST_ARTIFACTS_SCHEMA: dict` (JSON Schema)
   - `list_artifacts_handler(arguments: dict) -> dict`
   - `GET_ARTIFACT_LINEAGE_DESCRIPTION: str`
   - `GET_ARTIFACT_LINEAGE_SCHEMA: dict`
   - `get_artifact_lineage_handler(arguments: dict) -> dict`
   - `REPLAY_RUN_DESCRIPTION: str`
   - `REPLAY_RUN_SCHEMA: dict`
   - `replay_run_handler(arguments: dict) -> dict`
