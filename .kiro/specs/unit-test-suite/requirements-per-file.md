# Per-File Unit Test Requirements

> **Parent document:** `requirements.md`
> These requirements extend the main spec with isolated, per-file unit tests.
> Each requirement maps 1-to-1 to a source file. Tests use mocks/stubs for all
> external dependencies so each file is tested in complete isolation.

---

### Requirement 17: Data Models (`app/models/`)

One test file per model. All models extend `PortDataType`.

#### Acceptance Criteria

**AudioSample (`audio_sample.py`)**
1. `AudioSample(path="x", sample_rate=16000)` constructs with `data` as empty float32 ndarray, `label=""`, `metadata={}`.
2. `data=None` is coerced to empty float32 ndarray.
3. `data=[1.0, 2.0]` (list) is coerced to float32 ndarray.
4. `AudioSample.model_validate({"path":"x","sample_rate":8000})` round-trips via `model_dump()`.
5. `AudioSample` is a subclass of `PortDataType`.

**FeatureArray (`feature_array.py`)**
6. `FeatureArray()` constructs with `data` as empty float32 2-D array, `label=""`, `feature_type=""`.
7. `data=None` is coerced to `np.zeros((0,0), dtype=np.float32)`.
8. `FeatureArray` is a subclass of `PortDataType`.

**TensorBatch (`tensor_batch.py`)**
9. `TensorBatch()` constructs with `data` as empty float32 array, `labels=[]`, `split=""`.
10. `batch_size` property returns `data.shape[0]`.
11. `data=None` is coerced to `np.zeros((0,), dtype=np.float32)`.

**TFLiteArtifact (`tflite_artifact.py`)**
12. `quantisation` field accepts `"float32"`, `"float16"`, `"int8"`.
13. `quantisation="bad"` raises `pydantic.ValidationError`.

**ModelArtifact, PredictionResult, DeploymentArtifact, DataSample (`model_artifact.py`, `prediction_result.py`, `deployment_artifact.py`, `data_sample.py`)**
14. Each constructs with all-default values without raising.
15. Each is a subclass of `PortDataType`.
16. `DataSample()` has `id=""`, `source=""`, `metadata={}`.
17. `DeploymentArtifact` `labels` and `metadata` default to empty list/dict (not shared mutable defaults).

---

### Requirement 18: Node Infrastructure (`app/core/nodes/`)

**errors.py**
1. All 8 error classes (`NodeSystemError`, `NodeNotFoundError`, `DuplicateNodeTypeError`, `NodeMetadataError`, `NodeTypeError`, `PortTypeNotFoundError`, `DuplicatePortTypeError`, `PipelineGraphError`) are importable and are subclasses of `Exception`.
2. `NodeNotFoundError` is a subclass of `NodeSystemError`.
3. `PipelineGraphError` is a subclass of `NodeSystemError`.

**observers.py**
4. `LoggingObserver.on_node_start(node_type, run_id)` emits a JSON log line containing `"event": "node_start"` at INFO level.
5. `LoggingObserver.on_node_end(...)` emits a JSON log line containing `"event": "node_end"` and `"duration_s"` at INFO level.
6. `LoggingObserver.on_node_error(...)` emits a JSON log line containing `"event": "node_error"` at ERROR level.
7. `CompositeObserver([obs1, obs2]).on_node_start(...)` calls `on_node_start` on both child observers.
8. `CompositeObserver` with an empty list does not raise on any event method.

**config.py (NodeConfig)**
9. A `NodeConfig` subclass with `extra="forbid"` raises `pydantic.ValidationError` when an unknown field is passed.
10. `NodeConfig.model_validate({})` succeeds for a config with all-default fields.

**retry.py**
11. `RetryPolicy(max_attempts=0)` raises `pydantic.ValidationError`.
12. `RetryPolicy(backoff_seconds=-1.0)` raises `pydantic.ValidationError`.
13. `RetryPolicy(backoff_multiplier=0.5)` raises `pydantic.ValidationError`.
14. `RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0).wait_before_attempt(2)` returns `4.0`.

---

### Requirement 19: Core Utilities (`app/core/`)

**conditions.py**
1. `evaluate_condition("len(output['output']) > 2", {"output": [1,2,3]})` returns `True`.
2. `evaluate_condition("len(output['output']) > 2", {"output": [1]})` returns `False`.
3. `evaluate_condition("import os", {})` raises `ConditionEvaluationError`.
4. `evaluate_condition("open('x')", {})` raises `ConditionEvaluationError` (disallowed function).
5. `evaluate_condition("x > 1", {})` raises `ConditionEvaluationError` (disallowed name).
6. `evaluate_condition("{ bad syntax", {})` raises `ConditionEvaluationError` (syntax error).

**events.py**
7. `create_event_source("timer", {"interval_s": 0.1})` returns a `TimerSource` instance.
8. `create_event_source("queue", {"queue": asyncio.Queue()})` returns a `QueueSource` instance.
9. `create_event_source("unknown_type", {})` raises `ValueError`.
10. `TimerSource` is a subclass of `EventSource`.
11. `QueueSource.watch()` yields the dict that was put into the queue.

**runtime_backend.py**
12. `get_backend("local_python")` returns a `LocalPythonBackend` instance.
13. `get_backend("nonexistent")` raises `KeyError`.
14. `list_backends()` returns a sorted list containing `"local_python"`.
15. `register_backend("my_backend", LocalPythonBackend)` makes `get_backend("my_backend")` succeed.
16. `register_backend("x", int)` raises `TypeError` (not a RuntimeBackend subclass).
17. `LocalPythonBackend().backend_id` returns `"local_python"`.

**webhook.py**
18. `WebhookService.save(url, events)` writes `webhooks.json` with `{"url": url, "events": events}`.
19. `WebhookService.load()` returns `{}` when `webhooks.json` does not exist.
20. `WebhookService.notify(event, payload)` does not raise when no URL is configured.
21. `WebhookService.notify(event, payload)` does not raise when `httpx.post` raises (fire-and-forget).
22. `WebhookService.notify("run_done", {})` does not call `httpx.post` when `event` is not in the subscribed events list.

**ir/migrate.py**
23. `migrate_yaml_to_ir_file(yaml_path)` writes a `.graph.json` file next to the YAML file and returns its path.
24. `migrate_yaml_to_ir_file(yaml_path, output_path="custom.graph.json")` writes to the specified path.
25. The written `.graph.json` is valid IR JSON (parseable by `load_ir_from_file`).

---

### Requirement 20: Artifact Store and Provenance (`app/core/artifact_store.py`, `app/core/provenance.py`)

**ArtifactStore**
1. `ArtifactStore.register(run_id, node_id, node_type, "generic", data)` returns an `ArtifactRecord` with non-empty `artifact_id` and `content_hash`.
2. Calling `register()` twice with identical data returns records with the same `artifact_id` (content-addressing deduplication).
3. `ArtifactStore.get(artifact_id)` returns the same `ArtifactRecord` that was registered.
4. `ArtifactStore.get("nonexistent")` raises `ArtifactNotFoundError`.
5. `ArtifactNotFoundError` is a subclass of `KeyError`.
6. `ArtifactStore.register(..., artifact_type="unsupported_type")` raises `ValueError`.
7. `ArtifactStore.list(run_id="r1")` returns only records whose `run_id == "r1"`.
8. `ArtifactStore.list()` returns records sorted by `created_at` descending.

**ProvenanceStore**
9. `ProvenanceStore.record(artifact_id, run_id, node_id, node_type, graph_hash, [])` writes `{artifact_id}.json` and appends to `by_run/{run_id}.json`.
10. Calling `record()` twice with the same `artifact_id` does not create duplicate entries in `by_run/{run_id}.json`.
11. `ProvenanceStore.get_lineage("unknown_id")` returns `{"artifact_id": "unknown_id", "inputs": [], "error": "no_provenance_record"}` without raising.
12. `ProvenanceStore.get_lineage(artifact_id)` returns a dict with `"run_id"`, `"node_type"`, `"inputs"` keys for a registered artifact.
13. `ProvenanceStore.find_by_run("unknown_run")` returns `[]` without raising.
14. `ProvenanceStore.find_reproducible(graph_hash)` returns all records with that `graph_hash`.

---

### Requirement 21: Ingestion Service (`app/core/ingestion.py`)

1. `IngestionJob(job_id="x", status="running")` constructs with `progress=[]`.
2. `IngestionJob.append_progress({"step": 1})` appends to `progress` (thread-safe).
3. `IngestionJob.read_progress()` returns a snapshot list without mutating the original.
4. Two `IngestionJob` instances do not share the same `progress` list.
5. `IngestionService.start_url_job(urls, label)` returns a non-empty `job_id` string immediately.
6. `IngestionService.get_job(job_id)` returns the `IngestionJob` for a started job.
7. `IngestionService.get_job("nonexistent")` raises `KeyError`.
8. `IngestionService.start_hf_job(repo_id, split, audio_col, None, None)` returns a non-empty `job_id` string immediately.

---

### Requirement 22: Project Manager (`app/core/project_manager.py`)

1. `ProjectManager.create("my-project")` creates a `project.json` with `status="draft"` and `versions=[]`.
2. `ProjectManager.create("my-project")` called twice raises `ValueError`.
3. `ProjectManager.delete("my-project", confirm="my-project")` removes the project directory.
4. `ProjectManager.delete("my-project", confirm="wrong")` raises `ValueError`.
5. `ProjectManager.rename("old", "new")` moves the directory and updates `project.json["name"]`.
6. `ProjectManager.set_status("proj", "archived")` updates `project.json["status"]`.
7. `ProjectManager.set_status("proj", "invalid_status")` raises `ValueError`.
8. `ProjectManager.set_taxonomy("proj", [{"name": "a"}, {"name": "a"}])` raises `ValueError` (duplicate sibling).
9. `ProjectManager.set_contract("proj", {"min_duration_ms": 500, "max_duration_ms": 200})` raises `ValueError`.
10. `ProjectManager.add_annotations("proj", [{"sample_path": "x.wav", "label": "yes"}])` writes to `annotations.jsonl`.
11. `ProjectManager.export_annotations("proj", "csv")` returns a CSV string with a header row.
12. `ProjectManager.diff_versions("proj", "v1", "v2")` returns `{"added": N, "removed": N, "changed": N}`.

---

### Requirement 23: Quality Checker (`app/core/quality_checker.py`)

1. `QualityChecker._check_duration_range(path, 100.0, {"min_duration_ms": 200})` returns a finding with `check_name="duration_range"` and `severity="error"`.
2. `QualityChecker._check_duration_range(path, 500.0, {"min_duration_ms": 200, "max_duration_ms": 1000})` returns `[]` (no findings).
3. `QualityChecker._check_sample_rate(path, 8000, {"required_sample_rate": 16000})` returns a finding with `check_name="sample_rate"`.
4. `QualityChecker._check_clipping(path, np.array([0.0, 1.0, 1.0]))` returns a finding with `check_name="clipping"`.
5. `QualityChecker._check_dc_offset(path, np.full(100, 0.05))` returns a finding with `check_name="dc_offset"`.
6. `QualityChecker._check_class_imbalance({"a": 100, "b": 5})` returns a finding for label `"b"` with `check_name="class_imbalance"`.
7. `QualityChecker._check_class_imbalance({"a": 100, "b": 90})` returns `[]` (balanced).
8. `QualityChecker._finding("x.wav", "clipping", "warning", "detail")` returns a dict with all four keys.

---

### Requirement 24: REST API Routers — Per-File (`app/api/routers/`)

All tests use `fastapi.testclient.TestClient`. External services (ArtifactStore, ProvenanceStore, PluginManager, ProjectManager, IngestionService) are mocked.

**run_control.py**
1. `POST /api/v1/runs/{run_id}/pause` with an active run returns HTTP 200 `{"run_id": ..., "status": "paused"}`.
2. `POST /api/v1/runs/{run_id}/pause` with no active run returns HTTP 404 with `{"error": "run_not_active"}`.
3. `POST /api/v1/runs/{run_id}/resume` with an active run returns HTTP 200 `{"status": "running"}`.
4. `POST /api/v1/runs/{run_id}/cancel` with an active run returns HTTP 200 `{"status": "cancelled"}`.

**artifacts.py**
5. `GET /api/v1/artifacts` returns HTTP 200 with a JSON array.
6. `GET /api/v1/artifacts?run_id=r1` passes `run_id="r1"` to `ArtifactStore.list()`.
7. `GET /api/v1/artifacts/{valid_id}` returns HTTP 200 with the artifact record dict.
8. `GET /api/v1/artifacts/{valid_id}` returns HTTP 404 when `ArtifactNotFoundError` is raised.
9. `GET /api/v1/artifacts/bad!id` returns HTTP 400 (invalid characters).
10. `GET /api/v1/artifacts/{id}/lineage` returns HTTP 200 with a lineage dict (never 404).
11. `POST /api/v1/artifacts/{id}/replay` returns HTTP 404 when artifact is not found.
12. `POST /api/v1/artifacts/{id}/replay` returns HTTP 422 when `graph.json` is missing.

**data.py**
13. `GET /api/v1/data/inputs` returns HTTP 200 with a JSON array.
14. `GET /api/v1/data/inputs/{label}` returns HTTP 404 when the label directory does not exist.
15. `GET /api/v1/data/outputs` returns HTTP 200 with a JSON array.
16. `GET /api/v1/data/outputs/{project}/{version}` returns HTTP 404 when the dataset does not exist.
17. `POST /api/v1/data/merge` with empty `sources` returns HTTP 422.
18. `POST /api/v1/data/inputs/upload` with an unsupported extension returns HTTP 400.

**ingest.py**
19. `POST /api/v1/ingest/url` with `urls=[]` returns HTTP 422.
20. `POST /api/v1/ingest/url` with valid body returns HTTP 200 `{"job_id": "..."}`.
21. `GET /api/v1/ingest/url/{job_id}/stream` returns HTTP 404 for unknown `job_id`.
22. `POST /api/v1/ingest/huggingface` with empty `repo_id` returns HTTP 422.

**projects.py**
23. `GET /api/v1/projects` returns HTTP 200 with a JSON array.
24. `POST /api/v1/projects` with `{"name": "test-proj"}` returns HTTP 200 with project metadata.
25. `DELETE /api/v1/projects/{name}` with wrong `confirm` returns HTTP 422.
26. `GET /api/v1/projects/{name}/taxonomy` returns HTTP 404 when project does not exist.

---

### Requirement 25: MCP Auth and Tool Registry (`app/mcp/auth.py`, `app/mcp/tool_registry.py`)

**auth.py**
1. `check_auth({})` returns `None` when `GRAPHYN_API_TOKEN` is unset (no auth required).
2. `check_auth({"_meta": {"auth_token": "correct"}})` returns `None` when token matches `GRAPHYN_API_TOKEN`.
3. `check_auth({"_meta": {"auth_token": "wrong"}})` returns a dict with `"error_type": "unauthorized"` when token does not match.
4. `check_auth({})` returns a dict with `"error_type": "unauthorized"` when `GRAPHYN_API_TOKEN` is set but no token is provided.
5. The returned error dict contains `"error": True`, `"error_type": "unauthorized"`, and `"message"` keys.

**tool_registry.py**
6. `register_all_tools(register_fn)` calls `register_fn` exactly 15 times (one per MCP tool).
7. The tool names registered are exactly: `list_nodes`, `generate_graph`, `validate_graph`, `get_graph_schema`, `get_graph_capability_summary`, `get_event_schema`, `execute_pipeline`, `inspect_run`, `pause_run`, `resume_run`, `cancel_run`, `list_artifacts`, `get_artifact_lineage`, `replay_run`, `optimize_execution`.
8. Each call to `register_fn` passes a non-empty description string and a non-empty input schema dict.
