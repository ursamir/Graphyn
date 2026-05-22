# Requirements Document — App Pydantic Migration and FastAPI Redesign

## Introduction

The Enhanced Node System (`app/core/nodes/`) has been fully built and all 27 audio nodes have been migrated to it. AudioBuilder is a **universal data pipeline builder** — not just audio. The new node system supports any domain (Audio, ML, Data, Automation, Video). This feature completes the migration by updating every remaining consumer of the old dict-based registry format — the plugin, SDK, CLI, FastAPI layer, logger, run manager, ingestion service, and pipeline cache — so that the entire application is consistent, uses Pydantic v2 models throughout, and contains no legacy compatibility shims.

Additionally, this feature delivers a **complete FastAPI redesign** that exposes the full power of the new node system: rich node discovery, type compatibility queries, TypeCatalogue browsing, DAG pipeline support, and a properly versioned, router-split API under `/api/v1/`.

The scope covers fifteen discrete migration and redesign targets:

1. `plugins/noise_node.py` — migrate to new `Node` subclass pattern
2. `app/core/sdk.py` — rewrite `Node` wrapper and `Pipeline` to use `NodeRegistry`
3. `app/cli/main.py` — update `cmd_validate` to use `NodeRegistry` API
4. `app/core/logger.py` — fix deprecated `datetime.utcnow()` and structured `node_end`
5. `app/core/run_manager.py` — fix deprecated `datetime.utcnow()`
6. `app/core/ingestion.py` — migrate `IngestionJob` dataclass to Pydantic `BaseModel`
7. `app/core/webhook.py` — no changes required (already clean)
8. `app/core/pipeline_cache.py` — use `AudioSample.model_validate()` for cache reads
9. Remove all legacy dict registry references codebase-wide
10. Complete FastAPI restructure with API versioning (`/api/v1/` prefix, split routers)
11. Node Catalogue API — rich node discovery, port introspection, type compatibility
12. Pipeline API with DAG support — validate and execute pipelines in both linear and DAG format
13. Fix `/run-async` run ID tracking — eliminate the dual-RunManager bug
14. Generalize pipeline validation rules — remove hardcoded audio-specific constraints
15. `NodeRegistry` compatibility shims — `__getitem__`, `keys()`, `items()` for legacy callers

After this migration, zero references to the old `NODE_REGISTRY` dict format, `registry[node_type]["schema"]`, or `registry[node_type]["class"]` patterns shall remain anywhere in the codebase, and the API shall be fully versioned, router-split, and capable of serving any pipeline domain.

---

## Glossary

- **Node**: A `app.core.nodes.base.Node` subclass that declares typed ports, a `NodeConfig` inner class, and a `NodeMetadata` class variable. The canonical unit of the Enhanced Node System.
- **NodeRegistry**: The singleton (`app.core.nodes.registry.NodeRegistry`) that maps node type strings to `Node` subclasses and `NodeMetadata`. Accessed via `app.core.registry_runtime.get_registry()`.
- **NodeConfig**: A `pydantic.BaseModel` subclass (from `app.core.nodes.config`) that holds validated, typed configuration for a node.
- **NodeMetadata**: A Pydantic model (`app.core.nodes.metadata.NodeMetadata`) describing a node's identity, category, version, tags, and port definitions.
- **AutoDiscovery**: The mechanism in `app.core.nodes.discovery` that scans `app/core/nodes/` and the `plugins/` directory at import time, registering `Node` subclasses automatically without any `register()` function.
- **InputPort / OutputPort**: Typed port descriptors declared as class variables on a `Node` subclass.
- **TypeCatalogue**: The registry of all `PortDataType` subclasses, accessible via `registry.type_catalogue`. Supports `list_types()` and `resolve(fqn)`.
- **CompatibilityChecker**: The service in `app.core.nodes.compat` that determines whether two port data types are compatible for connection.
- **DAG Pipeline Format**: A pipeline specification that uses explicit `edges` to connect named ports on named nodes, as opposed to the legacy linear format where nodes are connected implicitly in sequence.
- **Linear Pipeline Format**: The legacy pipeline YAML format where nodes are listed in order and connected implicitly output-to-input.
- **Old Dict Registry**: The legacy format where nodes were stored as `registry[node_type] = {"class": ..., "schema": ..., "label": ..., ...}`. This format must be fully removed.
- **SDK_Node / PipelineNode**: The `Node` class currently defined in `app/core/sdk.py` that shadows the real `Node` base class. Must be renamed to `PipelineNode`.
- **PipelineLogger**: The structured event logger in `app/core/logger.py` used by the pipeline executor and streaming endpoints.
- **RunManager**: The run lifecycle manager in `app/core/run_manager.py` that writes `meta.json`, `config.yaml`, and `logs.json` to `workspace/runs/{run_id}/`.
- **IngestionJob**: The job state object in `app/core/ingestion.py` that tracks background download progress.
- **PipelineCache**: The node-output cache in `app/core/pipeline_cache.py` that reads and writes `AudioSample` lists to disk.
- **AudioSample**: The Pydantic `BaseModel` in `app/models/audio_sample.py` representing a single audio sample with `path`, `sample_rate`, `data`, `label`, and `metadata` fields.
- **UTC-aware datetime**: A `datetime` object produced by `datetime.now(timezone.utc)` (Python 3.12+ preferred form) rather than the deprecated `datetime.utcnow()`.
- **API Router**: A FastAPI `APIRouter` instance in `app/api/routers/` that groups related endpoints. The redesign splits the monolithic `main.py` into focused routers: `nodes.py`, `pipelines.py`, `runs.py`, `data.py`, `ingest.py`, `system.py`.
- **Deprecated Alias**: A root-path endpoint (e.g. `GET /schemas`) that returns HTTP 301 redirecting to the new versioned path (e.g. `GET /api/v1/nodes`) for backward compatibility during a 6-month transition period.
- **ProjectManager**: The domain-specific service in `app/core/project_manager.py` that manages audio dataset projects. Its router (`projects.py`) is moved under `/api/v1/` but otherwise unchanged.

---

## Requirements

### Requirement 1: Migrate NoiseNode Plugin to the Enhanced Node System

**User Story:** As a developer, I want the `plugins/noise_node.py` plugin to use the new `Node` subclass pattern, so that it is auto-discovered by `AutoDiscovery` and registered in `NodeRegistry` without any manual `register()` function.

#### Acceptance Criteria

1. THE `NoiseNode` SHALL subclass `app.core.nodes.base.Node` and declare a `metadata` class variable of type `NodeMetadata` with `node_type="noise"`, a non-empty `label`, `description`, and `category`.
2. THE `NoiseNode` SHALL declare typed `input_ports` and `output_ports` using `InputPort` and `OutputPort` with `data_type=list[AudioSample]`.
3. THE `NoiseNode` SHALL declare an inner `Config(NodeConfig)` class with a `noise_level: float` field and a default value of `0.005`.
4. THE `NoiseNode` SHALL implement `process(self, samples)` using the SISO shorthand, accepting and returning `list[AudioSample]`.
5. THE `NoiseNode.process` method SHALL add Gaussian noise scaled by `self.config.noise_level` to each sample's `data` array and return the modified samples.
6. WHEN `AutoDiscovery` scans the `plugins/` directory, THE `NodeRegistry` SHALL contain an entry for `"noise"` that maps to `NoiseNode` without any `register()` call.
7. THE `plugins/noise_node.py` file SHALL NOT contain a `register` function or any reference to the old dict-based registry format.
8. IF `NoiseNode` is instantiated with a config dict missing `noise_level`, THEN THE `NodeConfig` validation SHALL raise a `pydantic.ValidationError`.

---

### Requirement 2: Rewrite SDK Node Wrapper to Use NodeRegistry

**User Story:** As a developer using the SDK, I want `app/core/sdk.py` to validate node types and configs against the real `NodeRegistry`, so that SDK pipelines use the same validation path as the CLI and API.

#### Acceptance Criteria

1. THE `app/core/sdk.py` module SHALL rename the `Node` class to `PipelineNode` to avoid shadowing `app.core.nodes.base.Node`.
2. WHEN a `PipelineNode` is instantiated with a `node_type` that is not in `NodeRegistry`, THE `PipelineNode.__init__` SHALL raise a `ValueError` containing the unknown type name and the list of available types.
3. WHEN a `PipelineNode` is instantiated with a `config` dict, THE `PipelineNode.__init__` SHALL validate the config by calling `NodeRegistry.get_class(node_type).Config.model_validate(config)` and raise a `ValueError` wrapping any `pydantic.ValidationError` that results.
4. THE `PipelineNode._validate` method SHALL use `registry.get_class(node_type)` and SHALL NOT use `registry[node_type]` dict-style access.
5. THE `PipelineNode._validate` method SHALL NOT call the legacy `validate_node_config` function with a raw schema dict.
6. THE `Pipeline.run` method SHALL continue to write a temporary YAML file and call `run_pipeline()` as it does today; no change to the execution path is required.
7. THE `Pipeline.from_yaml` class method SHALL construct `PipelineNode` instances (not the old `Node` instances).
8. THE `app/core/sdk.py` module SHALL NOT contain any reference to `registry[node_type]["schema"]` or `registry[node_type]["class"]`.

---

### Requirement 3: Update CLI Validate Command to Use NodeRegistry API

**User Story:** As a CLI user, I want the `validate` subcommand to use the new `NodeRegistry` accessor methods, so that node type lookups are consistent with the rest of the application.

#### Acceptance Criteria

1. THE `cmd_validate` function in `app/cli/main.py` SHALL call `registry.get_class(node_type)` to check whether a node type exists, and SHALL NOT use `node_type in registry` followed by `registry[node_type]` dict-style access.
2. WHEN `validate_pipeline` raises a `ValueError` for an unknown node type, THE `cmd_validate` function SHALL print the error message to stderr and exit with code 1.
3. THE `cmd_validate` function SHALL continue to call `validate_pipeline(config, registry)` and print the count and list of validated nodes on success, preserving the existing output format.
4. THE `app/cli/main.py` file SHALL NOT contain any reference to `registry[node_type]["schema"]` or `registry[node_type]["class"]`.
5. WHEN `cmd_validate` is called with a valid pipeline YAML, THE CLI SHALL exit with code 0 and print a line beginning with `"✓ Valid pipeline"`.

---

### Requirement 4: Fix Deprecated datetime.utcnow() in PipelineLogger

**User Story:** As a developer, I want `PipelineLogger` to use timezone-aware UTC datetimes, so that the application does not emit deprecation warnings on Python 3.12 and produces ISO 8601 timestamps with explicit UTC offset.

#### Acceptance Criteria

1. THE `PipelineLogger._timestamp` method SHALL return `datetime.now(timezone.utc).isoformat()` and SHALL NOT call `datetime.utcnow()`.
2. ALL calls to `datetime.utcnow()` in `app/core/logger.py` SHALL be replaced with `datetime.now(timezone.utc)`.
3. THE `PipelineLogger.node_end` method SHALL accept an explicit `output_count: int` parameter (defaulting to `0`) instead of parsing an integer from a `count_str` string.
4. WHEN `node_end` is called with `output_count=3`, THE structured event emitted SHALL contain `"output_count": 3` without any regex parsing.
5. THE `PipelineLogger.node_end` method SHALL still emit a human-readable log line that includes the node type, duration, and output count.
6. THE `app/core/logger.py` file SHALL NOT import or call `re.search` for the purpose of extracting an integer from a string.
7. WHEN `PipelineLogger.pipeline_start` is called, THE structured event SHALL contain a `"timestamp"` field whose value ends with `"+00:00"` or `"Z"` indicating UTC.

---

### Requirement 5: Fix Deprecated datetime.utcnow() in RunManager

**User Story:** As a developer, I want `RunManager` to use timezone-aware UTC datetimes, so that run metadata timestamps are consistent with the logger and do not emit deprecation warnings on Python 3.12.

#### Acceptance Criteria

1. ALL calls to `datetime.utcnow()` in `app/core/run_manager.py` SHALL be replaced with `datetime.now(timezone.utc)`.
2. THE `RunManager.__init__` method SHALL write the initial `meta.json` with a `"created_at"` value produced by `datetime.now(timezone.utc).isoformat()`.
3. THE `RunManager.save_metadata` method SHALL write `"created_at"` using `datetime.now(timezone.utc).isoformat()`.
4. THE `app/core/run_manager.py` file SHALL NOT contain any call to `datetime.utcnow()`.
5. WHEN `RunManager.save_metadata` is called, THE `meta.json` written to disk SHALL contain a `"created_at"` field whose string value is a valid ISO 8601 datetime with UTC offset.

---

### Requirement 6: Migrate IngestionJob to Pydantic BaseModel

**User Story:** As a developer, I want `IngestionJob` to be a Pydantic `BaseModel` instead of a `dataclass`, so that the ingestion module is consistent with the rest of the application's data modelling conventions.

#### Acceptance Criteria

1. THE `IngestionJob` class in `app/core/ingestion.py` SHALL subclass `pydantic.BaseModel` and SHALL NOT use `@dataclass` or `dataclasses.field`.
2. THE `IngestionJob` model SHALL declare `job_id: str`, `status: str`, and `progress: list[dict]` fields, with `progress` defaulting to an empty list via `pydantic.Field(default_factory=list)`.
3. WHEN `IngestionJob` is instantiated with only `job_id` and `status`, THE `progress` field SHALL default to `[]`.
4. THE `IngestionService` methods that mutate `job.progress` (by calling `job.progress.append(...)`) SHALL continue to work correctly after the migration.
5. THE `app/core/ingestion.py` file SHALL NOT import `dataclass` or `field` from the `dataclasses` module.
6. THE `IngestionJob` model SHALL be serialisable to a dict via `job.model_dump()` without raising an exception.

---

### Requirement 7: Fix PipelineCache AudioSample Construction

**User Story:** As a developer, I want `PipelineCache.load` to construct `AudioSample` instances using `AudioSample.model_validate()`, so that Pydantic v2 validation is applied correctly when reading cached samples from disk.

#### Acceptance Criteria

1. THE `PipelineCache.load` method SHALL construct each `AudioSample` by calling `AudioSample.model_validate({...})` with a dict built from the manifest entry and the decoded audio data.
2. THE `PipelineCache.load` method SHALL NOT call the `AudioSample(...)` constructor directly with keyword arguments when building instances from cached manifest data.
3. WHEN a manifest entry contains a `metadata` key, THE constructed `AudioSample` SHALL have its `metadata` field set to that value.
4. WHEN a manifest entry is missing the `metadata` key, THE `PipelineCache.load` method SHALL default `metadata` to `{}` before calling `model_validate`.
5. THE `PipelineCache.save` method SHALL access `AudioSample` fields using attribute access (`sample.label`, `sample.path`, `sample.sample_rate`, `sample.metadata`) and SHALL NOT use dict-style access.
6. IF `AudioSample.model_validate` raises a `pydantic.ValidationError` for a corrupt manifest entry, THEN THE `PipelineCache.load` method SHALL catch the exception, log a warning, and return `None` (triggering node re-execution).

---

### Requirement 8: Update FastAPI /schemas Endpoint to Use NodeRegistry API

**User Story:** As a frontend developer, I want the `/schemas` endpoint to return node metadata sourced from `NodeRegistry`, so that the response reflects the new typed port system and is consistent with the rest of the application.

#### Acceptance Criteria

1. THE `/schemas` GET endpoint in `app/api/main.py` SHALL build its response by iterating over `registry.list_nodes()` and calling `registry.get_config_schema(node_type)` for each node's config schema.
2. THE `/schemas` endpoint SHALL NOT iterate over `registry.items()` using dict-style access or read `node_def["schema"]`, `node_def["label"]`, or any other dict key from the old format.
3. THE `/schemas` endpoint SHALL return a JSON object keyed by `node_type`, where each value contains at minimum: `label`, `description`, `category`, `schema` (the JSON Schema of the node's `Config` model), and `kind` (defaulting to `"base"` if not present in metadata).
4. THE response shape of `/schemas` SHALL remain backward-compatible: the same top-level keys (`label`, `description`, `category`, `schema`) SHALL be present for every node type.
5. THE `/validate-node` POST endpoint SHALL check node type existence using `node_type in registry` (which calls `NodeRegistry.__contains__`) and SHALL NOT use `registry[node_type]` dict-style access.
6. THE `/validate-node` endpoint SHALL retrieve the config schema by calling `registry.get_config_schema(payload.node_type)` and SHALL NOT access `registry[payload.node_type]["schema"]`.
7. THE `app/api/main.py` file SHALL NOT contain any reference to `registry[node_type]["schema"]`, `registry[node_type]["class"]`, or `node_def.get(...)` patterns that assume a dict-based registry value.

---

### Requirement 9: Remove All Legacy Dict Registry References Codebase-Wide

**User Story:** As a developer, I want the entire codebase to be free of old dict-based registry access patterns, so that there is a single, consistent way to interact with the node registry.

#### Acceptance Criteria

1. THE codebase SHALL NOT contain any occurrence of `registry[node_type]["schema"]` after the migration is complete.
2. THE codebase SHALL NOT contain any occurrence of `registry[node_type]["class"]` after the migration is complete.
3. THE codebase SHALL NOT contain any occurrence of `registry[node_type]["label"]` or `registry[node_type]["description"]` after the migration is complete.
4. THE codebase SHALL NOT contain any `register(registry)` function in any file under `plugins/`.
5. THE `app/core/sdk.py` module SHALL NOT define a class named `Node` (the name is reserved for `app.core.nodes.base.Node`).
6. WHEN `get_registry()` is called from any module in `app/`, THE return value SHALL be the `NodeRegistry` singleton and SHALL support `registry.get_class()`, `registry.get_metadata()`, `registry.list_nodes()`, and `registry.get_config_schema()` without raising `AttributeError`.
7. THE `app/core/validation.py` legacy fallback path (the `except Exception: pass` block in `_validate_connections` that falls back to string-based type comparison) SHALL remain in place to preserve backward compatibility with any external callers that pass a non-`NodeRegistry` registry object.

---

### Requirement 10: Complete FastAPI Restructure with API Versioning

**User Story:** As an API consumer, I want all endpoints to be served under a `/api/v1/` prefix with focused routers, so that the API is versioned, maintainable, and clearly separated from static file mounts.

#### Acceptance Criteria

1. THE FastAPI application SHALL serve all new endpoints under the `/api/v1/` prefix.
2. THE `app/api/main.py` monolith SHALL be split into focused routers: `app/api/routers/nodes.py`, `app/api/routers/pipelines.py`, `app/api/routers/runs.py`, `app/api/routers/data.py`. The existing `projects.py`, `ingest.py`, `webhooks.py`, `cleanup.py`, `merge.py`, and `registry_api.py` routers SHALL be moved under the `/api/v1/` prefix.
3. THE static file mounts (`/files`, `/input-files`, `/run-files`) SHALL remain at the root level (not under `/api/v1/`) since they serve binary assets, not API responses.
4. WHEN a client requests a legacy root-path endpoint (e.g. `GET /schemas`, `POST /run-stream`, `GET /runs`), THE server SHALL return HTTP 301 with a `Location` header pointing to the corresponding `/api/v1/` path, for a minimum transition period of 6 months.
5. THE `app/api/main.py` file after restructuring SHALL contain fewer than 100 lines of application code (excluding imports and comments), with all endpoint logic delegated to routers.
6. THE existing `projects.py` and `webhooks.py` routers SHALL be included under `/api/v1/` without modification to their internal endpoint logic.
7. THE `GET /registry` endpoint (dataset project registry) SHALL be renamed to `GET /api/v1/system/projects-registry` to avoid confusion with the node registry, and a 301 redirect SHALL be added at `GET /registry`.
8. ALL calls to `datetime.utcnow()` in `app/api/main.py` SHALL be replaced with `datetime.now(timezone.utc)`.

---

### Requirement 11: Node Catalogue API

**User Story:** As a frontend developer or pipeline builder, I want a rich node catalogue API that exposes full node metadata, port definitions, config schemas, and type compatibility queries, so that I can build dynamic UIs and pipeline validation tools without hardcoding node knowledge.

#### Acceptance Criteria

1. THE `GET /api/v1/nodes` endpoint SHALL return a JSON array of all registered nodes, where each entry contains: `node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`, and `config_schema` (the JSON Schema of the node's `Config` model).
2. WHEN `GET /api/v1/nodes` is called with a `category` query parameter, THE endpoint SHALL return only nodes whose `category` field matches the provided value.
3. THE `GET /api/v1/nodes/{node_type}` endpoint SHALL return the full metadata for a single node type. IF the node type is not registered, THEN THE endpoint SHALL return HTTP 404.
4. THE `GET /api/v1/nodes/{node_type}/config-schema` endpoint SHALL return the JSON Schema dict for the node's `Config` model, sourced from `registry.get_config_schema(node_type)`.
5. THE `GET /api/v1/nodes/{node_type}/port-schema` endpoint SHALL return the port definitions for the node, sourced from `registry.get_port_schema(node_type)`, containing `input_ports` and `output_ports` dicts.
6. THE `GET /api/v1/nodes/compatible` endpoint SHALL accept `output_type` (a fully-qualified type name string) and `direction` (`"input"` or `"output"`) query parameters and return a JSON array of `NodeMetadata` entries for nodes compatible with that port type, sourced from `registry.find_compatible_nodes(resolved_type, direction)`.
7. WHEN `GET /api/v1/nodes/compatible` is called with an `output_type` that is not registered in `TypeCatalogue`, THE endpoint SHALL return HTTP 400 with a descriptive error message.
8. THE `GET /api/v1/types` endpoint SHALL return a JSON array of all fully-qualified type name strings registered in `registry.type_catalogue`, sourced from `registry.type_catalogue.list_types()`.

---

### Requirement 12: Pipeline API with DAG Support

**User Story:** As a pipeline builder, I want to validate and execute pipelines in both the legacy linear format and the new explicit DAG format with named edges, so that I can build multi-port, multi-branch pipelines that the old linear format cannot express.

#### Acceptance Criteria

1. THE `POST /api/v1/pipelines/validate` endpoint SHALL accept a JSON body with a `yaml` string field and return `{"valid": true}` on success or `{"valid": false, "error": "<message>"}` on failure.
2. THE `POST /api/v1/pipelines/validate` endpoint SHALL accept pipeline YAML in both the legacy linear format (nodes listed in order, implicit connections) and the new DAG format (nodes with `id` fields plus an `edges` list specifying `from_node`, `from_port`, `to_node`, `to_port`).
3. THE `POST /api/v1/pipelines/run` endpoint SHALL accept the same `{"yaml": "..."}` payload as the legacy `/run-stream` and SHALL stream NDJSON events with the same event types: `pipeline_start`, `node_start`, `node_end`, `node_error`, `pipeline_summary`, `done`, `error`.
4. THE `POST /api/v1/pipelines/run-async` endpoint SHALL accept the same `{"yaml": "..."}` payload as the legacy `/run-async` and SHALL return `{"run_id": "<id>"}` immediately.
5. THE `GET /api/v1/pipelines/templates` endpoint SHALL return the same response as the legacy `GET /templates`.
6. THE `GET /api/v1/pipelines/templates/{name}` endpoint SHALL return the same response as the legacy `GET /template/{name}`.
7. THE `POST /api/v1/pipelines/templates` endpoint SHALL save a user-defined template, accepting `{"name": "<alphanumeric>", "yaml": "<yaml string>"}`.
8. THE `DELETE /api/v1/pipelines/templates/{name}` endpoint SHALL delete a named template.

---

### Requirement 13: Fix /run-async Run ID Tracking

**User Story:** As a developer, I want the `/run-async` endpoint to return the same `run_id` that the pipeline executor uses, so that polling `/api/v1/runs/{run_id}/status` always finds the correct run directory.

#### Acceptance Criteria

1. THE `POST /api/v1/pipelines/run-async` endpoint SHALL create exactly one `RunManager` instance before starting the background thread, and SHALL return that instance's `run_id` to the caller.
2. THE background thread started by `POST /api/v1/pipelines/run-async` SHALL use the same `RunManager` instance (or the same `run_id`) that was returned to the caller, so that `workspace/runs/{run_id}/` is populated by the executing pipeline.
3. THE `POST /api/v1/pipelines/run-async` endpoint SHALL NOT create a second `RunManager` inside the background thread that would produce a different `run_id`.
4. WHEN the background thread completes successfully, THE `workspace/runs/{run_id}/meta.json` SHALL contain `"status": "completed"`.
5. WHEN the background thread fails with an exception, THE `workspace/runs/{run_id}/meta.json` SHALL contain `"status": "failed"` and an `"error"` field with the exception message.
6. THE `GET /api/v1/runs/{run_id}/status` endpoint SHALL return `{"status": "completed"}` after a successful async run, reading from the `meta.json` written by the single `RunManager`.

---

### Requirement 14: Generalize Pipeline Validation Rules

**User Story:** As a pipeline builder working with non-audio domains, I want pipeline validation to check only structural correctness (node types exist, configs are valid, port types are compatible), so that I can build pipelines that do not start with an audio input node or end with an export node.

#### Acceptance Criteria

1. THE `validate_pipeline` function in `app/core/validation.py` SHALL NOT raise a `ValueError` solely because the first node's type is not `"input"` or `"mic_input"`.
2. THE `validate_pipeline` function SHALL NOT raise a `ValueError` solely because the last node's type is not `"export"`, `"hf_export"`, or `"tfrecord_export"`.
3. THE `validate_pipeline` function SHALL raise a `ValueError` when a node type referenced in the pipeline config is not registered in `NodeRegistry`.
4. THE `validate_pipeline` function SHALL raise a `ValueError` when a node's config dict fails validation against its `NodeConfig` model.
5. WHEN port type information is available via `CompatibilityChecker`, THE `validate_pipeline` function SHALL raise a `ValueError` when two connected ports have incompatible data types.
6. THE `POST /api/v1/pipelines/validate` endpoint SHALL use the generalized `validate_pipeline` function and SHALL NOT add any audio-specific validation rules on top of it.
7. THE legacy `validate_pipeline` behaviour for pipelines that do start with `input`/`mic_input` and end with `export` SHALL be preserved — such pipelines SHALL still pass validation.

---

### Requirement 15: NodeRegistry Compatibility Shims

**User Story:** As a developer, I want `NodeRegistry` to implement `__getitem__`, `keys()`, and `items()` compatibility shims, so that legacy callers in `validation.py` and any other code that uses dict-style registry access continue to work without modification.

#### Acceptance Criteria

1. THE `NodeRegistry` class SHALL implement a `__getitem__(self, node_type: str) -> dict` method that returns a dict containing at minimum: `"class"`, `"schema"`, `"label"`, `"description"`, `"category"`, `"kind"`, `"input_type"`, and `"output_type"` keys, sourced from `NodeMetadata` and `Config.model_json_schema()`.
2. WHEN `registry[node_type]` is called with an unregistered `node_type`, THE `__getitem__` method SHALL raise `NodeNotFoundError` (not `KeyError`).
3. THE `NodeRegistry` class SHALL implement a `keys(self)` method that returns the same key view as `self._classes.keys()`.
4. THE `NodeRegistry` class SHALL implement an `items(self)` method that returns an iterable of `(node_type, dict)` pairs, where each dict is the same format returned by `__getitem__`.
5. THE `app/core/validation.py` file SHALL NOT be modified as part of this migration — the shims in `NodeRegistry` SHALL be sufficient to make it work correctly.
6. WHEN `validate_pipeline` in `app/core/validation.py` calls `registry[node_type]["schema"]`, THE shim SHALL return the JSON Schema dict produced by `node_class.Config.model_json_schema()`.
7. THE compatibility shims SHALL be documented with a comment in `app/core/nodes/registry.py` indicating they exist for backward compatibility and should not be used in new code.
