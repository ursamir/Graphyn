# req-02 — Provenance Records

## Introduction

This document specifies the `ProvenanceStore` component (`app/core/provenance.py`) and the `ProvenanceRecord` data model. Provenance records link artifacts to the exact execution context that produced them: the run, the node, the graph structure (via `graph_hash`), and the input artifacts consumed. Together, these records form a directed acyclic graph of artifact lineage that enables reproducibility queries, audit trails, and graph optimization.

The `graph_hash` (SHA-256 of `dump_ir(graph)`) is the reproducibility key established in Phase 1 (req-03 §3.6). Two runs with the same `graph_hash` and the same input artifact hashes are expected to produce artifacts with identical `content_hash` values for deterministic nodes.

**Cross-references:** req-01 (ProvenanceRecord references ArtifactRecord IDs), req-03 (RunManager calls `ProvenanceStore.record()`), req-05 (REST API exposes lineage endpoints).

---

## Requirement 1: ProvenanceRecord Data Model

**User Story:** As a data scientist, I want each artifact to carry a complete record of how it was produced, so that I can audit and reproduce any pipeline output.

### Acceptance Criteria

1. THE `ProvenanceRecord` SHALL be a Pydantic `BaseModel` with the following fields:
   - `artifact_id: str` — the artifact produced (references `ArtifactRecord.artifact_id`)
   - `run_id: str` — the run that produced the artifact
   - `node_id: str` — the IR node ID that produced the artifact
   - `node_type: str` — the node type string
   - `graph_hash: str` — SHA-256 of the canonical `dump_ir(graph)` JSON for this run
   - `input_artifact_ids: list[str]` — artifact IDs consumed as inputs (may be empty for source nodes)
   - `created_at: str` — ISO 8601 UTC timestamp
   - `schema_version: str` — `"1.0"`

2. THE `ProvenanceRecord` SHALL be JSON-serializable via `model.model_dump(mode="json")`.

3. THE `ProvenanceRecord` SHALL be immutable after creation (Pydantic `model_config = ConfigDict(frozen=True)`).

---

## Requirement 2: ProvenanceStore Initialization

**User Story:** As a platform operator, I want the ProvenanceStore to initialize its workspace directories automatically, so that no manual setup is required.

### Acceptance Criteria

1. THE `ProvenanceStore` SHALL read its base directory from `os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")` and use `{workspace}/provenance/` as its root.

2. WHEN `ProvenanceStore.__init__()` is called, THE `ProvenanceStore` SHALL create `{workspace}/provenance/` and `{workspace}/provenance/by_run/` if they do not exist.

3. THE `ProvenanceStore` SHALL NOT raise an exception if the workspace directories already exist.

---

## Requirement 3: Recording Provenance

**User Story:** As a pipeline executor, I want to record provenance for every artifact produced, so that lineage is captured automatically without manual intervention.

### Acceptance Criteria

1. THE `ProvenanceStore` SHALL expose a `record(artifact_id, run_id, node_id, node_type, graph_hash, input_artifact_ids)` method that returns a `ProvenanceRecord`.

2. WHEN `record()` is called, THE `ProvenanceStore` SHALL:
   a. Create a `ProvenanceRecord` with the provided fields and a UTC `created_at` timestamp
   b. Write `{workspace}/provenance/{artifact_id}.json` containing the serialized `ProvenanceRecord`
   c. Append `artifact_id` to the run index at `{workspace}/provenance/by_run/{run_id}.json`

3. THE `by_run/{run_id}.json` file SHALL be a JSON array of `artifact_id` strings.

4. WHEN `record()` is called for an `artifact_id` that already has a provenance record, THE `ProvenanceStore` SHALL overwrite the existing record (idempotent update).

5. THE `record()` method SHALL be thread-safe.

---

## Requirement 4: Lineage Retrieval

**User Story:** As a data scientist, I want to retrieve the full upstream lineage of any artifact, so that I can trace exactly what data and graph structure produced it.

### Acceptance Criteria

1. THE `ProvenanceStore` SHALL expose a `get_lineage(artifact_id)` method that returns a dict representing the full upstream lineage tree rooted at `artifact_id`.

2. THE lineage tree dict SHALL have the following structure:
   ```json
   {
     "artifact_id": "...",
     "run_id": "...",
     "node_id": "...",
     "node_type": "...",
     "graph_hash": "...",
     "created_at": "...",
     "inputs": [
       { /* same structure, recursively */ }
     ]
   }
   ```

3. WHEN `get_lineage()` encounters an `artifact_id` with no provenance record, THE `ProvenanceStore` SHALL include a leaf node with `{"artifact_id": "...", "inputs": [], "error": "no_provenance_record"}`.

4. THE `get_lineage()` method SHALL detect and break cycles (if any) by tracking visited `artifact_id` values and emitting `{"artifact_id": "...", "inputs": [], "error": "cycle_detected"}` for repeated nodes.

5. THE `get_lineage()` method SHALL NOT raise an exception for missing provenance records — it SHALL return a partial tree with error nodes.

---

## Requirement 5: Run-Based Queries

**User Story:** As a developer, I want to query all provenance records for a run, so that I can understand the full artifact graph produced by a single execution.

### Acceptance Criteria

1. THE `ProvenanceStore` SHALL expose a `find_by_run(run_id)` method that returns `list[ProvenanceRecord]`.

2. WHEN `find_by_run()` is called for a run with no provenance records, THE `ProvenanceStore` SHALL return an empty list.

3. WHEN `find_by_run()` is called for an unknown `run_id`, THE `ProvenanceStore` SHALL return an empty list (not raise an exception).

---

## Requirement 6: Reproducibility Queries

**User Story:** As an ML engineer, I want to find all runs that used the same graph structure, so that I can compare outputs and verify reproducibility.

### Acceptance Criteria

1. THE `ProvenanceStore` SHALL expose a `find_reproducible(graph_hash)` method that returns `list[ProvenanceRecord]` — all provenance records whose `graph_hash` matches the provided value.

2. WHEN `find_reproducible()` is called, THE `ProvenanceStore` SHALL scan all `{workspace}/provenance/*.json` files and return matching records.

3. WHEN `find_reproducible()` is called with a `graph_hash` that matches no records, THE `ProvenanceStore` SHALL return an empty list.

---

## Requirement 7: Workspace Layout

**User Story:** As a platform operator, I want provenance data stored in a predictable directory structure, so that I can audit lineage manually if needed.

### Acceptance Criteria

1. THE `ProvenanceStore` SHALL use the following workspace layout:
   ```
   workspace/
   └── provenance/
       ├── {artifact_id}.json   # ProvenanceRecord for each artifact
       └── by_run/
           └── {run_id}.json    # JSON array of artifact_ids for each run
   ```

2. THE `{artifact_id}.json` files SHALL contain the full `ProvenanceRecord` serialized via `model_dump(mode="json")`.

3. THE `by_run/{run_id}.json` files SHALL be JSON arrays of `artifact_id` strings.

4. THE existing workspace layout SHALL NOT be modified by the `ProvenanceStore`.
