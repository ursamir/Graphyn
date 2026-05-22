# Design — Provenance + Artifact System (Phase 4)

## Overview

Phase 4 introduces two new core modules (`ArtifactStore`, `ProvenanceStore`), extends `RunManager`, changes `Pipeline.run()`'s return type to `ArtifactCollection`, adds a REST router, a CLI subcommand, and three MCP tools. All changes are additive — no existing public API is removed or broken.

The central design insight is that **content-addressed storage** (already used by `PipelineCache`) is the right primitive for artifacts too. Two node executions that produce identical outputs should share storage. The `graph_hash` (SHA-256 of `dump_ir(graph)`) is the reproducibility key: if two runs share the same `graph_hash` and the same input hashes, their deterministic node outputs will have identical `content_hash` values.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Interfaces                                   │
│  CLI (audiobuilder artifacts)  │  REST (/api/v1/artifacts/)          │
│  MCP (list_artifacts, ...)     │  SDK (Pipeline.run() → Collection)  │
└────────────────┬───────────────┴──────────────────┬─────────────────┘
                 │                                  │
                 ▼                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│                        RunManager (extended)                        │
│  register_artifact()  compute_graph_hash()  get_provenance_summary()│
└──────────────┬──────────────────────────────────┬──────────────────┘
               │                                  │
               ▼                                  ▼
┌──────────────────────────┐      ┌───────────────────────────────────┐
│      ArtifactStore       │      │         ProvenanceStore            │
│  app/core/artifact_store │      │      app/core/provenance.py        │
│                          │      │                                    │
│  register()              │      │  record()                          │
│  get()                   │      │  get_lineage()                     │
│  list()                  │      │  find_by_run()                     │
│  get_versions()          │      │  find_reproducible()               │
└──────────┬───────────────┘      └──────────────┬─────────────────────┘
           │                                     │
           ▼                                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Workspace (filesystem)                        │
│  workspace/artifacts/{id}/record.json + data/                         │
│  workspace/artifacts/index.json  (content_hash → artifact_id)         │
│  workspace/provenance/{artifact_id}.json                              │
│  workspace/provenance/by_run/{run_id}.json                            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Component Diagram

```
app/
├── core/
│   ├── artifact_store.py      NEW  — ArtifactStore, ArtifactRecord, errors
│   ├── provenance.py          NEW  — ProvenanceStore, ProvenanceRecord
│   ├── run_manager.py         EXTEND — register_artifact(), compute_graph_hash(),
│   │                                   get_provenance_summary(), _graph_hash field
│   └── sdk.py                 EXTEND — ArtifactCollection class,
│                                       Pipeline.run() return type change
├── api/
│   ├── main.py                EXTEND — register artifacts_router
│   └── routers/
│       ├── artifacts.py       NEW  — /api/v1/artifacts/ endpoints
│       └── runs.py            EXTEND — /runs/{id}/artifacts, /runs/{id}/provenance
├── cli/
│   └── main.py                EXTEND — audiobuilder artifacts subcommand
└── mcp/
    ├── tool_registry.py       EXTEND — register 3 new tools
    └── handlers/
        └── provenance.py      NEW  — list_artifacts, get_artifact_lineage, replay_run
```

---

## Data Flow: Node Execution → Artifact Registration → Provenance Recording

```
run_pipeline_ir()
    │
    ├─ Creates RunManager (run_id assigned)
    ├─ Calls save_graph_ir(graph_data)
    │       └─ RunManager computes and stores self._graph_hash
    │
    └─ For each node execution:
           │
           ├─ Node.process() → raw output (list[AudioSample], ModelArtifact, etc.)
           │
           ├─ RunManager.register_artifact(
           │       node_id, node_type, artifact_type, data,
           │       input_artifact_ids=[prior node artifact IDs]
           │   )
           │       │
           │       ├─ ArtifactStore.register() → ArtifactRecord
           │       │       ├─ Compute content_hash
           │       │       ├─ Check index.json for deduplication
           │       │       ├─ Write data/ files (WAV + manifest, or data.json)
           │       │       ├─ Write record.json
           │       │       └─ Update index.json
           │       │
           │       └─ ProvenanceStore.record() → ProvenanceRecord
           │               ├─ Write {artifact_id}.json
           │               └─ Append to by_run/{run_id}.json
           │
           └─ Returns ArtifactRecord (stored in run_manager._artifacts list)

Pipeline.run() wraps result in ArtifactCollection(
    artifacts=run_manager._artifacts,
    run_id=run_manager.run_id,
    _raw=raw_outputs
)
```

---

## Storage Layout (Workspace Extension)

```
workspace/
├── artifacts/                          NEW
│   ├── index.json                      content_hash → artifact_id (flat JSON object)
│   └── {artifact_id}/
│       ├── record.json                 ArtifactRecord (full metadata)
│       └── data/
│           ├── manifest.json           (for audio_samples type)
│           ├── 0.wav, 1.wav, ...       (for audio_samples type)
│           └── data.json               (for model_artifact, feature_array, etc.)
├── provenance/                         NEW
│   ├── {artifact_id}.json              ProvenanceRecord
│   └── by_run/
│       └── {run_id}.json               JSON array of artifact_ids
├── runs/{run_id}/                      EXISTING (unchanged)
│   ├── meta.json
│   ├── logs.json
│   ├── graph.json                      ← Phase 4 reads this for replay
│   ├── resume_state.json
│   └── checkpoints/
├── cache/{sha256}/                     EXISTING (unchanged)
└── datasets/                           EXISTING (unchanged)
```

---

## Key Design Decisions

### 1. Content-Addressed Storage (Why)

`PipelineCache` already uses SHA-256 content addressing for `AudioSample` outputs. `ArtifactStore` extends this pattern to all artifact types. The benefits are:

- **Deduplication**: ML pipelines often re-run the same preprocessing steps. Identical outputs share storage automatically.
- **Reproducibility**: Two runs with the same `graph_hash` and same inputs will produce artifacts with identical `content_hash` values for deterministic nodes. This is verifiable without re-running.
- **Integrity**: The `content_hash` serves as a checksum. If a file is corrupted, the hash will not match.

The `index.json` file maps `content_hash → artifact_id` and is the deduplication gate. It is updated atomically (file lock) to prevent race conditions in parallel execution.

### 2. Separate `artifacts/` and `provenance/` Directories (Why)

Separating storage from lineage metadata follows the single-responsibility principle:

- `artifacts/` answers: "What was produced and where is it stored?"
- `provenance/` answers: "How was it produced and what were its inputs?"

This separation allows the provenance store to be queried independently of artifact data (e.g., for lineage queries that don't need to load the actual data). It also allows future phases to replace the storage backend (e.g., S3, GCS) without changing the provenance schema.

The `by_run/` index in `provenance/` is a secondary index that enables O(1) lookup of all artifacts for a run, avoiding a full scan of `provenance/*.json`.

### 3. `ArtifactCollection` is Dict-Like but Not a Dict Subclass (Why)

`Pipeline.run()` currently returns a raw `dict`. Making `ArtifactCollection` a `dict` subclass would be the simplest backward-compatible change, but it would create confusion: `isinstance(result, dict)` would return `True`, and the dict's internal state would need to be kept in sync with the `artifacts` list.

Instead, `ArtifactCollection` implements the dict protocol (`__getitem__`, `__contains__`, `keys()`, `items()`, `values()`) by delegating to a private `_raw` dict. This is the same pattern used by Django's `QuerySet` and SQLAlchemy's `Row` — rich objects that behave like simpler types for backward compatibility.

The `_raw` dict is the exact output of `run_pipeline_ir()`, so all existing code that accesses `result["node_id"]` continues to work unchanged.

### 4. `graph_hash` as the Reproducibility Key (Why)

The `graph_hash` is SHA-256 of `json.dumps(dump_ir(graph), sort_keys=True)`. This is stable because:

- `dump_ir()` produces a canonical JSON representation (Phase 1 design)
- `sort_keys=True` eliminates key-ordering non-determinism
- The hash covers the full graph structure: nodes, edges, parameters, metadata

Two runs with the same `graph_hash` used the same graph. Combined with the same input `content_hash` values, this is sufficient to guarantee identical outputs for deterministic nodes. This is the foundation for the `find_reproducible()` query and the replay feature.

### 5. Lazy Initialization of ArtifactStore and ProvenanceStore in RunManager (Why)

`RunManager.__init__()` is called for every pipeline run, including all 919 existing tests. Eagerly creating `ArtifactStore` and `ProvenanceStore` instances would create workspace directories in every test, polluting test environments and potentially causing test failures.

Lazy initialization (create on first use of `register_artifact()`) means Phase 4 components are only activated when explicitly used. Existing tests that never call `register_artifact()` are completely unaffected.

### 6. Replay Uses `load_ir_from_file()` + New `RunManager` (Why)

Replay is intentionally simple: load the stored `graph.json`, create a fresh `RunManager`, and execute. This reuses all existing execution infrastructure (parallel, resumable, etc.) without special-casing. The new run gets its own `run_id`, `meta.json`, and artifacts — the original run is never modified.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Lineage Integrity

*For any* set of artifacts registered in the `ArtifactStore` and any `ProvenanceRecord` whose `input_artifact_ids` reference those artifacts, every `artifact_id` in `input_artifact_ids` SHALL be retrievable via `ArtifactStore.get()` without raising `ArtifactNotFoundError`.

**Validates: Requirements req-01 §4, req-02 §3**

### Property 2: Content-Addressed Deduplication

*For any* artifact data D, registering D twice via `ArtifactStore.register()` (with different `run_id` or `node_id`) SHALL produce two `ArtifactRecord` objects with the same `content_hash`, and `workspace/artifacts/index.json` SHALL contain exactly one entry for that `content_hash`.

**Validates: Requirements req-01 §3.3, req-01 §3.4**

### Property 3: Provenance Round-Trip

*For any* artifact ID A for which `ProvenanceStore.record(A, ...)` has been called, `ProvenanceStore.get_lineage(A)` SHALL return a dict whose top-level `artifact_id` equals A, with `run_id`, `node_id`, and `inputs` keys present.

**Validates: Requirements req-02 §4**

### Property 4: Replay Reproducibility

*For any* pipeline graph G containing only deterministic nodes, executing G twice (once directly, once via replay from the stored `graph.json`) SHALL produce `ArtifactRecord` objects with identical `content_hash` values for each corresponding node output.

**Validates: Requirements req-03 §1, req-05 §4**

### Property 5: ArtifactCollection Backward Compatibility

*For any* pipeline execution, the `ArtifactCollection` AC returned by `Pipeline.run()` SHALL satisfy: `AC[k]` equals the raw output for all keys `k` in the raw output dict, `k in AC` iff `k` is in the raw output dict, and `set(AC.keys())` equals the set of keys in the raw output dict.

**Validates: Requirements req-04 §3**

---

## Error Handling

| Component | Error | Type | Behavior |
|---|---|---|---|
| `ArtifactStore` | Unknown artifact ID | `ArtifactNotFoundError(id)` | Raised by `get()` |
| `ArtifactStore` | Serialization failure | `ArtifactSerializationError(type, cause)` | Raised by `register()` |
| `ArtifactStore` | Unsupported artifact type | `ValueError` | Raised by `register()` |
| `ArtifactStore` | Corrupt `index.json` | Warning + fail-open | Log warning, treat as empty |
| `ProvenanceStore` | Missing provenance record | Partial tree with error node | `get_lineage()` never raises |
| `ProvenanceStore` | Cycle in lineage | Cycle-break with error node | `get_lineage()` never raises |
| `RunManager` | `register_artifact()` before `save_graph_ir()` | Empty `graph_hash` | Graceful degradation |
| REST API | Unknown artifact ID | HTTP 404 | `{"detail": "Artifact not found"}` |
| REST API | Invalid artifact ID chars | HTTP 400 | `{"detail": "Invalid artifact_id"}` |
| REST API | Missing `graph.json` for replay | HTTP 422 | `{"detail": "graph.json not found..."}` |
| MCP | Missing required argument | `{"error_type": "missing_argument"}` | Structured error |
| MCP | Unknown run ID | `{"error_type": "unknown_run_id"}` | Structured error |
| MCP | Missing `graph.json` | `{"error_type": "graph_not_found"}` | Structured error |

---

## Testing Strategy

### Unit Tests

Unit tests verify specific examples, edge cases, and error conditions:

- `tests/test_artifact_store.py` — `ArtifactStore` CRUD, deduplication, error cases
- `tests/test_provenance.py` — `ProvenanceStore` record/retrieve, lineage tree, cycle detection
- `tests/test_run_manager_phase4.py` — `register_artifact()`, `compute_graph_hash()`, `get_provenance_summary()`
- `tests/test_artifact_collection.py` — `ArtifactCollection` dict protocol, `Pipeline.run()` return type
- `tests/test_artifacts_api.py` — REST endpoint responses, 404/400 cases
- `tests/test_artifacts_cli.py` — CLI subcommand output, exit codes
- `tests/mcp/test_provenance_tools.py` — MCP handler unit tests

Unit tests focus on:
- Specific examples that demonstrate correct behavior
- Integration points between components
- Edge cases: empty artifact lists, missing files, corrupt index, cycles in lineage
- Error conditions: unknown IDs, invalid types, missing graph.json

### Property-Based Tests

Property tests verify universal correctness properties across all valid inputs:

- `tests/test_provenance_properties.py` — all 5 properties from req-07

Each property test uses `@settings(max_examples=100)` minimum and isolates the workspace via `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`.

**Property-based testing library:** Hypothesis (already installed, used in `tests/mcp/test_properties.py`)

**Tag format:** `# Feature: provenance-artifact-system, Property N: <text>`

### Regression Baseline

All 919 existing tests must pass after each task group. The checkpoint command is:

```bash
venv/bin/pytest tests/ -x --tb=short -q
```

Phase 4 tests are additive — they do not modify any existing test file.
