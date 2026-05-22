# req-01 — Artifact Store

## Introduction

This document specifies the `ArtifactStore` component (`app/core/artifact_store.py`) and the `ArtifactRecord` data model. The `ArtifactStore` is a content-addressed, typed artifact registry. It stores the outputs of node executions as first-class platform entities, enabling deduplication, versioning, and retrieval by run, node type, or artifact type.

The design mirrors `PipelineCache` (Phase 1) in its use of SHA-256 content addressing, but operates at a higher level of abstraction: it stores typed metadata envelopes (`ArtifactRecord`) alongside serialized data, and it supports multiple artifact types beyond `AudioSample`.

**Cross-references:** req-02 (provenance records reference artifact IDs), req-03 (RunManager calls `ArtifactStore.register()`), req-04 (ArtifactCollection wraps ArtifactRecord lists).

---

## Requirement 1: ArtifactRecord Data Model

**User Story:** As a platform developer, I want a typed metadata envelope for every artifact, so that I can identify, retrieve, and compare artifacts without loading their data.

### Acceptance Criteria

1. THE `ArtifactRecord` SHALL be a Pydantic `BaseModel` with the following fields:
   - `artifact_id: str` — globally unique identifier (UUID4, 8-char prefix)
   - `content_hash: str` — SHA-256 hex digest of the canonical serialized artifact data
   - `artifact_type: str` — one of `"audio_samples"`, `"model_artifact"`, `"tflite_artifact"`, `"prediction_result"`, `"feature_array"`, `"generic"`
   - `node_id: str` — the IR node ID that produced this artifact
   - `node_type: str` — the node type string (e.g. `"clean"`, `"train"`)
   - `run_id: str` — the run that produced this artifact
   - `name: str | None` — optional human-readable name (default `None`)
   - `metadata: dict` — arbitrary key-value metadata (default `{}`)
   - `created_at: str` — ISO 8601 UTC timestamp
   - `schema_version: str` — `"1.0"`
   - `data_path: str | None` — relative path from workspace root to the serialized data directory (default `None`)

2. THE `ArtifactRecord` SHALL be JSON-serializable via `model.model_dump(mode="json")`.

3. WHEN two `ArtifactRecord` objects have the same `content_hash`, THE `ArtifactStore` SHALL treat them as identical content regardless of their `artifact_id`.

4. THE `ArtifactRecord` SHALL be immutable after creation (Pydantic `model_config = ConfigDict(frozen=True)`).

---

## Requirement 2: ArtifactStore Initialization

**User Story:** As a platform operator, I want the ArtifactStore to initialize its workspace directories automatically, so that no manual setup is required.

### Acceptance Criteria

1. THE `ArtifactStore` SHALL read its base directory from `os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")` and use `{workspace}/artifacts/` as its root.

2. WHEN `ArtifactStore.__init__()` is called, THE `ArtifactStore` SHALL create `{workspace}/artifacts/` and `{workspace}/artifacts/index.json` if they do not exist.

3. THE `index.json` file SHALL map `content_hash → artifact_id` and SHALL be a valid JSON object (empty `{}` on first creation).

4. THE `ArtifactStore` SHALL NOT raise an exception if the workspace directories already exist.

---

## Requirement 3: Artifact Registration

**User Story:** As a pipeline executor, I want to register node outputs as artifacts, so that they are stored with full metadata and can be retrieved later.

### Acceptance Criteria

1. THE `ArtifactStore` SHALL expose a `register(run_id, node_id, node_type, artifact_type, data, metadata)` method that returns an `ArtifactRecord`.

2. WHEN `register()` is called, THE `ArtifactStore` SHALL compute a `content_hash` by serializing `data` to a canonical form and computing its SHA-256 digest.

3. WHEN `register()` is called with data whose `content_hash` already exists in `index.json`, THE `ArtifactStore` SHALL return the existing `ArtifactRecord` without writing duplicate data to disk (content-addressed deduplication).

4. WHEN `register()` is called with new content, THE `ArtifactStore` SHALL:
   a. Assign a new `artifact_id` (UUID4, 8-char prefix)
   b. Create `{workspace}/artifacts/{artifact_id}/` directory
   c. Write serialized data to `{workspace}/artifacts/{artifact_id}/data/`
   d. Write `{workspace}/artifacts/{artifact_id}/record.json` containing the `ArtifactRecord`
   e. Update `{workspace}/artifacts/index.json` with `content_hash → artifact_id`

5. THE `register()` method SHALL be thread-safe (use a file lock or in-process lock when updating `index.json`).

6. IF `artifact_type` is `"audio_samples"`, THE `ArtifactStore` SHALL serialize each `AudioSample` as a WAV file plus a `manifest.json` (same format as `PipelineCache`).

7. IF `artifact_type` is `"model_artifact"` or `"tflite_artifact"`, THE `ArtifactStore` SHALL serialize the artifact using its `model_dump(mode="json")` representation in a `data.json` file.

8. IF `artifact_type` is `"feature_array"` or `"prediction_result"`, THE `ArtifactStore` SHALL serialize the artifact using its `model_dump(mode="json")` representation in a `data.json` file.

9. IF `artifact_type` is `"generic"`, THE `ArtifactStore` SHALL serialize `data` as JSON in a `data.json` file.

---

## Requirement 4: Artifact Retrieval

**User Story:** As a developer, I want to retrieve artifacts by ID or query them by run/type, so that I can inspect pipeline outputs programmatically.

### Acceptance Criteria

1. THE `ArtifactStore` SHALL expose a `get(artifact_id)` method that returns an `ArtifactRecord`.

2. WHEN `get(artifact_id)` is called for an unknown ID, THE `ArtifactStore` SHALL raise `ArtifactNotFoundError(artifact_id)`.

3. THE `ArtifactStore` SHALL expose a `list(run_id=None, node_type=None, artifact_type=None)` method that returns `list[ArtifactRecord]`.

4. WHEN `list()` is called with no filters, THE `ArtifactStore` SHALL return all registered artifacts sorted by `created_at` descending.

5. WHEN `list()` is called with one or more filters, THE `ArtifactStore` SHALL return only artifacts matching ALL provided filters.

6. THE `ArtifactStore` SHALL expose a `get_versions(artifact_name)` method that returns `list[ArtifactRecord]` — all artifacts whose `name` field equals `artifact_name`, sorted by `created_at` descending.

---

## Requirement 5: Workspace Layout Extension

**User Story:** As a platform operator, I want artifacts stored in a predictable, inspectable directory structure, so that I can audit and manage storage manually if needed.

### Acceptance Criteria

1. THE `ArtifactStore` SHALL use the following workspace layout:
   ```
   workspace/
   └── artifacts/
       ├── {artifact_id}/
       │   ├── record.json      # ArtifactRecord metadata
       │   └── data/            # serialized artifact data
       └── index.json           # content_hash → artifact_id mapping
   ```

2. THE `record.json` file SHALL contain the full `ArtifactRecord` serialized via `model_dump(mode="json")`.

3. THE `index.json` file SHALL be a flat JSON object mapping `content_hash` strings to `artifact_id` strings.

4. THE existing workspace layout (`datasets/`, `runs/`, `cache/`) SHALL NOT be modified by the `ArtifactStore`.

---

## Requirement 6: Error Handling

**User Story:** As a developer, I want clear, typed errors from the ArtifactStore, so that I can handle failure cases explicitly.

### Acceptance Criteria

1. THE `ArtifactStore` SHALL define `ArtifactNotFoundError(artifact_id: str)` as a subclass of `KeyError`.

2. WHEN `register()` fails due to a serialization error, THE `ArtifactStore` SHALL raise `ArtifactSerializationError(artifact_type, cause)` as a subclass of `RuntimeError`.

3. WHEN `index.json` is corrupt or unreadable, THE `ArtifactStore` SHALL log a warning and treat the index as empty (fail-open for reads, fail-safe for writes by rebuilding the index from disk).

4. IF `register()` is called with an unsupported `artifact_type`, THE `ArtifactStore` SHALL raise `ValueError` with a descriptive message listing supported types.
