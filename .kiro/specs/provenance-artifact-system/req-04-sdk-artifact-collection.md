# req-04 — SDK ArtifactCollection

## Introduction

This document specifies the `ArtifactCollection` class and the change to `Pipeline.run()`'s return type. In Phases 1–3, `Pipeline.run()` returns a raw `dict` mapping node IDs to their outputs. Phase 4 changes this return type to `ArtifactCollection`, which wraps a list of `ArtifactRecord` objects while remaining fully backward-compatible with dict-like access patterns.

The backward compatibility requirement is strict: any code that treats the return value of `Pipeline.run()` as a dict (using `result["node_id"]`, `"node_id" in result`, `result.keys()`) must continue to work without modification.

**Cross-references:** req-01 (`ArtifactRecord` is the element type), req-03 (`RunManager.register_artifact()` populates the collection), req-05 (REST API returns `ArtifactCollection`-derived responses).

---

## Requirement 1: ArtifactCollection Data Model

**User Story:** As a Python SDK user, I want `Pipeline.run()` to return a rich object that gives me access to typed artifacts and lineage, so that I can inspect pipeline outputs without reading files manually.

### Acceptance Criteria

1. THE `ArtifactCollection` SHALL be a class defined in `app/core/sdk.py` (or a dedicated `app/core/artifact_collection.py` imported by `sdk.py`).

2. THE `ArtifactCollection` SHALL have the following attributes:
   - `artifacts: list[ArtifactRecord]` — all artifacts registered during the run
   - `run_id: str` — the run ID
   - `_raw: dict` — the raw node-output dict (for backward compatibility, not part of the public API)

3. THE `ArtifactCollection` SHALL expose the following methods:
   - `get(node_id: str) -> ArtifactRecord | None` — return the first artifact whose `node_id` matches, or `None`
   - `get_by_type(artifact_type: str) -> list[ArtifactRecord]` — return all artifacts of the given type
   - `lineage(artifact_id: str) -> dict` — delegate to `ProvenanceStore.get_lineage(artifact_id)`

4. THE `ArtifactCollection` SHALL implement the following dict-like interface for backward compatibility:
   - `__getitem__(key: str)` — return `self._raw[key]`
   - `__contains__(key: str)` — return `key in self._raw`
   - `keys()` — return `self._raw.keys()`
   - `items()` — return `self._raw.items()`
   - `values()` — return `self._raw.values()`
   - `get(key: str, default=None)` — NOTE: this overloads the `get(node_id)` method; the implementation SHALL dispatch based on argument type: if `key` is a `str` and `default` is not provided, check `_raw` first, then fall back to artifact lookup by `node_id`

5. THE `ArtifactCollection.__repr__()` SHALL return a human-readable string including `run_id` and artifact count.

---

## Requirement 2: Pipeline.run() Return Type Change

**User Story:** As a Python SDK user, I want `Pipeline.run()` to return an `ArtifactCollection`, so that I get artifact metadata and lineage access without changing my existing code.

### Acceptance Criteria

1. WHEN `Pipeline.run()` completes successfully, THE `Pipeline` SHALL return an `ArtifactCollection` instead of a raw `dict`.

2. THE `ArtifactCollection` returned by `Pipeline.run()` SHALL be populated with:
   - `run_id` from the `RunManager` used during execution
   - `artifacts` from `RunManager.get_provenance_summary()["artifacts"]` (as `ArtifactRecord` objects)
   - `_raw` set to the raw output dict returned by `run_pipeline_ir()`

3. WHEN `Pipeline.run()` is called without a `run_manager` argument, THE `Pipeline` SHALL create an internal `RunManager` and use it to populate the `ArtifactCollection`.

4. THE `Pipeline.run()` method signature SHALL NOT change (all existing parameters remain with the same types and defaults).

5. WHEN `Pipeline.run()` raises an exception, THE exception SHALL propagate unchanged (no wrapping in `ArtifactCollection`).

---

## Requirement 3: Backward Compatibility

**User Story:** As a developer with existing code that uses `Pipeline.run()` as a dict, I want my code to continue working without modification after upgrading to Phase 4.

### Acceptance Criteria

1. FOR ANY existing code that accesses `result = pipeline.run()` as `result["node_id"]`, THE `ArtifactCollection` SHALL return the same value as the Phase 3 raw dict.

2. FOR ANY existing code that checks `"node_id" in result`, THE `ArtifactCollection` SHALL return the same boolean as the Phase 3 raw dict.

3. FOR ANY existing code that iterates `result.keys()`, THE `ArtifactCollection` SHALL return the same keys as the Phase 3 raw dict.

4. THE `ArtifactCollection` SHALL pass `isinstance(result, dict)` as `False` — it is NOT a dict subclass. Code that uses `isinstance(result, dict)` to branch behavior is not supported for backward compatibility.

5. THE `run_with_manager()` method on `Pipeline` SHALL also return `(ArtifactCollection, RunManager)` instead of `(dict, RunManager)`.

---

## Requirement 4: ArtifactCollection Lineage Access

**User Story:** As a data scientist, I want to access the lineage of any artifact directly from the ArtifactCollection, so that I can trace provenance without importing additional modules.

### Acceptance Criteria

1. WHEN `collection.lineage(artifact_id)` is called, THE `ArtifactCollection` SHALL return the lineage tree dict as specified in req-02 §Requirement 4.

2. WHEN `collection.lineage(artifact_id)` is called for an `artifact_id` not in `collection.artifacts`, THE `ArtifactCollection` SHALL still delegate to `ProvenanceStore.get_lineage()` (which may return a partial tree or error node).

3. THE `lineage()` method SHALL NOT raise an exception for unknown artifact IDs.
