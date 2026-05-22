# Bugfix Requirements Document

## Introduction

Five critical bugs were identified in a deep technical review of the Graphyn Pipeline Engine (`app/core/pipeline.py`, `app/core/sdk.py`, `app/core/run_manager.py`, `app/core/nodes/errors.py`, `app/core/artifact_store.py`, `app/core/executor.py`). These bugs affect core runtime correctness, observability, code organisation, and the public SDK API:

- **Bug 1** — `run_pipeline_ir_async` is defined twice in `pipeline.py`; the first definition is dead code silently shadowed by the second.
- **Bug 2** — `run_pipeline_ir_async` creates a second `run_id` via `uuid.uuid4()` and passes it to `NodeExecutor`, so observer events reference a different ID than the one persisted to disk by `RunManager`.
- **Bug 3** — `ResumeError` is defined in `pipeline.py` but imported by `run_manager.py` via a deferred in-method import to avoid a circular dependency; it should live in `app/core/nodes/errors.py` with the other execution errors.
- **Bug 4** — `_infer_artifact_type()` encodes domain knowledge about `AudioSample` and `DatasetArtifact` inside `pipeline.py` and is imported by `executor.py`; it should live in `app/core/artifact_store.py`.
- **Bug 5** — `Pipeline.validate()` in `sdk.py` calls `validate_pipeline(pipeline_cfg)` with only one argument; `validate_pipeline` requires two (`config, registry`), so every call raises `TypeError` and the method is completely non-functional.

## Bug Analysis

### Current Behavior (Defect)

**Bug 1 — Duplicate `run_pipeline_ir_async` definition**

1.1 WHEN `run_pipeline_ir_async` is called at runtime THEN the system executes only the second definition of the function (around line 680 in `pipeline.py`), silently shadowing the first definition (around lines 450–600).

1.2 WHEN a developer modifies the first definition of `run_pipeline_ir_async` THEN the system ignores those changes at runtime, producing no observable effect and no error.

1.3 WHEN `app/core/pipeline.py` is read THEN the system presents two syntactically valid, identically-signed definitions of `run_pipeline_ir_async` in the same module scope.

**Bug 2 — Dual `run_id`: RunManager ID vs executor UUID4**

1.4 WHEN `run_pipeline_ir_async` executes THEN the system creates two distinct `run_id` values: `run.run_id` (a 16-character hex string from `RunManager.__init__`) and a separate `run_id = str(uuid.uuid4())` (a full UUID4 string generated inside `run_pipeline_ir_async`), and these two values are never equal.

1.5 WHEN `NodeExecutor` instances are constructed inside `run_pipeline_ir_async` THEN the system passes the UUID4 `run_id` to each executor, so observer callbacks (`on_node_start`, `on_node_end`, `on_node_error`) receive the UUID4 value as the run identifier.

1.6 WHEN the run completes and metadata is persisted to disk THEN the system writes `RunManager.run_id` (16-char hex) to `meta.json` and uses it as the run directory name, while observer events have already been emitted with the UUID4 value.

1.7 WHEN tooling or monitoring systems attempt to correlate observer events with persisted run metadata by matching `run_id` values THEN the system silently fails to find a match because the two IDs are different values.

**Bug 3 — Circular import: `ResumeError` in `pipeline.py`, imported by `run_manager.py`**

1.8 WHEN `RunManager.load_resume_state()` needs to raise `ResumeError` THEN the system performs a deferred import `from app.core.pipeline import ResumeError` inside the method body to avoid a circular import at module load time.

1.9 WHEN `RunManager.find_latest_checkpoint()` needs `_load_checkpoint_outputs` THEN the system performs a second deferred import `from app.core.pipeline import _load_checkpoint_outputs` inside the method body for the same reason.

1.10 WHEN `app/core/nodes/errors.py` is read THEN the system shows all other execution-related errors (`NodeSystemError`, `NodeNotFoundError`, `PipelineGraphError`, etc.) defined there, but `ResumeError` is absent, violating the established error hierarchy convention.

**Bug 4 — `_infer_artifact_type` is a domain function living in `pipeline.py`**

1.11 WHEN `pipeline.py` is read THEN the system contains `_infer_artifact_type()`, a function that encodes domain knowledge about `AudioSample`, `DatasetArtifact`, and feature-array duck-typing — domain concerns that belong in the artifact layer, not in the pipeline orchestration module.

1.12 WHEN `executor.py` needs to infer the artifact type of a node output THEN the system imports `_infer_artifact_type` from `pipeline.py` via `from app.core.pipeline import _infer_artifact_type`, creating a cross-layer dependency from the executor into the pipeline orchestration module.

1.13 WHEN `artifact_store.py` is read THEN the system shows no `_infer_artifact_type` function, even though `ArtifactStore` is the module responsible for registering and typing artifacts.

**Bug 5 — `Pipeline.validate()` always raises `TypeError`**

1.14 WHEN `Pipeline.validate()` is called THEN the system calls `validate_pipeline(pipeline_cfg)` with only one argument, but `validate_pipeline` requires two positional arguments `(config, registry)`, causing a `TypeError` on every invocation.

1.15 WHEN the `TypeError` is raised inside `Pipeline.validate()` THEN the system catches it with a bare `except Exception` block and appends the `TypeError` message string to the `errors` list, so the method always returns a non-empty list regardless of whether the pipeline is actually valid.

1.16 WHEN a caller checks `if not pipeline.validate()` to determine pipeline validity THEN the system always evaluates the condition as `False` (errors list is never empty), making it impossible to distinguish a valid pipeline from an invalid one via this method.

---

### Expected Behavior (Correct)

**Bug 1 — Duplicate `run_pipeline_ir_async` definition**

2.1 WHEN `run_pipeline_ir_async` is called at runtime THEN the system SHALL execute exactly one, canonical definition of the function with no shadowing.

2.2 WHEN a developer modifies `run_pipeline_ir_async` THEN the system SHALL reflect those changes at runtime on the next invocation.

2.3 WHEN `app/core/pipeline.py` is read THEN the system SHALL contain exactly one definition of `run_pipeline_ir_async`.

**Bug 2 — Dual `run_id`: RunManager ID vs executor UUID4**

2.4 WHEN `run_pipeline_ir_async` executes THEN the system SHALL use a single `run_id` value — `run.run_id` — for all purposes: `NodeExecutor` construction, observer event emission, run directory naming, and metadata persistence.

2.5 WHEN observer callbacks receive a `run_id` THEN the system SHALL ensure that `run_id` matches the value stored in `meta.json` and used as the run directory name.

2.6 WHEN `ParallelExecutor.run_wave` is called with a `run_id` argument THEN the system SHALL pass `run.run_id` rather than a separately generated UUID4.

**Bug 3 — Circular import: `ResumeError` in `pipeline.py`, imported by `run_manager.py`**

2.7 WHEN `ResumeError` is needed by any module THEN the system SHALL allow it to be imported from `app/core/nodes/errors.py` without triggering a circular import.

2.8 WHEN `run_manager.py` raises `ResumeError` THEN the system SHALL import it from `app/core/nodes/errors.py` at the top of the file rather than using a deferred in-method import.

2.9 WHEN `app/core/nodes/errors.py` is read THEN the system SHALL contain `ResumeError` alongside the other execution error classes.

2.10 WHEN `pipeline.py` references `ResumeError` THEN the system SHALL import it from `app/core/nodes/errors.py`.

**Bug 4 — `_infer_artifact_type` is a domain function living in `pipeline.py`**

2.11 WHEN `_infer_artifact_type` is needed THEN the system SHALL provide it from `app/core/artifact_store.py`, co-located with `ArtifactStore`, `ArtifactRecord`, and `SUPPORTED_ARTIFACT_TYPES`.

2.12 WHEN `executor.py` calls `_infer_artifact_type` THEN the system SHALL import it from `app/core/artifact_store.py`.

2.13 WHEN `app/core/pipeline.py` is read THEN the system SHALL NOT contain a definition of `_infer_artifact_type`.

**Bug 5 — `Pipeline.validate()` always raises `TypeError`**

2.14 WHEN `Pipeline.validate()` is called on a structurally valid pipeline THEN the system SHALL call `validate_pipeline(pipeline_cfg, registry)` with both required arguments and SHALL return an empty list `[]`.

2.15 WHEN `Pipeline.validate()` is called on an invalid pipeline THEN the system SHALL return a non-empty list of human-readable error strings describing the specific validation failures.

2.16 WHEN `Pipeline.validate()` is called THEN the system SHALL obtain the `registry` argument by calling `get_registry()` from `app.core.registry_runtime`.

---

### Unchanged Behavior (Regression Prevention)

**Bug 1 — Duplicate `run_pipeline_ir_async` definition**

3.1 WHEN `run_pipeline_ir_async` is called with any valid `GraphIR` and execution parameters THEN the system SHALL CONTINUE TO execute the pipeline and return the final node's output dict.

3.2 WHEN `run_pipeline_ir` (the synchronous shim) is called THEN the system SHALL CONTINUE TO delegate to `run_pipeline_ir_async` via `asyncio.run()` and return the same result.

3.3 WHEN `parallel=True` is passed THEN the system SHALL CONTINUE TO use `ParallelExecutor` for wave-based execution.

3.4 WHEN `resume_run_id` is provided THEN the system SHALL CONTINUE TO load prior checkpoint state and skip completed nodes.

**Bug 2 — Dual `run_id`: RunManager ID vs executor UUID4**

3.5 WHEN `run_pipeline_ir_async` is called with an externally supplied `run_manager` THEN the system SHALL CONTINUE TO use that manager's `run_id` without creating a new one.

3.6 WHEN `RunManager` generates its `run_id` in `__init__` THEN the system SHALL CONTINUE TO use 16 hex characters derived from `uuid.uuid4()`.

3.7 WHEN observer events are emitted for `node_start`, `node_end`, and `node_error` THEN the system SHALL CONTINUE TO emit them with the correct node type and timing information.

**Bug 3 — Circular import: `ResumeError` in `pipeline.py`, imported by `run_manager.py`**

3.8 WHEN `RunManager.load_resume_state()` cannot find a prior run or its state file THEN the system SHALL CONTINUE TO raise `ResumeError` with a descriptive message.

3.9 WHEN `run_pipeline_ir_async` encounters a resume failure THEN the system SHALL CONTINUE TO propagate `ResumeError` to the caller.

3.10 WHEN `app/core/nodes/errors.py` is imported THEN the system SHALL CONTINUE TO export all existing error classes (`NodeSystemError`, `NodeNotFoundError`, `DuplicateNodeTypeError`, `NodeMetadataError`, `NodeTypeError`, `PortTypeNotFoundError`, `DuplicatePortTypeError`, `PipelineGraphError`).

**Bug 4 — `_infer_artifact_type` is a domain function living in `pipeline.py`**

3.11 WHEN `_infer_artifact_type` receives a list of `AudioSample`-like objects (with `data` and `sample_rate` attributes) THEN the system SHALL CONTINUE TO return `"audio_samples"`.

3.12 WHEN `_infer_artifact_type` receives a `DatasetArtifact` instance THEN the system SHALL CONTINUE TO return `"generic"`.

3.13 WHEN `_infer_artifact_type` receives a dict with `"train"`, `"val"`, or `"test"` keys THEN the system SHALL CONTINUE TO return `"generic"`.

3.14 WHEN `_infer_artifact_type` receives a numpy `ndarray` or a dict with `"features"` / `"feature_array"` keys THEN the system SHALL CONTINUE TO return `"feature_array"`.

3.15 WHEN `_infer_artifact_type` receives any other value THEN the system SHALL CONTINUE TO return `"generic"`.

3.16 WHEN `executor.py` registers artifacts via `run_manager.register_artifact()` THEN the system SHALL CONTINUE TO pass the correct `artifact_type` string inferred from the node output value.

**Bug 5 — `Pipeline.validate()` always raises `TypeError`**

3.17 WHEN `Pipeline.validate()` returns an empty list THEN the system SHALL CONTINUE TO indicate that the pipeline is valid and ready to run.

3.18 WHEN `Pipeline.validate()` returns a non-empty list THEN the system SHALL CONTINUE TO indicate that the pipeline has validation errors, with each string in the list describing one error.

3.19 WHEN `validate_pipeline` raises a `ValueError` for a structural issue (missing `pipeline` key, empty nodes list, unknown node type, incompatible port types) THEN the system SHALL CONTINUE TO catch it and return the error message as a string in the errors list.

3.20 WHEN `Pipeline.run()` is called on a pipeline that would fail `validate()` THEN the system SHALL CONTINUE TO raise the underlying error during execution (validate is advisory, not a gate on run).
