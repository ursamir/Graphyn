# Tasks — App Pydantic Migration and FastAPI Redesign

← Back to spec root: `.kiro/specs/app-pydantic-migration/`

## Overview

This migration is a clean transformation — no legacy bridges, no backward-compat shims, no 301 redirects. Old patterns are deleted and replaced with the new API throughout. Tasks are split into sub-files matching the design sub-files. The recommended execution order is **01 → 02 → 04 → 03**.

| Group | Sub-file | Scope | Req. |
|-------|----------|-------|------|
| 01 — Plugin, SDK, CLI | [tasks-01-plugin-sdk-cli.md](tasks-01-plugin-sdk-cli.md) | `plugins/noise_node.py`, `app/core/sdk.py`, `app/cli/main.py` | 1, 2, 3, 9 |
| 02 — Core Services | [tasks-02-core-services.md](tasks-02-core-services.md) | `logger.py`, `run_manager.py`, `ingestion.py`, `pipeline_cache.py`, `pipeline.py` | 4, 5, 6, 7 |
| 04 — Validation | [tasks-04-validation.md](tasks-04-validation.md) | `app/core/validation.py` (no shims in `registry.py`) | 14, 15 |
| 03 — API Redesign | [tasks-03-api.md](tasks-03-api.md) | `app/api/main.py` replaced + all new routers | 8, 10, 11, 12, 13 |

---

## Execution Order

```
Group 01 (Plugin/SDK/CLI)
  └─ No dependencies on other groups

Group 02 (Core Services)
  └─ No dependencies on other groups

Group 04 (Validation)
  └─ Depends on: Group 01 (NodeRegistry populated by AutoDiscovery)

Group 03 (API Redesign)
  └─ Depends on: Group 02 (RunManager, PipelineLogger, run_pipeline kwarg)
  └─ Depends on: Group 04 (validate_pipeline uses registry.get_class() directly)
```

---

## What is removed vs. transformed

| Old pattern | New pattern |
|-------------|-------------|
| `register(registry)` in plugins | `AutoDiscovery` via `metadata: ClassVar[NodeMetadata]` |
| `registry[node_type]["class"]` | `registry.get_class(node_type)` |
| `registry[node_type]["schema"]` | `registry.get_config_schema(node_type)` |
| `registry.items()` / `registry.keys()` shims | `registry.list_nodes()` iteration |
| `validate_node_config(config, schema)` | `NodeClass.Config.model_validate(config)` |
| `datetime.utcnow()` | `datetime.now(timezone.utc)` |
| `@dataclass` on `IngestionJob` | `class IngestionJob(BaseModel)` |
| `AudioSample(path=...)` constructor | `AudioSample.model_validate({...})` |
| 500-line `app/api/main.py` monolith | Thin factory + 5 focused routers |
| Legacy root-path endpoints (`/schemas`, `/runs`, etc.) | Deleted — routes live at `/api/v1/` only |
| 301 redirect shims | Not added — callers update to new paths |

---

## Task Summary

### Group 01 — Plugin, SDK, CLI
- [x] 1.1 Rewrite `plugins/noise_node.py` to use the Enhanced Node System
- [x] 1.2 Rename `Node` → `PipelineNode` in `app/core/sdk.py`
- [x] 1.3 Update `PipelineNode._validate` to use `registry.get_class()` + `Config.model_validate()`
- [x] 1.4 Update `Pipeline.from_yaml` to construct `PipelineNode` instances
- [x] 1.5 Verify `app/cli/main.py` requires no changes; add assertion test
- [x] 1.6 Write unit tests for Group 01 changes
- [x] 1.7 Write property-based tests: Properties 1, 2, 3

### Group 02 — Core Services
- [x] 2.1 Fix `datetime.utcnow()` in `app/core/logger.py`; update `node_end` signature
- [x] 2.2 Fix `datetime.utcnow()` in `app/core/run_manager.py`
- [x] 2.3 Migrate `IngestionJob` from `@dataclass` to Pydantic `BaseModel`
- [x] 2.4 Update `PipelineCache.load` to use `AudioSample.model_validate()`
- [x] 2.5 Add `run_manager` parameter to `run_pipeline()` in `app/core/pipeline.py`
- [x] 2.6 Write unit tests for Group 02 changes
- [x] 2.7 Write property-based tests: Properties 4, 5, 6, 7, 8, 9, 10

### Group 04 — Validation
- [x] 4.1 Migrate `app/core/validation.py` to use `registry.get_class()` directly (no shims)
- [x] 4.2 Remove hardcoded audio-specific first/last node rules from `validate_pipeline`
- [x] 4.3 Add `_validate_dag_edges` function to `app/core/validation.py`
- [x] 4.4 Write unit tests for Group 04 changes
- [x] 4.5 Write property-based test: Property 12

### Group 03 — API Redesign
- [x] 3.1 Create `app/api/routers/nodes.py` — Node Catalogue API
- [x] 3.2 Create `app/api/routers/pipelines.py` — Pipeline API (validate, run, run-async, templates)
- [x] 3.3 Create `app/api/routers/runs.py` — Runs API
- [x] 3.4 Create `app/api/routers/data.py` — Data API
- [x] 3.5 Create `app/api/routers/system.py` — System API (health, cleanup, webhooks, registry)
- [x] 3.6 Replace `app/api/main.py` with thin app factory (no legacy endpoints)
- [x] 3.7 Verify single-RunManager guarantee for `/run-async`
- [x] 3.8 Write unit tests for Group 03 changes
- [x] 3.9 Write property-based tests: Properties 11, 13
- [x] 3.10 Write integration tests for API layer

---

## Acceptance Gate

All tasks are complete when:
- [x] `pytest tests/` passes with zero failures — **365 passed, 0 failures**
- [x] Zero occurrences of `registry[` in the codebase (no dict-style registry access anywhere)
- [x] Zero occurrences of `datetime.utcnow()` in migrated files (logger, run_manager, api/)
- [x] Zero occurrences of `register(registry)` in `plugins/`
- [x] Zero occurrences of `@dataclass` on `IngestionJob`
- [x] `app/api/main.py` is under 100 lines of application code — **67 lines**
- [x] No `@app.get` / `@app.post` inline handlers in `app/api/main.py` (all routes in routers)
- [x] Legacy root-path endpoints (`/schemas`, `/runs`, `/validate`, etc.) return HTTP 404
- [x] All property-based tests pass — **21 property tests passing**
