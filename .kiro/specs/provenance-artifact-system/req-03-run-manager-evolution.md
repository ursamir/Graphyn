# req-03 — RunManager Evolution

## Introduction

This document specifies the Phase 4 extensions to `RunManager` in `app/core/run_manager.py`. The existing `RunManager` manages run lifecycle (metadata, logs, graph IR, checkpoints, resume state, pause/resume/cancel). Phase 4 adds three capabilities: artifact registration (delegating to `ArtifactStore`), graph hash computation, and provenance summary generation.

The `RunManager` is extended, not replaced. All existing methods and their signatures remain unchanged. The new methods are purely additive.

**Cross-references:** req-01 (`ArtifactStore` is the storage backend), req-02 (`ProvenanceStore` is the provenance backend), req-04 (`ArtifactCollection` is built from the artifacts registered via `RunManager`).

---

## Requirement 1: Graph Hash Computation

**User Story:** As a platform developer, I want RunManager to compute a stable hash of the graph IR, so that I can identify runs that used the same graph structure for reproducibility queries.

### Acceptance Criteria

1. THE `RunManager` SHALL expose a `compute_graph_hash(graph_ir)` static method (or class method) that accepts a `GraphIR` object and returns a `str`.

2. THE `compute_graph_hash()` method SHALL compute the hash as `hashlib.sha256(json.dumps(dump_ir(graph_ir), sort_keys=True).encode()).hexdigest()`.

3. THE `compute_graph_hash()` method SHALL produce identical output for two `GraphIR` objects that are semantically equivalent (same nodes, edges, metadata, parameters) regardless of the order in which they were constructed.

4. THE `compute_graph_hash()` method SHALL be a pure function with no side effects.

---

## Requirement 2: Artifact Registration

**User Story:** As a pipeline executor, I want to register node outputs as artifacts through RunManager, so that artifact storage and provenance recording happen in one coordinated call.

### Acceptance Criteria

1. THE `RunManager` SHALL expose a `register_artifact(node_id, node_type, artifact_type, data, metadata=None, input_artifact_ids=None)` method that returns an `ArtifactRecord`.

2. WHEN `register_artifact()` is called, THE `RunManager` SHALL:
   a. Call `ArtifactStore.register(run_id=self.run_id, node_id=node_id, node_type=node_type, artifact_type=artifact_type, data=data, metadata=metadata or {})`
   b. Call `ProvenanceStore.record(artifact_id=record.artifact_id, run_id=self.run_id, node_id=node_id, node_type=node_type, graph_hash=self._graph_hash, input_artifact_ids=input_artifact_ids or [])`
   c. Return the `ArtifactRecord`

3. THE `RunManager` SHALL store the current `graph_hash` as `self._graph_hash` after `save_graph_ir()` is called. WHEN `save_graph_ir(graph_data)` is called, THE `RunManager` SHALL compute and store `self._graph_hash` from the `graph_data` dict.

4. WHEN `register_artifact()` is called before `save_graph_ir()` has been called, THE `RunManager` SHALL use `""` (empty string) as the `graph_hash`.

5. THE `RunManager` SHALL lazily initialize `ArtifactStore` and `ProvenanceStore` instances on first use (not at `__init__` time) to avoid breaking existing tests that do not use Phase 4 features.

---

## Requirement 3: Provenance Summary

**User Story:** As a developer, I want to retrieve a complete summary of all artifacts and their lineage for a run, so that I can inspect the full output of a pipeline execution.

### Acceptance Criteria

1. THE `RunManager` SHALL expose a `get_provenance_summary()` method that returns a `dict`.

2. THE provenance summary dict SHALL have the following structure:
   ```json
   {
     "run_id": "...",
     "graph_hash": "...",
     "artifacts": [
       {
         "artifact_id": "...",
         "artifact_type": "...",
         "node_id": "...",
         "node_type": "...",
         "content_hash": "...",
         "created_at": "..."
       }
     ],
     "provenance_records": [
       {
         "artifact_id": "...",
         "input_artifact_ids": [...],
         "graph_hash": "..."
       }
     ]
   }
   ```

3. WHEN `get_provenance_summary()` is called for a run with no registered artifacts, THE `RunManager` SHALL return a valid dict with empty `artifacts` and `provenance_records` lists.

4. THE `get_provenance_summary()` method SHALL NOT raise an exception if `ArtifactStore` or `ProvenanceStore` have not been initialized (return empty lists).

---

## Requirement 4: Backward Compatibility

**User Story:** As a platform developer, I want all existing RunManager behavior to remain unchanged, so that Phase 1–3 tests continue to pass without modification.

### Acceptance Criteria

1. THE `RunManager.__init__()` signature SHALL NOT change.

2. ALL existing `RunManager` methods (`save_config`, `save_logs`, `save_metadata`, `save_graph_ir`, `mark_failed`, `mark_cancelled`, `pause`, `resume`, `cancel`, `wait_if_paused`, `init_resume_state`, `update_resume_state`, `load_resume_state`, `find_latest_checkpoint`) SHALL retain their existing signatures and behavior.

3. THE module-level functions `register_active_run()`, `get_active_run()`, `deregister_active_run()` SHALL retain their existing signatures and behavior.

4. WHEN Phase 4 extensions are not used (i.e., `register_artifact()` and `get_provenance_summary()` are never called), THE `RunManager` SHALL behave identically to its Phase 3 implementation.
