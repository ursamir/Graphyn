# req-07 — Property-Based Test Specifications

## Introduction

This document specifies the five property-based tests for Phase 4. These tests use the Hypothesis library (already installed in the project) and follow the existing pattern established in `tests/mcp/test_properties.py`. Each property is a universally quantified statement about the system's behavior that must hold for all valid inputs.

All property tests SHALL use `@settings(max_examples=100)` minimum and SHALL be tagged with a comment in the format `# Feature: provenance-artifact-system, Property N: <text>`.

---

## Property 1: Lineage Integrity

**Specification:** For any artifact registered with input artifact IDs, all `input_artifact_ids` in its `ProvenanceRecord` are themselves registered artifacts in the `ArtifactStore`.

**Formal statement:** *For any* set of artifacts A₁, A₂, ..., Aₙ registered in the `ArtifactStore`, and any `ProvenanceRecord` P where `P.artifact_id` is in the store, every `artifact_id` in `P.input_artifact_ids` SHALL also be present in the `ArtifactStore`.

**Test strategy:**
1. Generate a random list of 1–5 "input" artifacts (random `artifact_type`, random metadata)
2. Register each input artifact via `ArtifactStore.register()`
3. Register one "output" artifact and record its provenance with `input_artifact_ids` pointing to the registered inputs
4. Call `ProvenanceStore.get_lineage(output_artifact_id)`
5. Assert that every `artifact_id` appearing in `input_artifact_ids` of the provenance record can be retrieved via `ArtifactStore.get(artifact_id)` without raising `ArtifactNotFoundError`

**Validates:** req-02 §Requirement 3, req-01 §Requirement 4

**Tag:** `# Feature: provenance-artifact-system, Property 1: Lineage integrity`

---

## Property 2: Content-Addressed Deduplication

**Specification:** Registering the same content twice produces the same `content_hash` and does not create duplicate storage entries.

**Formal statement:** *For any* valid artifact data D, calling `ArtifactStore.register(data=D, ...)` twice (with potentially different `run_id`, `node_id`, or `metadata`) SHALL produce two `ArtifactRecord` objects with the same `content_hash`, and the `workspace/artifacts/index.json` SHALL contain exactly one entry for that `content_hash`.

**Test strategy:**
1. Generate random artifact data (e.g., a list of `AudioSample`-like dicts, or a simple JSON-serializable dict for `"generic"` type)
2. Call `ArtifactStore.register()` twice with the same `data` but different `run_id` and `node_id`
3. Assert `record1.content_hash == record2.content_hash`
4. Read `index.json` and assert it contains exactly one entry for that `content_hash`
5. Assert the `workspace/artifacts/` directory contains exactly one artifact directory for that content (not two)

**Validates:** req-01 §Requirement 3.3, req-01 §Requirement 3.4

**Tag:** `# Feature: provenance-artifact-system, Property 2: Content-addressed deduplication`

---

## Property 3: Provenance Round-Trip

**Specification:** Recording provenance and then retrieving lineage returns a tree rooted at the artifact.

**Formal statement:** *For any* artifact A with provenance recorded via `ProvenanceStore.record(artifact_id=A.artifact_id, ...)`, calling `ProvenanceStore.get_lineage(A.artifact_id)` SHALL return a dict whose top-level `artifact_id` equals `A.artifact_id`.

**Test strategy:**
1. Generate a random `artifact_id` (UUID-like string), `run_id`, `node_id`, `node_type`, `graph_hash`, and `input_artifact_ids` (empty list for simplicity)
2. Call `ProvenanceStore.record(artifact_id, run_id, node_id, node_type, graph_hash, input_artifact_ids)`
3. Call `ProvenanceStore.get_lineage(artifact_id)`
4. Assert `result["artifact_id"] == artifact_id`
5. Assert `result["run_id"] == run_id`
6. Assert `result["node_id"] == node_id`
7. Assert `"inputs"` key is present in the result

**Validates:** req-02 §Requirement 4

**Tag:** `# Feature: provenance-artifact-system, Property 3: Provenance round-trip`

---

## Property 4: Replay Reproducibility

**Specification:** Replaying a run with the same `graph.json` and same inputs produces artifacts with identical `content_hash` values for deterministic nodes.

**Formal statement:** *For any* pipeline graph G containing only deterministic nodes (i.e., all nodes have `IRCapabilityMetadata.deterministic == True`), executing G twice with the same inputs SHALL produce `ArtifactRecord` objects with identical `content_hash` values for each corresponding node output.

**Test strategy:**
1. Build a minimal deterministic pipeline (e.g., a single `InputNode` or a simple transform node with fixed config)
2. Execute the pipeline via `run_pipeline_ir()` with `run_manager=RunManager()` — capture `run_id_1`
3. Load `workspace/runs/{run_id_1}/graph.json` via `load_ir_from_file()`
4. Execute the loaded graph again with a new `RunManager()` — capture `run_id_2`
5. Retrieve artifacts for both runs via `ArtifactStore.list(run_id=run_id_1)` and `ArtifactStore.list(run_id=run_id_2)`
6. For each pair of artifacts with the same `node_type`, assert `artifact_1.content_hash == artifact_2.content_hash`

**Note:** This property applies only to deterministic nodes. Non-deterministic nodes (e.g., those with random augmentation) are excluded from the assertion. The test generator SHALL only use nodes where `IRCapabilityMetadata.deterministic == True`.

**Validates:** req-03 §Requirement 1, req-05 §Requirement 4

**Tag:** `# Feature: provenance-artifact-system, Property 4: Replay reproducibility`

---

## Property 5: ArtifactCollection Backward Compatibility

**Specification:** `ArtifactCollection` supports dict-like access for all keys that the old `Pipeline.run()` return value supported.

**Formal statement:** *For any* pipeline execution that previously returned a dict D from `Pipeline.run()`, the `ArtifactCollection` AC returned by the same execution SHALL satisfy: `AC[k] == D[k]` for all `k in D.keys()`, `k in AC` iff `k in D`, and `set(AC.keys()) == set(D.keys())`.

**Test strategy:**
1. Execute a pipeline using the Phase 3 `run_pipeline_ir()` directly (bypassing `ArtifactCollection`) to get the raw dict `raw_outputs`
2. Execute the same pipeline via `Pipeline.run()` to get `collection: ArtifactCollection`
3. For each key `k` in `raw_outputs`:
   - Assert `k in collection` is `True`
   - Assert `collection[k]` equals `raw_outputs[k]` (or is equivalent for list types)
4. Assert `set(collection.keys()) == set(raw_outputs.keys())`
5. Assert `collection.run_id` is a non-empty string

**Note:** The generator SHALL use pipelines with 1–3 nodes to keep execution fast. The test SHALL use `@settings(max_examples=50)` due to the cost of pipeline execution.

**Validates:** req-04 §Requirement 3

**Tag:** `# Feature: provenance-artifact-system, Property 5: ArtifactCollection backward compatibility`

---

## Test File Location

All five property tests SHALL be implemented in `tests/test_provenance_properties.py`.

Each test SHALL:
- Use `@given(...)` with Hypothesis strategies
- Use `@settings(max_examples=100)` (except Property 5 which uses `max_examples=50`)
- Include the tag comment immediately before the `def test_...` line
- Use a temporary workspace directory (via `tmp_path` pytest fixture or `@settings(deriving=...)`) to avoid polluting the real workspace
- Clean up after itself (use `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))` to isolate)
