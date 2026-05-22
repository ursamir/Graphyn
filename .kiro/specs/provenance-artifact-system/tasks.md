# Implementation Plan: Provenance + Artifact System (Phase 4)

## Overview

Implement the Phase 4 provenance and artifact system as a set of additive components. No existing file is removed; no existing public API signature changes. The regression baseline is **919 tests** — verified after each group.

## Task Groups and Dependency Graph

```
Group A: ArtifactStore + ArtifactRecord          (no dependencies)
Group B: ProvenanceStore + ProvenanceRecord       (no dependencies, parallel with A)
Group C: RunManager Evolution                     (depends on A, B)
Group D: SDK ArtifactCollection                   (depends on C)
Group E: REST API /api/v1/artifacts/              (depends on A, B)
Group F: CLI audiobuilder artifacts               (depends on A, B)
Group G: MCP Provenance Tools                     (depends on A, B)
Group H: Property-Based Tests                     (depends on A, B, C, D)
```

Groups A and B can be implemented in parallel. Groups E, F, G can be implemented in parallel after A and B. Group D depends on C. Group H depends on A, B, C, D.

---

## Tasks

- [x] A. Implement `ArtifactStore` and `ArtifactRecord` (`app/core/artifact_store.py`)
  - [x] A.1 Define `ArtifactRecord` Pydantic model and error classes
    - Create `app/core/artifact_store.py`
    - Define `ArtifactRecord(BaseModel, frozen=True)` with fields: `artifact_id`, `content_hash`, `artifact_type`, `node_id`, `node_type`, `run_id`, `name`, `metadata`, `created_at`, `schema_version="1.0"`, `data_path`
    - Define `ArtifactNotFoundError(KeyError)` and `ArtifactSerializationError(RuntimeError)`
    - Define `SUPPORTED_ARTIFACT_TYPES: frozenset = frozenset({"audio_samples", "model_artifact", "tflite_artifact", "prediction_result", "feature_array", "generic"})`
    - _Requirements: req-01 §1, req-01 §6_

  - [x] A.2 Implement `ArtifactStore.__init__()` and index management
    - `__init__(self, base_dir: str | None = None)`: reads `GRAPHYN_PROJECT_DIR` env var, sets `self.base = Path(base_dir or workspace) / "artifacts"`, creates dirs, loads/creates `index.json`
    - `_load_index() -> dict`: reads `index.json`, returns `{}` on missing/corrupt (log warning)
    - `_save_index(index: dict)`: writes `index.json` atomically using a threading lock (`self._lock = threading.Lock()`)
    - _Requirements: req-01 §2_

  - [x] A.3 Implement `ArtifactStore.register()`
    - `register(run_id, node_id, node_type, artifact_type, data, metadata=None) -> ArtifactRecord`
    - Validate `artifact_type` against `SUPPORTED_ARTIFACT_TYPES`; raise `ValueError` if unsupported
    - Compute `content_hash` via `_compute_content_hash(artifact_type, data) -> str`
    - Check `index.json` for existing `content_hash`; if found, load and return existing `ArtifactRecord` from `record.json`
    - If new: assign `artifact_id = str(uuid.uuid4())[:8]`, create dirs, serialize data, write `record.json`, update index
    - Serialization dispatch: `"audio_samples"` → WAV files + `manifest.json` (same format as `PipelineCache`); all others → `data.json` via `model_dump(mode="json")` or `json.dumps`
    - `_compute_content_hash(artifact_type, data) -> str`: for `"audio_samples"`, hash the manifest JSON; for others, hash `json.dumps(data, sort_keys=True, default=str)`
    - _Requirements: req-01 §3_

  - [x] A.4 Implement `ArtifactStore.get()`, `list()`, `get_versions()`
    - `get(artifact_id: str) -> ArtifactRecord`: read `{base}/{artifact_id}/record.json`; raise `ArtifactNotFoundError` if missing
    - `list(run_id=None, node_type=None, artifact_type=None) -> list[ArtifactRecord]`: scan all `{base}/*/record.json` files, filter by provided args, sort by `created_at` descending
    - `get_versions(artifact_name: str) -> list[ArtifactRecord]`: call `list()` then filter by `name == artifact_name`
    - _Requirements: req-01 §4_

  - [x]* A.5 Write unit tests for `ArtifactStore`
    - Create `tests/test_artifact_store.py`
    - Test `register()` creates `record.json`, `data/`, and updates `index.json`
    - Test `register()` deduplication: same data → same `content_hash`, no duplicate dir
    - Test `get()` returns correct `ArtifactRecord`
    - Test `get()` raises `ArtifactNotFoundError` for unknown ID
    - Test `list()` with no filters returns all artifacts
    - Test `list()` with `run_id` filter returns only matching artifacts
    - Test `list()` with `artifact_type` filter returns only matching artifacts
    - Test `register()` with unsupported `artifact_type` raises `ValueError`
    - Test corrupt `index.json` is handled gracefully (treated as empty)
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-01 §3, §4, §6_

- [x] B. Implement `ProvenanceStore` and `ProvenanceRecord` (`app/core/provenance.py`)
  - [x] B.1 Define `ProvenanceRecord` Pydantic model
    - Create `app/core/provenance.py`
    - Define `ProvenanceRecord(BaseModel, frozen=True)` with fields: `artifact_id`, `run_id`, `node_id`, `node_type`, `graph_hash`, `input_artifact_ids: list[str]`, `created_at`, `schema_version="1.0"`
    - _Requirements: req-02 §1_

  - [x] B.2 Implement `ProvenanceStore.__init__()` and `record()`
    - `__init__(self, base_dir: str | None = None)`: reads `GRAPHYN_PROJECT_DIR`, sets `self.base = Path(...) / "provenance"`, creates `base/` and `base/by_run/`
    - `record(artifact_id, run_id, node_id, node_type, graph_hash, input_artifact_ids) -> ProvenanceRecord`
    - Write `{base}/{artifact_id}.json` (full `ProvenanceRecord`)
    - Append `artifact_id` to `{base}/by_run/{run_id}.json` (JSON array, create if missing)
    - Use `threading.Lock()` for thread safety on `by_run` updates
    - _Requirements: req-02 §2, §3_

  - [x] B.3 Implement `ProvenanceStore.get_lineage()`
    - `get_lineage(artifact_id: str, _visited: set | None = None) -> dict`
    - Load `{base}/{artifact_id}.json`; if missing, return `{"artifact_id": artifact_id, "inputs": [], "error": "no_provenance_record"}`
    - Track `_visited` set to detect cycles; if `artifact_id` already visited, return `{"artifact_id": artifact_id, "inputs": [], "error": "cycle_detected"}`
    - Recursively call `get_lineage()` for each `input_artifact_id`
    - Return tree dict with `artifact_id`, `run_id`, `node_id`, `node_type`, `graph_hash`, `created_at`, `inputs`
    - _Requirements: req-02 §4_

  - [x] B.4 Implement `ProvenanceStore.find_by_run()` and `find_reproducible()`
    - `find_by_run(run_id: str) -> list[ProvenanceRecord]`: read `{base}/by_run/{run_id}.json`, load each `{artifact_id}.json`; return `[]` if file missing
    - `find_reproducible(graph_hash: str) -> list[ProvenanceRecord]`: scan all `{base}/*.json` (excluding `by_run/`), return records where `graph_hash` matches
    - _Requirements: req-02 §5, §6_

  - [x]* B.5 Write unit tests for `ProvenanceStore`
    - Create `tests/test_provenance.py`
    - Test `record()` writes `{artifact_id}.json` and updates `by_run/{run_id}.json`
    - Test `record()` is idempotent (calling twice with same args overwrites, no duplicate in `by_run`)
    - Test `get_lineage()` returns tree rooted at `artifact_id`
    - Test `get_lineage()` returns error node for missing provenance record
    - Test `get_lineage()` detects and breaks cycles
    - Test `find_by_run()` returns all records for a run
    - Test `find_by_run()` returns `[]` for unknown run
    - Test `find_reproducible()` returns records matching `graph_hash`
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-02 §3, §4, §5, §6_

- [x] C. Checkpoint — verify 919 tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions before proceeding.

- [x] D. Extend `RunManager` with Phase 4 methods (`app/core/run_manager.py`)
  - [x] D.1 Add `compute_graph_hash()` static method and `_graph_hash` field
    - Add `self._graph_hash: str = ""` to `RunManager.__init__()`
    - Add `@staticmethod compute_graph_hash(graph_ir) -> str`: `hashlib.sha256(json.dumps(dump_ir(graph_ir), sort_keys=True).encode()).hexdigest()`
    - Extend `save_graph_ir(graph_data: dict)`: after writing the file, compute `self._graph_hash = hashlib.sha256(json.dumps(graph_data, sort_keys=True).encode()).hexdigest()`
    - Import `hashlib` at top of file (already present via stdlib)
    - _Requirements: req-03 §1_

  - [x] D.2 Add `register_artifact()` method with lazy store initialization
    - Add `self._artifact_store: ArtifactStore | None = None` and `self._provenance_store: ProvenanceStore | None = None` to `__init__()` (not initialized)
    - Add `self._artifacts: list[ArtifactRecord] = []` to `__init__()`
    - Add `_get_artifact_store() -> ArtifactStore`: lazy init `self._artifact_store`
    - Add `_get_provenance_store() -> ProvenanceStore`: lazy init `self._provenance_store`
    - Implement `register_artifact(node_id, node_type, artifact_type, data, metadata=None, input_artifact_ids=None) -> ArtifactRecord`
    - Append returned `ArtifactRecord` to `self._artifacts`
    - _Requirements: req-03 §2_

  - [x] D.3 Add `get_provenance_summary()` method
    - Implement `get_provenance_summary() -> dict`
    - Return `{"run_id": self.run_id, "graph_hash": self._graph_hash, "artifacts": [...], "provenance_records": [...]}`
    - If stores not initialized, return empty lists
    - _Requirements: req-03 §3_

  - [x]* D.4 Write unit tests for RunManager Phase 4 extensions
    - Create `tests/test_run_manager_phase4.py`
    - Test `compute_graph_hash()` returns same hash for same `GraphIR`
    - Test `compute_graph_hash()` returns different hash for different graphs
    - Test `save_graph_ir()` sets `self._graph_hash`
    - Test `register_artifact()` returns `ArtifactRecord` and appends to `self._artifacts`
    - Test `register_artifact()` before `save_graph_ir()` uses empty `graph_hash`
    - Test `get_provenance_summary()` returns correct structure
    - Test `get_provenance_summary()` returns empty lists when no artifacts registered
    - Test all existing `RunManager` methods still work (backward compat smoke test)
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-03 §1, §2, §3, §4_

- [x] E. Checkpoint — verify 919 tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions before proceeding.

- [x] F. Implement `ArtifactCollection` and update `Pipeline.run()` (`app/core/sdk.py`)
  - [x] F.1 Define `ArtifactCollection` class
    - Add `ArtifactCollection` class to `app/core/sdk.py` (or `app/core/artifact_collection.py` imported by `sdk.py`)
    - Fields: `artifacts: list[ArtifactRecord]`, `run_id: str`, `_raw: dict`
    - Methods: `get(node_id_or_key, default=None)`, `get_by_type(artifact_type) -> list[ArtifactRecord]`, `lineage(artifact_id) -> dict`
    - Dict protocol: `__getitem__`, `__contains__`, `keys()`, `items()`, `values()`
    - `__repr__`: `f"ArtifactCollection(run_id={self.run_id!r}, artifacts={len(self.artifacts)})"`
    - _Requirements: req-04 §1_

  - [x] F.2 Update `Pipeline.run()` to return `ArtifactCollection`
    - Modify `Pipeline.run()` to create an internal `RunManager` when none is provided
    - After `run_pipeline_ir()` returns, wrap result in `ArtifactCollection(artifacts=run_manager._artifacts, run_id=run_manager.run_id, _raw=raw_outputs)`
    - Update `Pipeline.run_with_manager()` to return `(ArtifactCollection, RunManager)`
    - Ensure exceptions still propagate unchanged
    - _Requirements: req-04 §2, §3_

  - [x]* F.3 Write unit tests for `ArtifactCollection`
    - Create `tests/test_artifact_collection.py`
    - Test `collection["key"]` returns same value as raw dict
    - Test `"key" in collection` returns same bool as raw dict
    - Test `collection.keys()` returns same keys as raw dict
    - Test `collection.get(node_id)` returns `ArtifactRecord` or `None`
    - Test `collection.get_by_type("audio_samples")` returns filtered list
    - Test `collection.lineage(artifact_id)` delegates to `ProvenanceStore`
    - Test `Pipeline.run()` returns `ArtifactCollection` instance
    - Test `Pipeline.run_with_manager()` returns `(ArtifactCollection, RunManager)` tuple
    - Test `isinstance(collection, dict)` is `False`
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-04 §1, §2, §3_

- [x] G. Checkpoint — verify 919 tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions before proceeding.

- [x] H. Implement REST API `/api/v1/artifacts/` (`app/api/routers/artifacts.py`)
  - [x] H.1 Create `artifacts.py` router with list and get endpoints
    - Create `app/api/routers/artifacts.py` with `router = APIRouter(prefix="/artifacts", tags=["artifacts"])`
    - `GET /artifacts`: query params `run_id`, `node_type`, `artifact_type`; delegate to `ArtifactStore.list()`
    - `GET /artifacts/{artifact_id}`: validate ID chars; delegate to `ArtifactStore.get()`; return 404 on `ArtifactNotFoundError`
    - `GET /artifacts/{artifact_id}/lineage`: delegate to `ProvenanceStore.get_lineage()`
    - `POST /artifacts/{artifact_id}/replay`: load provenance to find `run_id`, load `graph.json`, submit to `ThreadPoolExecutor`, return `{"run_id": new_run_id, "status": "started"}`
    - _Requirements: req-05 §1_

  - [x] H.2 Register `artifacts_router` in `app/api/main.py`
    - Import `artifacts_router` from `app.api.routers.artifacts`
    - Add `app.include_router(artifacts_router, prefix="/api/v1", dependencies=_deps)`
    - _Requirements: req-05 §1.2_

  - [x] H.3 Extend `app/api/routers/runs.py` with artifact endpoints
    - Add `GET /runs/{run_id}/artifacts`: delegate to `ArtifactStore.list(run_id=run_id)`
    - Add `GET /runs/{run_id}/provenance`: create `RunManager`-like summary from `ProvenanceStore.find_by_run(run_id)` and `ArtifactStore.list(run_id=run_id)`
    - _Requirements: req-05 §1.4_

  - [x]* H.4 Write unit tests for artifacts REST API
    - Create `tests/test_artifacts_api.py`
    - Test `GET /api/v1/artifacts` returns list (empty when no artifacts)
    - Test `GET /api/v1/artifacts?run_id=X` returns only artifacts for that run
    - Test `GET /api/v1/artifacts/{id}` returns `ArtifactRecord` dict
    - Test `GET /api/v1/artifacts/{id}` returns 404 for unknown ID
    - Test `GET /api/v1/artifacts/{id}` returns 400 for invalid ID chars
    - Test `GET /api/v1/artifacts/{id}/lineage` returns lineage tree
    - Test `POST /api/v1/artifacts/{id}/replay` returns `{"run_id": ..., "status": "started"}`
    - Test `POST /api/v1/artifacts/{id}/replay` returns 404 for unknown artifact
    - Test `GET /api/v1/runs/{run_id}/artifacts` returns list
    - Test `GET /api/v1/runs/{run_id}/provenance` returns summary dict
    - Use `TestClient` from `fastapi.testclient` and `tmp_path` fixture
    - _Requirements: req-05 §1, §2_

- [x] I. Implement CLI `audiobuilder artifacts` subcommand (`app/cli/main.py`)
  - [x] I.1 Implement `cmd_artifacts_list`, `cmd_artifacts_get`, `cmd_artifacts_lineage`, `cmd_artifacts_replay`
    - `cmd_artifacts_list(args)`: call `ArtifactStore.list(run_id=args.run, artifact_type=args.type)`, print table with columns `ARTIFACT ID`, `TYPE`, `NODE TYPE`, `RUN ID`, `CREATED AT`
    - `cmd_artifacts_get(args)`: call `ArtifactStore.get(args.artifact_id)`, print `json.dumps(record.model_dump(mode="json"), indent=2)`; exit 1 on `ArtifactNotFoundError`
    - `cmd_artifacts_lineage(args)`: call `ProvenanceStore.get_lineage(args.artifact_id)`, print `json.dumps(tree, indent=2)`
    - `cmd_artifacts_replay(args)`: load `workspace/runs/{args.run_id}/graph.json` via `load_ir_from_file()`; create `RunManager()`; call `run_pipeline_ir()`; print new `run_id`; exit 1 if `graph.json` missing
    - _Requirements: req-05 §3_

  - [x] I.2 Register `artifacts` subparser in `build_parser()`
    - Add `artifacts_parser = subparsers.add_parser("artifacts", ...)` with sub-subparsers: `list`, `get`, `lineage`, `replay`
    - `list`: `--run` (optional), `--type` (optional)
    - `get`: positional `artifact_id`
    - `lineage`: positional `artifact_id`
    - `replay`: positional `run_id`
    - _Requirements: req-05 §3_

  - [x]* I.3 Write unit tests for CLI artifacts subcommand
    - Create `tests/test_artifacts_cli.py`
    - Test `build_parser()` includes `artifacts` subcommand with all 4 sub-subcommands
    - Test `artifacts list` prints table header and exits 0
    - Test `artifacts list` prints "No artifacts found." when empty
    - Test `artifacts get <id>` prints JSON and exits 0 for known artifact
    - Test `artifacts get <id>` exits 1 for unknown artifact
    - Test `artifacts lineage <id>` prints JSON tree
    - Test `artifacts replay <run_id>` exits 1 when `graph.json` missing
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-05 §3_

- [x] J. Implement MCP provenance tools (`app/mcp/handlers/provenance.py`)
  - [x] J.1 Implement `list_artifacts_handler`, `get_artifact_lineage_handler`, `replay_run_handler`
    - Create `app/mcp/handlers/provenance.py`
    - Define `LIST_ARTIFACTS_DESCRIPTION`, `LIST_ARTIFACTS_SCHEMA`, `list_artifacts_handler(arguments) -> dict`
    - Define `GET_ARTIFACT_LINEAGE_DESCRIPTION`, `GET_ARTIFACT_LINEAGE_SCHEMA`, `get_artifact_lineage_handler(arguments) -> dict`
    - Define `REPLAY_RUN_DESCRIPTION`, `REPLAY_RUN_SCHEMA`, `replay_run_handler(arguments) -> dict`
    - All handlers: wrap in try/except, return structured error dicts on failure, never raise
    - `replay_run_handler`: use `ThreadPoolExecutor` (same pattern as `execute_pipeline_handler`)
    - _Requirements: req-06 §1, §2, §3_

  - [x] J.2 Register new tools in `app/mcp/tool_registry.py`
    - Import from `app.mcp.handlers.provenance`
    - Add `register("list_artifacts", ...)`, `register("get_artifact_lineage", ...)`, `register("replay_run", ...)`
    - Total tool count becomes 14
    - _Requirements: req-06 §4_

  - [x]* J.3 Write unit tests for MCP provenance tools
    - Create `tests/mcp/test_provenance_tools.py`
    - Test `list_artifacts_handler({})` returns `{"artifacts": [], "count": 0}` when no artifacts
    - Test `list_artifacts_handler({"run_id": "x"})` returns filtered list
    - Test `get_artifact_lineage_handler({})` returns `error_type: "missing_argument"`
    - Test `get_artifact_lineage_handler({"artifact_id": "x"})` returns lineage tree
    - Test `replay_run_handler({})` returns `error_type: "missing_argument"`
    - Test `replay_run_handler({"run_id": "nonexistent"})` returns `error_type: "unknown_run_id"`
    - Test `replay_run_handler({"run_id": "x"})` where `graph.json` missing returns `error_type: "graph_not_found"`
    - Test `replay_run_handler({"run_id": "x"})` with valid `graph.json` returns `{"run_id": ..., "status": "started"}`
    - Test all handlers never raise unhandled exceptions (exception safety)
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-06 §1, §2, §3_

- [x] K. Checkpoint — verify 919 tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions before proceeding.

- [x] L. Write property-based tests (`tests/test_provenance_properties.py`)
  - [x]* L.1 Write Property 1: Lineage Integrity
    - **Property 1: Lineage integrity**
    - `@given(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5))`
    - Register N input artifacts, register one output artifact with `input_artifact_ids` pointing to them
    - Assert every `artifact_id` in `input_artifact_ids` is retrievable via `ArtifactStore.get()`
    - `@settings(max_examples=100)`
    - `# Feature: provenance-artifact-system, Property 1: Lineage integrity`
    - **Validates: Requirements req-01 §4, req-02 §3**

  - [x]* L.2 Write Property 2: Content-Addressed Deduplication
    - **Property 2: Content-addressed deduplication**
    - `@given(st.dictionaries(st.text(min_size=1), st.text()))`
    - Register same `"generic"` data twice with different `run_id`
    - Assert `record1.content_hash == record2.content_hash`
    - Assert `index.json` has exactly one entry for that hash
    - `@settings(max_examples=100)`
    - `# Feature: provenance-artifact-system, Property 2: Content-addressed deduplication`
    - **Validates: Requirements req-01 §3.3, req-01 §3.4**

  - [x]* L.3 Write Property 3: Provenance Round-Trip
    - **Property 3: Provenance round-trip**
    - `@given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"))))`
    - Call `ProvenanceStore.record(artifact_id, ...)` then `get_lineage(artifact_id)`
    - Assert `result["artifact_id"] == artifact_id` and `"inputs"` key present
    - `@settings(max_examples=100)`
    - `# Feature: provenance-artifact-system, Property 3: Provenance round-trip`
    - **Validates: Requirements req-02 §4**

  - [x]* L.4 Write Property 4: Replay Reproducibility
    - **Property 4: Replay reproducibility**
    - Use a fixed minimal deterministic pipeline (e.g., single `InputNode` with fixed config)
    - Execute twice: once directly, once via `load_ir_from_file(graph.json)`
    - Assert artifacts with same `node_type` have same `content_hash`
    - `@settings(max_examples=50)` (pipeline execution is expensive)
    - `# Feature: provenance-artifact-system, Property 4: Replay reproducibility`
    - **Validates: Requirements req-03 §1, req-05 §4**

  - [x]* L.5 Write Property 5: ArtifactCollection Backward Compatibility
    - **Property 5: ArtifactCollection backward compatibility**
    - `@given(st.integers(min_value=1, max_value=3))` — number of nodes
    - Execute pipeline via `run_pipeline_ir()` to get raw dict; execute same pipeline via `Pipeline.run()` to get `ArtifactCollection`
    - Assert `set(collection.keys()) == set(raw.keys())`
    - Assert `k in collection` iff `k in raw` for all keys
    - Assert `collection[k]` equals `raw[k]` for all keys
    - `@settings(max_examples=50)`
    - `# Feature: provenance-artifact-system, Property 5: ArtifactCollection backward compatibility`
    - **Validates: Requirements req-04 §3**

- [x] M. Final Checkpoint — all tests pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm all 919 + new Phase 4 tests pass.
  - Verify `audiobuilder artifacts list` runs without error.
  - Verify `GET /api/v1/artifacts` returns 200.
  - Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- All new files use `from __future__ import annotations` and Python 3.10+ type hints
- All workspace access uses `os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")` — never hardcoded paths
- `ArtifactStore` and `ProvenanceStore` are instantiated fresh per test using `tmp_path` + `monkeypatch`
- The `_raw` dict in `ArtifactCollection` is the exact return value of `run_pipeline_ir()` — no copying
- MCP handlers follow the 30-line limit from `mcp-server.md` — delegate to store methods immediately
- Replay uses `ThreadPoolExecutor` (non-blocking) in REST/MCP, synchronous in CLI

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["A.1", "A.2", "B.1", "B.2"] },
    { "id": 1, "tasks": ["A.3", "B.3"] },
    { "id": 2, "tasks": ["A.4", "B.4"] },
    { "id": 3, "tasks": ["A.5", "B.5"] },
    { "id": 4, "tasks": ["D.1"] },
    { "id": 5, "tasks": ["D.2", "D.3"] },
    { "id": 6, "tasks": ["D.4"] },
    { "id": 7, "tasks": ["F.1"] },
    { "id": 8, "tasks": ["F.2"] },
    { "id": 9, "tasks": ["F.3", "H.1", "I.1", "J.1"] },
    { "id": 10, "tasks": ["H.2", "H.3", "I.2", "J.2"] },
    { "id": 11, "tasks": ["H.4", "I.3", "J.3"] },
    { "id": 12, "tasks": ["L.1", "L.2", "L.3", "L.4", "L.5"] }
  ]
}
```
