# Tasks 02 — Core Services

← Back to [tasks.md](tasks.md) | Design: [design-02-core-services.md](design-02-core-services.md)

**Requirements covered:** 4, 5, 6, 7

**Files changed:**
- `app/core/logger.py` — UTC timestamps, `node_end` signature ✅
- `app/core/run_manager.py` — UTC timestamps ✅
- `app/core/ingestion.py` — `IngestionJob` dataclass → Pydantic `BaseModel` ✅
- `app/core/pipeline_cache.py` — `AudioSample.model_validate()` ✅
- `app/core/pipeline.py` — accept optional `run_manager` kwarg ✅
- `tests/test_migration.py` — new/updated unit tests ✅
- `tests/test_properties.py` — new property tests ✅

---

## Task 2.1 — Fix `datetime.utcnow()` in `app/core/logger.py`; update `node_end` signature

**Requirement:** 4.1–4.7

### Sub-tasks

- [x] 2.1.1 Add `timezone` to the `from datetime import ...` import line
- [x] 2.1.2 Remove `import re` (it is only used for the `node_end` regex)
- [x] 2.1.3 Update `_timestamp()` to return `datetime.now(timezone.utc).isoformat()`
- [x] 2.1.4 Replace all inline `datetime.utcnow().isoformat()` calls with `self._timestamp()`
- [x] 2.1.5 Change `node_end` signature: replace `count_str: str = ""` with `output_count: int = 0`
- [x] 2.1.6 In `node_end`, replace the `re.search(r"\d+", count_str)` block with direct use of `output_count`
- [x] 2.1.7 Update the human-readable log line in `node_end` to use `output_count` directly
- [x] 2.1.8 Update callers of `node_end` in `app/core/pipeline.py` to pass `output_count=<int>`
- [x] 2.1.9 Verify `app/cli/main.py`'s `StdoutLogger` is compatible with the new signature

### Acceptance checks
- `app/core/logger.py` contains zero occurrences of `datetime.utcnow` ✅
- `app/core/logger.py` contains zero occurrences of `import re` ✅
- `PipelineLogger()._timestamp()` returns a string ending with `"+00:00"` ✅
- `logger.node_end("clean", 0, 1.5, output_count=3)` emits `{"output_count": 3}` in the structured event ✅
- The human-readable log line for `node_end` contains the node type, duration, and output count ✅

---

## Task 2.2 — Fix `datetime.utcnow()` in `app/core/run_manager.py`

**Requirement:** 5.1–5.5

### Sub-tasks

- [x] 2.2.1 Add `timezone` to the `from datetime import ...` import line in `run_manager.py`
- [x] 2.2.2 Replace `datetime.utcnow().isoformat()` in `RunManager.__init__` with `datetime.now(timezone.utc).isoformat()`
- [x] 2.2.3 Replace `datetime.utcnow().isoformat()` in `RunManager.save_metadata` with `datetime.now(timezone.utc).isoformat()`
- [x] 2.2.4 Verify `mark_failed` does not call `datetime.utcnow()`
- [x] 2.2.5 Confirm no other `datetime.utcnow()` calls remain in `run_manager.py`

### Acceptance checks
- `app/core/run_manager.py` contains zero occurrences of `datetime.utcnow` ✅
- A freshly created `RunManager()` writes a `meta.json` whose `"created_at"` value ends with `"+00:00"` ✅
- `RunManager().save_metadata({})` writes a `meta.json` whose `"created_at"` value ends with `"+00:00"` ✅

---

## Task 2.3 — Migrate `IngestionJob` from `@dataclass` to Pydantic `BaseModel`

**Requirement:** 6.1–6.6

### Sub-tasks

- [x] 2.3.1 Remove `from dataclasses import dataclass, field` import
- [x] 2.3.2 Add `from pydantic import BaseModel, Field` import
- [x] 2.3.3 Remove `@dataclass` decorator from `IngestionJob`
- [x] 2.3.4 Change `class IngestionJob` to `class IngestionJob(BaseModel)`
- [x] 2.3.5 Replace `progress: list[dict] = field(default_factory=list)` with `progress: list[dict] = Field(default_factory=list)`
- [x] 2.3.6 Verify `IngestionService` methods that call `job.progress.append(...)` still work
- [x] 2.3.7 Verify `job.model_dump()` returns a serialisable dict

### Acceptance checks
- `issubclass(IngestionJob, BaseModel)` is `True` ✅
- `IngestionJob(job_id="x", status="running").progress == []` ✅
- `job.progress.append({"step": 1})` works without error ✅
- `job.model_dump()` returns `{"job_id": "x", "status": "running", "progress": [...]}` ✅
- `app/core/ingestion.py` contains zero occurrences of `@dataclass` ✅

---

## Task 2.4 — Update `PipelineCache.load` to use `AudioSample.model_validate()`

**Requirement:** 7.1–7.6

### Sub-tasks

- [x] 2.4.1 Add `import pydantic` to `app/core/pipeline_cache.py`
- [x] 2.4.2 Replace the `AudioSample(path=..., ...)` constructor call with `AudioSample.model_validate({...})`
- [x] 2.4.3 Wrap the `model_validate` call in a `try/except pydantic.ValidationError` block that logs a warning and returns `None`
- [x] 2.4.4 Ensure the outer `except Exception` block is preserved for I/O errors
- [x] 2.4.5 Verify `PipelineCache.save` uses attribute access — no changes needed

### Acceptance checks
- `PipelineCache.load` returns `None` when `AudioSample.model_validate` raises `pydantic.ValidationError` ✅
- `PipelineCache.load` returns `None` when the manifest file is missing ✅
- A valid cache entry is loaded correctly with `metadata` defaulting to `{}` ✅
- `app/core/pipeline_cache.py` contains zero occurrences of `AudioSample(path=` ✅

---

## Task 2.5 — Add `run_manager` parameter to `run_pipeline()`

**Requirement:** 13.1–13.3 (prerequisite for Group 03 Task 3.7)

### Sub-tasks

- [x] 2.5.1 Read `app/core/pipeline.py` to understand the current `run_pipeline` signature
- [x] 2.5.2 Add `run_manager: RunManager | None = None` to the `run_pipeline` function signature
- [x] 2.5.3 Replace the unconditional `run_manager = RunManager()` with `if run_manager is None: run_manager = RunManager()`
- [x] 2.5.4 Confirmed existing callers pass no `run_manager` — default `None` applies

### Acceptance checks
- `run_pipeline(config_path)` creates its own `RunManager` when none is provided ✅
- `run_pipeline(config_path, run_manager=existing_mgr)` uses `existing_mgr` and does not instantiate a second `RunManager` ✅
- No second `RunManager()` call occurs inside `run_pipeline` when one is passed in ✅

---

## Task 2.6 — Write unit tests for Group 02

**Requirement:** 4.1–7.6

### Tests to implement

- [x] 2.6.1 `test_logger_no_utcnow`
- [x] 2.6.2 `test_logger_timestamp_is_utc_aware`
- [x] 2.6.3 `test_logger_node_end_integer_param`
- [x] 2.6.4 `test_logger_node_end_log_line_contains_count`
- [x] 2.6.5 `test_logger_no_import_re`
- [x] 2.6.6 `test_run_manager_created_at_utc`
- [x] 2.6.7 `test_run_manager_save_metadata_utc`
- [x] 2.6.8 `test_ingestion_job_is_pydantic`
- [x] 2.6.9 `test_ingestion_job_default_progress`
- [x] 2.6.10 `test_ingestion_job_progress_append`
- [x] 2.6.11 `test_ingestion_job_model_dump`
- [x] 2.6.12 `test_pipeline_cache_load_validation_error`
- [x] 2.6.13 `test_pipeline_cache_load_missing_metadata_defaults`

### Acceptance checks
- All tests in `tests/test_migration.py` pass for Group 02 items ✅

---

## Task 2.7 — Write property-based tests: Properties 4, 5, 6, 7, 8, 9, 10

**Requirement:** 4.1, 4.4, 4.5, 5.2, 5.3, 5.5, 6.3, 6.6, 7.3, 7.4

### Tests to implement

- [x] 2.7.1 **Property 4 — UTC timestamp format** (`test_property_4_utc_timestamp_format`) — passes with `max_examples=100` ✅
- [x] 2.7.2 **Property 5 — node_end output_count passthrough** (`test_property_5_node_end_output_count`) — passes with `max_examples=100` ✅
- [x] 2.7.3 **Property 6 — node_end log line completeness** (`test_property_6_node_end_log_line`) — passes with `max_examples=100` ✅
- [x] 2.7.4 **Property 7 — RunManager UTC timestamp** (`test_property_7_run_manager_utc`) — passes with `max_examples=20` ✅
- [x] 2.7.5 **Property 8 — IngestionJob default progress** (`test_property_8_ingestion_job_default_progress`) — passes with `max_examples=100` ✅
- [x] 2.7.6 **Property 9 — IngestionJob serialisation round-trip** (`test_property_9_ingestion_job_roundtrip`) — passes with `max_examples=100` ✅
- [x] 2.7.7 **Property 10 — AudioSample metadata round-trip** (`test_property_10_audio_sample_metadata`) — passes with `max_examples=100` ✅

### Acceptance checks
- All seven property tests pass with the specified `max_examples` settings ✅
- Each test is annotated with `# Feature:` and `# Validates:` comments ✅
