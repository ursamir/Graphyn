# req-05 — REST API and CLI

## Introduction

This document specifies the new REST API endpoints under `/api/v1/artifacts/` and the new `audiobuilder artifacts` CLI subcommand. Both interfaces delegate to `ArtifactStore` and `ProvenanceStore` — no business logic lives in the router or CLI handler.

The REST API follows the existing pattern in `app/api/routers/`: a thin `APIRouter` that reads from the workspace and returns JSON. The CLI follows the existing pattern in `app/cli/main.py`: a subparser with sub-subcommands.

**Cross-references:** req-01 (`ArtifactStore` is the data source), req-02 (`ProvenanceStore` provides lineage), req-03 (`RunManager` is used for replay).

---

## Requirement 1: Artifacts REST Router

**User Story:** As a frontend developer or API consumer, I want REST endpoints for artifact discovery and lineage, so that I can build tooling on top of the provenance system.

### Acceptance Criteria

1. THE platform SHALL provide a new router at `app/api/routers/artifacts.py` with `router = APIRouter(prefix="/artifacts", tags=["artifacts"])`.

2. THE `artifacts_router` SHALL be registered in `app/api/main.py` with `prefix="/api/v1"` and the standard `_deps` auth dependency.

3. THE router SHALL expose the following endpoints:

   **GET `/api/v1/artifacts`**
   - Query parameters: `run_id: str | None`, `node_type: str | None`, `artifact_type: str | None`
   - Returns: `list[dict]` — serialized `ArtifactRecord` objects matching all provided filters
   - WHEN no filters are provided, THE endpoint SHALL return all artifacts sorted by `created_at` descending

   **GET `/api/v1/artifacts/{artifact_id}`**
   - Returns: `dict` — serialized `ArtifactRecord`
   - WHEN `artifact_id` is not found, THE endpoint SHALL return HTTP 404 with `{"detail": "Artifact not found"}`

   **GET `/api/v1/artifacts/{artifact_id}/lineage`**
   - Returns: `dict` — the lineage tree as specified in req-02 §Requirement 4
   - WHEN `artifact_id` is not found in the provenance store, THE endpoint SHALL return the partial tree (not HTTP 404)

   **POST `/api/v1/artifacts/{artifact_id}/replay`**
   - Triggers a replay of the run that produced `artifact_id`
   - Returns: `{"run_id": "<new_run_id>", "status": "started"}`
   - WHEN `artifact_id` is not found, THE endpoint SHALL return HTTP 404
   - WHEN the `graph.json` for the original run is not found, THE endpoint SHALL return HTTP 422 with `{"detail": "graph.json not found for original run"}`
   - THE replay SHALL execute asynchronously (same pattern as `POST /api/v1/pipelines/run-async`)

4. THE router SHALL expose the following endpoints on the existing runs router (extend `app/api/routers/runs.py`):

   **GET `/api/v1/runs/{run_id}/artifacts`**
   - Returns: `list[dict]` — all `ArtifactRecord` objects for the run
   - WHEN the run has no artifacts, THE endpoint SHALL return an empty list

   **GET `/api/v1/runs/{run_id}/provenance`**
   - Returns: `dict` — the provenance summary as specified in req-03 §Requirement 3
   - WHEN the run has no provenance records, THE endpoint SHALL return a valid dict with empty lists

---

## Requirement 2: Artifact ID Validation

**User Story:** As an API consumer, I want the API to reject malformed artifact IDs, so that I get clear errors instead of filesystem traversal attempts.

### Acceptance Criteria

1. THE artifacts router SHALL validate `artifact_id` path parameters: only alphanumeric characters, hyphens, and underscores are allowed.

2. WHEN an `artifact_id` contains invalid characters, THE endpoint SHALL return HTTP 400 with `{"detail": "Invalid artifact_id"}`.

---

## Requirement 3: CLI `audiobuilder artifacts` Subcommand

**User Story:** As a developer, I want to inspect artifacts and lineage from the command line, so that I can debug pipeline outputs without writing Python scripts.

### Acceptance Criteria

1. THE CLI SHALL expose a new top-level subcommand `artifacts` in `app/cli/main.py`.

2. THE `artifacts` subcommand SHALL have the following sub-subcommands:

   **`audiobuilder artifacts list [--run <run_id>] [--type <artifact_type>]`**
   - Lists artifacts, optionally filtered by run ID and/or artifact type
   - Output: a table with columns `ARTIFACT ID`, `TYPE`, `NODE TYPE`, `RUN ID`, `CREATED AT`
   - WHEN no artifacts match the filters, THE CLI SHALL print `"No artifacts found."` and exit 0

   **`audiobuilder artifacts get <artifact_id>`**
   - Prints the full `ArtifactRecord` as formatted JSON
   - WHEN `artifact_id` is not found, THE CLI SHALL print an error to stderr and exit 1

   **`audiobuilder artifacts lineage <artifact_id>`**
   - Prints the lineage tree as formatted JSON
   - WHEN `artifact_id` is not found in the provenance store, THE CLI SHALL print the partial tree (not exit 1)

   **`audiobuilder artifacts replay <run_id>`**
   - Re-executes the pipeline using the `graph.json` stored in `workspace/runs/{run_id}/`
   - Prints the new `run_id` on success
   - WHEN `workspace/runs/{run_id}/graph.json` does not exist, THE CLI SHALL print an error to stderr and exit 1
   - THE replay SHALL execute synchronously (blocking until complete), printing progress to stdout

3. THE `artifacts` subcommand SHALL delegate all data access to `ArtifactStore` and `ProvenanceStore` — no direct filesystem reads in the CLI handler.

4. THE `artifacts` subcommand SHALL follow the existing CLI pattern: `cmd_artifacts_*` functions registered via `set_defaults(func=...)`.

---

## Requirement 4: Replay Semantics

**User Story:** As an ML engineer, I want to replay a run from its stored graph, so that I can reproduce results or re-run a pipeline with the same structure on new data.

### Acceptance Criteria

1. WHEN a replay is triggered (via CLI or REST API), THE platform SHALL:
   a. Load `workspace/runs/{original_run_id}/graph.json` via `load_ir_from_file()`
   b. Create a new `RunManager` (new `run_id`)
   c. Execute `run_pipeline_ir(graph, run_manager=new_run_manager)`
   d. Return the new `run_id`

2. THE replay SHALL produce a new run with its own `run_id`, `meta.json`, `logs.json`, and `graph.json`.

3. THE replay SHALL NOT modify the original run's files.

4. WHEN the original `graph.json` references node types that are no longer registered, THE replay SHALL fail with a descriptive error (same behavior as `validate_graph_handler` for unknown node types).
