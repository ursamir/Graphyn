# G2 Pipeline & IR — Deep Review (Second Pass)

**Reviewer:** Kiro AI  
**Date:** 2025-07-14  
**Files reviewed:** 11  
**Scope:** `app/core/pipeline.py`, `validation.py`, `pipeline_cache.py`, `executor.py`, `conditions.py`, `events.py`, `ir/models.py`, `ir/loader.py`, `ir/yaml_shim.py`, `ir/migrate.py`, `ir/__init__.py`

---

## PHASE 1 — EXPLORATION PLAN


### File 1 — `app/core/pipeline.py`
**Purpose:** Central DAG executor — builds `PipelineGraph`, drives `NodeExecutor` lifecycle, implements sequential/parallel/event-driven execution modes, resume, partial execution, and YAML backward-compat shim.  
**Review questions:**
- Does `run_pipeline_ir_async` correctly handle the case where `parallel=True` AND `event_driven=True` simultaneously?
- Is the `asyncio.run()` call in `run_pipeline_ir` safe when called from within an already-running event loop?
- Does the pass-through logic for excluded nodes correctly propagate data to downstream active nodes?
- Is `_write_checkpoint` path construction safe against path traversal via `node_id`?
- Does the condition evaluation double-call in the skip-node check create a TOCTOU issue?
- Are all `NodeExecutor` instances torn down on every exit path (cancel, error, normal)?

### File 2 — `app/core/validation.py`
**Purpose:** Validates raw pipeline config dicts (YAML-sourced) against the node registry, checking node types, configs, and edge port compatibility.  
**Review questions:**
- Does `validate_pipeline` correctly handle the DAG edge format vs. linear format?
- Is the `validate_node_config` tombstone function safe (does it raise or silently pass)?
- Are there any silent `except Exception: pass` blocks that swallow real errors?
- Does `_validate_dag_edges` handle the case where `from_id` or `to_id` is `None`?

### File 3 — `app/core/pipeline_cache.py`
**Purpose:** Disk-backed node output cache with two storage formats (WAV+manifest legacy, outputs.json new) and a stable input hashing strategy.  
**Review questions (P-14):** Are both formats present? Is there a migration path from legacy to new? Can `has()` return True while `load()` returns None (TOCTOU)?
- Is `input_hash` stable across process restarts for all supported types?
- Does `save()` correctly handle the case where `outputs` contains both AudioSample and non-AudioSample ports?
- Is `clear()` safe against concurrent access?

### File 4 — `app/core/executor.py`
**Purpose:** Parallel wave executor — runs all nodes in a wave concurrently using `asyncio.gather` + `ThreadPoolExecutor`, with cache, checkpoint, and artifact registration.  
**Review questions:**
- Does `run_wave` correctly propagate the first exception while still awaiting all tasks?
- Is the `ThreadPoolExecutor` lifecycle correct — is it shut down even when tasks raise?
- Does `_run_node` access `node_outputs` (a shared dict) safely from multiple concurrent tasks?
- Is the `cacheable` fallback-to-True on exception correct behavior?

### File 5 — `app/core/conditions.py`
**Purpose:** Restricted `eval()` for conditional edge expressions — whitelist-based AST validator with 500-char limit.  
**Review questions (Security):** Is the 500-char limit present and enforced before `ast.parse`? Is `_ALLOWED_NODE_TYPES` complete and bypass-proof? Can `ast.Attribute` sneak through?
- Is `evaluate_condition` deterministic for the same `(expression, output)` pair?
- Are there any AST node types that could be constructed from allowed types (e.g., `ast.JoinedStr` via f-strings)?

### File 6 — `app/core/events.py`
**Purpose:** Event source abstractions (`FileWatcherSource`, `TimerSource`, `QueueSource`) for event-driven pipeline execution.  
**Review questions:**
- Does `FileWatcherSource.close()` correctly stop the `watchfiles` async generator?
- Does `TimerSource` have a drift problem (wall-clock vs. sleep-based timing)?
- Is `QueueSource` safe against a `close()` call before `watch()` is called?
- Does `create_event_source` validate `source_config` keys correctly for all source types?

### File 7 — `app/core/ir/models.py`
**Purpose:** Pydantic models for the Graph IR — `GraphIR`, `IRNode`, `IREdge`, `IRMetadata`, `IRCapabilityMetadata`, `IRParameter`.  
**Review questions (P-23):** Is `IRNode.config` mutable despite `frozen=True`? Can it be mutated in place?
- Does `IRCapabilityMetadata.dependency_requirements` use a mutable default (`[]`)?
- Does `IRMetadata._name_non_empty` strip and store the normalised value correctly?
- Does `GraphIR._validate_graph` catch all duplicate-ID and dangling-edge cases?

### File 8 — `app/core/ir/loader.py`
**Purpose:** IR serialization/deserialization — `load_ir`, `dump_ir`, `load_ir_from_file`, `dump_ir_to_file`, version validation.  
**Review questions:**
- Does `_check_version` correctly handle malformed version strings?
- Does `load_ir` validate version before or after Pydantic validation?
- Is `dump_ir_to_file` atomic (no partial writes on failure)?
- Is `IRValidationError` actually raised anywhere, or is it dead code?

### File 9 — `app/core/ir/yaml_shim.py`
**Purpose:** Converts legacy YAML pipeline configs to `GraphIR` — supports both linear auto-chain and explicit-edge formats.  
**Review questions:**
- Does `yaml_config_to_ir` handle an empty `nodes` list without crashing?
- Does the explicit-edge parser handle the dict format (`src_id`/`dst_id`) correctly?
- Is `load_yaml_with_deprecation` safe against path traversal in `path`?
- Does the `stacklevel=2` in `warnings.warn` point to the correct caller frame?

### File 10 — `app/core/ir/migrate.py`
**Purpose:** CLI migration utility — converts YAML pipeline config files to IR JSON files on disk.  
**Review questions:**
- Does `migrate_yaml_to_ir_file` handle the case where `output_path` already exists (overwrite)?
- Is the output path derivation safe for files without a `.yaml`/`.yml` extension?
- Are parent directories of `output_path` created if they don't exist?

### File 11 — `app/core/ir/__init__.py`
**Purpose:** Public API surface for the `app.core.ir` package — re-exports all public symbols.  
**Review questions:**
- Is `__all__` complete and consistent with the actual exports?
- Are there any missing exports (e.g., `yaml_shim`, `migrate`)?
- Does the import order create any circular dependency risk?

---

## PHASE 2 — PER-FILE FINDINGS


---

## File 1 — `app/core/pipeline.py`

### D1 — Code Quality & Correctness


### [G2-01] `asyncio.run()` called inside an already-running event loop
**File:** `app/core/pipeline.py`  
**Severity:** 🔴 Critical  
**Dimension:** D1  
**Description:** `run_pipeline_ir()` calls `asyncio.run(run_pipeline_ir_async(...))`. `asyncio.run()` creates a new event loop and raises `RuntimeError: This event loop is already running` when called from within an async context (e.g., FastAPI route handler, Jupyter notebook, or any async test). This is a crash in the most common production deployment path (REST API).  
**Evidence:** `pipeline.py` line ~1190: `return asyncio.run(run_pipeline_ir_async(...))`. The REST API routers call `run_pipeline_ir` from async route handlers.  
**Proposed Fix:** Use `asyncio.get_event_loop().run_until_complete(...)` with a running-loop guard, or expose `run_pipeline_ir_async` as the primary API and make `run_pipeline_ir` a thin sync wrapper only for CLI/test use:
```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = None
if loop and loop.is_running():
    # Caller is async — they should await run_pipeline_ir_async directly
    raise RuntimeError(
        "run_pipeline_ir() cannot be called from an async context. "
        "Use 'await run_pipeline_ir_async(...)' instead."
    )
return asyncio.run(run_pipeline_ir_async(...))
```


### [G2-02] `parallel=True` + `event_driven=True` silently executes both branches
**File:** `app/core/pipeline.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** When both `parallel=True` and `event_driven=True` are passed, the function executes the parallel wave loop first (consuming all nodes), then falls through into the event-driven block. The event-driven block re-executes nodes that were already run, producing duplicate artifact registrations and double node teardown. There is no guard against this combination.  
**Evidence:** The `if parallel:` block and the `if event_driven:` block are sequential — there is no `elif` or mutual-exclusion check. Both blocks run when both flags are `True`.  
**Proposed Fix:** Add a guard at the top of `run_pipeline_ir_async`:
```python
if parallel and event_driven:
    raise ValueError("parallel and event_driven are mutually exclusive execution modes.")
```

### [G2-03] Condition expression evaluated twice for skip-node check (TOCTOU)
**File:** `app/core/pipeline.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1  
**Description:** In the sequential execution loop, a condition expression is first evaluated during input assembly (to decide whether to set `inputs[dst_port] = None`) and then evaluated a second time in the skip-node check block. If the `output` dict of the upstream node is mutated between the two evaluations (e.g., by a concurrent event-driven task), the two evaluations can disagree, causing a node to receive `None` on a required port but not be skipped, leading to a downstream crash.  
**Evidence:** Lines ~960–990 (first eval in input assembly) and lines ~995–1020 (second eval in skip-node check). Both call `evaluate_condition(condition, src_outputs)` independently.  
**Proposed Fix:** Cache the condition result from the first evaluation pass and reuse it in the skip-node check:
```python
condition_results: dict[tuple, bool] = {}
# In input assembly:
result = evaluate_condition(condition, src_outputs)
condition_results[(src_id, src_port, node_id, dst_port)] = result
# In skip-node check:
if not condition_results.get((src_id, src_port, node_id, dst_port), True):
    false_condition_ports.add(dst_port)
```


### [G2-04] `_write_checkpoint` path traversal via unsanitised `node_id`
**File:** `app/core/pipeline.py`  
**Severity:** 🟠 High  
**Dimension:** D6 (Security)  
**Description:** `_write_checkpoint` constructs the checkpoint directory as `os.path.join(run_base_path, "checkpoints", f"node_{node_id}")`. If `node_id` contains `../` sequences (e.g., `../../etc/cron.d`), the resulting path escapes the run directory. While `node_id` is validated by `IRNode._id_valid` (alphanumeric + `_-` only), `NodeSpec.node_id` in `PipelineConfig` has no such validator — it is a plain `str` field on a `@dataclass`. A caller constructing `PipelineConfig` directly (bypassing IR) can inject an arbitrary path.  
**Evidence:** `NodeSpec` dataclass has no `node_id` validation. `_write_checkpoint` uses `os.path.join` without resolving the final path against `run_base_path`.  
**Proposed Fix:** Resolve and assert the checkpoint path stays within the run directory:
```python
checkpoint_dir = os.path.realpath(
    os.path.join(run_base_path, "checkpoints", f"node_{node_id}")
)
if not checkpoint_dir.startswith(os.path.realpath(run_base_path)):
    raise ValueError(f"node_id '{node_id}' would escape the run directory")
```

### [G2-05] `NodeExecutor` teardown skipped on cancel path in sequential mode
**File:** `app/core/pipeline.py`  
**Severity:** 🟠 High  
**Dimension:** D3  
**Description:** When `run.is_cancelled` is detected in the sequential loop, the code calls `exec_.teardown()` for all executors and returns. However, if the cancel check fires *before* the first node runs (i.e., `node_stats` is empty), `last_completed` is `None` and the function returns `{}`. This is correct. But if the cancel fires mid-pipeline, executors for nodes that have already been set up but not yet reached in the loop are torn down correctly. The issue is that in the **parallel** path, there is no cancel check at all — the parallel executor runs entire waves to completion before checking for cancellation, potentially running many nodes after a cancel signal.  
**Evidence:** The `run.wait_if_paused()` / `run.is_cancelled` check exists only in the sequential loop. The parallel `for wave_idx, wave in enumerate(...)` loop has no cancel check between waves.  
**Proposed Fix:** Add a cancel check between waves in the parallel path:
```python
for wave_idx, wave in enumerate(graph_obj.execution_waves):
    if run.is_cancelled:
        break
    logger.wave_start(wave_idx, wave)
    ...
```


### [G2-06] Event-driven mode does not check conditions on edges
**File:** `app/core/pipeline.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** In the event-driven execution block (`_handle_source`), inputs are assembled from `node_outputs` without consulting `edge_conditions`. Conditional edges are silently ignored — all edges transmit data regardless of their condition expression. This is a correctness regression: a pipeline that works correctly in sequential mode will behave differently in event-driven mode.  
**Evidence:** The `_handle_source` inner function assembles `exec_inputs` with a simple `node_outputs[src_id].get(src_port)` lookup, with no reference to `edge_conditions`.  
**Proposed Fix:** Apply the same condition-check logic used in the sequential loop inside `_handle_source` before assembling each input port value.

### D2 — Architecture & Design

### [G2-07] `run_pipeline_ir_async` is 300+ lines — violates Single Responsibility
**File:** `app/core/pipeline.py`  
**Severity:** 🟡 Medium  
**Dimension:** D2  
**Description:** `run_pipeline_ir_async` handles setup, resume state loading, partial execution, sequential execution, parallel execution, event-driven execution, teardown, artifact registration, and metadata saving — all in one function. This makes it extremely difficult to test individual execution modes in isolation and violates SRP. The event-driven block in particular is a 100-line nested function inside an already-large function.  
**Evidence:** Function spans from approximately line 430 to line 1170 (~740 lines).  
**Proposed Fix:** Extract `_run_sequential`, `_run_parallel`, and `_run_event_driven` as private async functions, each accepting a shared execution context dataclass. `run_pipeline_ir_async` becomes an orchestrator of ~50 lines.

### D3 — Error Handling

### [G2-08] `_load_checkpoint_outputs` silently discards partial checkpoint data
**File:** `app/core/pipeline.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** If any single `AudioSample` in a checkpoint manifest fails `model_validate`, the entire checkpoint is discarded and the node re-executes. For large checkpoints (thousands of samples), a single corrupt entry causes full re-execution. The warning message says "will re-execute" but does not identify which entry failed.  
**Evidence:** `_load_checkpoint_outputs` returns `None` on any `pydantic.ValidationError`, discarding all successfully loaded samples.  
**Proposed Fix:** Log the failing entry index and consider returning partial results with a warning, or at minimum include the entry index in the warning message.

### D4 — Performance

### [G2-09] `_resolve_capability` called in a linear scan inside the sequential loop
**File:** `app/core/pipeline.py`  
**Severity:** 🟡 Medium  
**Dimension:** D4  
**Description:** In the sequential execution loop, `_resolve_capability` is called per-node with `next((n for n in graph.nodes if n.id == node_id), None)` — an O(N) scan of all IR nodes for every node executed. For a 100-node pipeline this is O(N²) total. The parallel executor correctly pre-builds `ir_nodes_map` but the sequential path does not.  
**Evidence:** Sequential loop, cache-save block: `ir_node = next((n for n in graph.nodes if n.id == node_id), None)`.  
**Proposed Fix:** Pre-build `ir_nodes_map` before the sequential loop (same as the parallel path already does).

### D5 — Test Coverage Gaps

No issues found beyond what is noted in the correctness property skeletons section.

### D6 — Security

See G2-04 above.

### D7 — Documentation

### [G2-10] `run_pipeline_ir_async` docstring does not document `event_loop` parameter behaviour
**File:** `app/core/pipeline.py`  
**Severity:** 🔵 Low  
**Dimension:** D7  
**Description:** The `event_loop` parameter is documented as "reserved for future use" but the function body never references it. This is misleading — callers may pass a loop expecting it to be used.  
**Evidence:** Parameter `event_loop: Any = None` in signature; body never uses it.  
**Proposed Fix:** Either remove the parameter or add a `# noqa` comment and a clear docstring note: "This parameter is accepted but ignored. It exists for future API compatibility."

### D8 — Convention Adherence

### [G2-11] Late imports inside hot execution path
**File:** `app/core/pipeline.py`  
**Severity:** 🔵 Low  
**Dimension:** D8  
**Description:** Several imports (`from app.core.conditions import evaluate_condition`, `from app.core.run_manager import register_active_run`) are placed inside the execution loop body rather than at module or function top level. While this avoids circular imports, it adds import machinery overhead on every node iteration.  
**Evidence:** Multiple `from app.core.X import Y` statements inside the `for idx, node_id in enumerate(...)` loop.  
**Proposed Fix:** Move these imports to the top of `run_pipeline_ir_async` (after the function signature), where they are resolved once per call rather than once per node.

---

## File 2 — `app/core/validation.py`

### D1 — Code Quality & Correctness

### [G2-12] `_validate_dag_edges` does not guard against `None` node IDs
**File:** `app/core/validation.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** When an edge dict has `"from": []` (empty list), `from_id` is set to `None`. The subsequent `if from_id not in id_to_type` check will pass (since `None` is not a key in `id_to_type`), raising `ValueError: Edge references unknown source node id 'None'`. This is a confusing error message. More critically, if `from_raw` is a non-list, non-string value (e.g., an integer from a malformed YAML), `from_id` is set to that integer, which also produces a confusing error.  
**Evidence:** Lines ~30–45 in `_validate_dag_edges`: `from_id = from_raw[0] if len(from_raw) > 0 else None`.  
**Proposed Fix:** Add an explicit guard:
```python
if from_id is None:
    raise ValueError("Edge 'from' field is missing or empty")
if to_id is None:
    raise ValueError("Edge 'to' field is missing or empty")
```

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

### [G2-13] `_validate_connections` swallows all non-`ValueError` exceptions silently
**File:** `app/core/validation.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** The outer `try/except Exception: pass` in `_validate_connections` catches and discards any exception that is not a `ValueError` — including `ImportError`, `AttributeError`, and `TypeError`. If `CompatibilityChecker.are_compatible` raises an unexpected exception (e.g., due to a bug in a new node type), the validation silently passes, allowing an incompatible pipeline to proceed to execution.  
**Evidence:** `_validate_connections`, final `except Exception: pass` block.  
**Proposed Fix:** Log the swallowed exception at WARNING level so it is visible in production logs, even if validation continues:
```python
except Exception as exc:
    log.warning("_validate_connections: unexpected error (skipping): %s", exc)
```

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

### [G2-14] No test for `validate_pipeline` with DAG format edges
**File:** `app/core/validation.py`  
**Severity:** 🟡 Medium  
**Dimension:** D5  
**Description:** `validate_pipeline` branches on `edges` presence to call either `_validate_dag_edges` or `_validate_connections`. The DAG path (`_validate_dag_edges`) handles both list-format and dict-format edges, plus the `None`-ID edge case. These paths appear untested based on the review of the test suite structure.  
**Proposed Fix:** Add parametrised tests covering: (a) valid DAG edges, (b) edge referencing unknown node ID, (c) incompatible port types in DAG format, (d) empty `from` list.

### D6 — Security

No issues found.

### D7 — Documentation

### [G2-15] `validate_node_config` tombstone lacks migration example
**File:** `app/core/validation.py`  
**Severity:** 🔵 Low  
**Dimension:** D7  
**Description:** The `validate_node_config` docstring says "migrate callers to the Pydantic-based API" but does not show a concrete before/after example. Callers hitting the `NotImplementedError` at runtime have no inline guidance.  
**Proposed Fix:** Add a one-line example to the docstring:
```
Example migration:
    # Before: validate_node_config("clean", cfg, schema)
    # After:  registry.get_class("clean").Config.model_validate(cfg)
```

### D8 — Convention Adherence

No issues found.


---

## File 3 — `app/core/pipeline_cache.py`

### D1 — Code Quality & Correctness

### [G2-16] `has()` / `load()` TOCTOU race — cache entry can disappear between check and read
**File:** `app/core/pipeline_cache.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** `has(key)` checks `self._cache_dir(key).is_dir()`. `load(key)` then opens files inside that directory. Between the two calls, another process (or `clear()`) can delete the directory, causing `load()` to return `None` even though `has()` returned `True`. The caller in `pipeline.py` treats a `None` return from `load()` as a cache miss and re-executes the node — so this is not a crash, but it is a silent correctness issue that causes unexpected re-execution.  
**Evidence:** `pipeline.py` sequential loop: `if cache.has(cache_key): cached_result = cache.load(cache_key); if cached_result is not None: ... cache_hit = True`.  
**Proposed Fix:** Combine `has` and `load` into a single `get(key) -> Optional[Any]` method that opens the directory atomically, or document that `load()` returning `None` is a valid "miss" signal and callers must handle it.

### [G2-17] `save()` writes only the first AudioSample port, silently drops others
**File:** `app/core/pipeline_cache.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** `save()` iterates over `outputs.items()` to find the first port with an AudioSample list, then writes only that port to `manifest.json` and returns immediately. If a node produces AudioSamples on multiple output ports (e.g., `output` and `augmented`), only the first port found is cached. On load, `{"output": samples}` is returned regardless of the original port name, potentially mapping data to the wrong port.  
**Evidence:** `save()` method: `for port_name, value in outputs.items(): if _is_audio_sample_list(value): audio_port = port_name; audio_samples = value; break` — then writes only `audio_samples` and returns.  
**Proposed Fix:** Write all AudioSample ports to separate subdirectories or encode the port name in the manifest. At minimum, use `audio_port` (not hardcoded `"output"`) as the key when returning from `load()`.

### D2 — Architecture & Design

No issues found beyond the open item P-14 verdict below.

### D3 — Error Handling

### [G2-18] `clear()` is not atomic — partial deletion leaves cache in inconsistent state
**File:** `app/core/pipeline_cache.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** `clear()` iterates over `self.BASE.iterdir()` and calls `shutil.rmtree(entry)` for each subdirectory. If `rmtree` fails mid-way (e.g., permission error on one entry), the function raises an exception and leaves the cache partially cleared. Subsequent `has()` calls may return `True` for entries whose files were partially deleted.  
**Evidence:** `clear()` method — no try/except around `shutil.rmtree(entry)`.  
**Proposed Fix:** Wrap each `shutil.rmtree` in a try/except and log failures, continuing to the next entry. Return a summary including any failed deletions.

### D4 — Performance

### [G2-19] `_is_json_serializable` calls `json.dumps` on every cache save — O(N) serialization just to check
**File:** `app/core/pipeline_cache.py`  
**Severity:** 🟡 Medium  
**Dimension:** D4  
**Description:** `_is_json_serializable(value)` calls `json.dumps(value)` and discards the result. Then `save()` calls `json.dumps(serializable, ...)` again to actually write the data. For large outputs (e.g., a dict of feature arrays), this doubles the serialization work.  
**Evidence:** `_is_json_serializable` function; `save()` calls it then calls `json.dump` again.  
**Proposed Fix:** Attempt `json.dumps` once and cache the result, or restructure `save()` to attempt serialization directly and catch `TypeError`/`ValueError` as the "not serializable" signal.

### D5 — Test Coverage Gaps

### [G2-20] No test for multi-port AudioSample output caching
**File:** `app/core/pipeline_cache.py`  
**Severity:** 🟡 Medium  
**Dimension:** D5  
**Description:** The bug in G2-17 (only first AudioSample port cached) is undetected because there are no tests for nodes with multiple AudioSample output ports.  
**Proposed Fix:** Add a test: `cache.save(key, {"output": samples_a, "augmented": samples_b})` then assert `cache.load(key)` returns both ports correctly.

### D6 — Security

No issues found.

### D7 — Documentation

### [G2-21] `BASE.setter` docstring says "test isolation only" but is part of the public class
**File:** `app/core/pipeline_cache.py`  
**Severity:** 🔵 Low  
**Dimension:** D7  
**Description:** The `BASE` setter is a public property setter on a public class. Its docstring warns it is "not part of the public API and may be removed," but there is no `_` prefix or `@deprecated` marker to enforce this. External callers may rely on it.  
**Proposed Fix:** Rename to `_base_dir` (private) or add a `DeprecationWarning` in the setter body.

### D8 — Convention Adherence

No issues found.

---

## File 4 — `app/core/executor.py`

### D1 — Code Quality & Correctness

### [G2-22] `node_outputs` dict mutated concurrently from multiple asyncio tasks without synchronisation
**File:** `app/core/executor.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** `run_wave` passes the shared `node_outputs` dict to all `_run_node` tasks, which are run concurrently via `asyncio.gather`. Each task writes `node_outputs[node_id] = outputs`. While asyncio is single-threaded for pure Python, sync nodes are offloaded to a `ThreadPoolExecutor` via `loop.run_in_executor`. The `outputs` assignment itself happens back on the event loop thread (after `await`), so dict writes are safe. However, the artifact registration block reads `run_manager.artifacts` and then writes new artifacts — this is a read-modify pattern that is not atomic if `run_manager.register_artifact` is not thread-safe.  
**Evidence:** `_run_node`: `_prior_artifact_ids.extend(r.artifact_id for r in run_manager.artifacts if r.node_id == _src_id)` followed by `run_manager.register_artifact(...)` — both in the same task, but multiple tasks run concurrently.  
**Proposed Fix:** Verify `RunManager.register_artifact` uses a lock. If not, add one, or move artifact registration to a post-wave serial step.

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

### [G2-23] First exception re-raised but other task exceptions are silently discarded
**File:** `app/core/executor.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** `run_wave` uses `asyncio.gather(..., return_exceptions=True)` and then re-raises only the first exception found. If multiple nodes in a wave fail simultaneously, only the first failure is surfaced. The other failures are silently discarded, making debugging multi-node failures very difficult.  
**Evidence:** `for result in results: if isinstance(result, BaseException): raise result` — stops at first exception.  
**Proposed Fix:** Collect all exceptions and raise an `ExceptionGroup` (Python 3.11+) or a custom `WaveExecutionError` that wraps all failures:
```python
failures = [r for r in results if isinstance(r, BaseException)]
if len(failures) == 1:
    raise failures[0]
elif failures:
    raise WaveExecutionError(f"{len(failures)} nodes failed in wave", failures)
```

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

### [G2-24] No test for wave execution where multiple nodes fail simultaneously
**File:** `app/core/executor.py`  
**Severity:** 🟡 Medium  
**Dimension:** D5  
**Description:** The multi-failure scenario (G2-23) is untested. Tests likely only cover single-node failure in a wave.  
**Proposed Fix:** Add a test with a 3-node wave where 2 nodes raise exceptions, asserting that at least one exception is propagated and the third node's result is still available.

### D6 — Security

No issues found.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.


---

## File 5 — `app/core/conditions.py`

### Security Check — 500-character limit AND `_ALLOWED_NODE_TYPES` whitelist

**500-character limit:** ✅ PRESENT and enforced. The check `if len(expression) > _MAX_EXPRESSION_LENGTH` (where `_MAX_EXPRESSION_LENGTH = 500`) occurs at the very top of `evaluate_condition`, **before** `ast.parse` is called. This correctly prevents DoS via pathologically complex expressions that would be expensive to parse.

**`_ALLOWED_NODE_TYPES` whitelist:** ✅ PRESENT. The frozenset is defined at module level and `_validate_ast` raises `ConditionEvaluationError` for any AST node type not in the set.

**Bypass analysis:** The whitelist is robust against the most common bypass vectors:
- `ast.Attribute` (e.g., `output.__class__`) — NOT in whitelist ✅
- `ast.Import` / `ast.ImportFrom` — NOT in whitelist ✅  
- `ast.Lambda` — NOT in whitelist ✅
- `ast.ListComp` / `ast.DictComp` — NOT in whitelist ✅
- `ast.JoinedStr` (f-strings) — NOT in whitelist ✅
- `ast.FormattedValue` — NOT in whitelist ✅

**One partial concern (see G2-25 below):** `ast.Slice` is not in the whitelist, but `ast.Subscript` IS. In Python 3.9+, `output["key"]` produces `Subscript(slice=Constant(...))` — the `Constant` is in the whitelist. However, `output[1:3]` produces `Subscript(slice=Slice(...))` — `ast.Slice` is NOT in the whitelist, so this is correctly rejected. ✅

**Verdict:** No 🔴 Critical finding. Both controls are present and cannot be bypassed via standard AST manipulation.

### D1 — Code Quality & Correctness

### [G2-25] `ast.NamedExpr` (walrus operator `:=`) not in `_ALLOWED_NODE_TYPES` — correctly blocked, but worth documenting
**File:** `app/core/conditions.py`  
**Severity:** 🔵 Low  
**Dimension:** D1  
**Description:** Python 3.8+ `ast.NamedExpr` (walrus operator) is not in `_ALLOWED_NODE_TYPES` and is correctly rejected. However, the docstring does not mention this explicitly, which could confuse users who try to write `(x := len(output["items"])) > 0`.  
**Evidence:** `_ALLOWED_NODE_TYPES` frozenset — `ast.NamedExpr` absent.  
**Proposed Fix:** Add a note to the module docstring: "Walrus operator (`:=`) is not supported."

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

No issues found. All exception paths raise `ConditionEvaluationError` with descriptive messages.

### D4 — Performance

No issues found. The 500-char limit prevents expensive parse operations.

### D5 — Test Coverage Gaps

### [G2-26] No test for `ast.Attribute` bypass attempt
**File:** `app/core/conditions.py`  
**Severity:** 🟡 Medium  
**Dimension:** D5  
**Description:** The security whitelist should have explicit regression tests for known bypass vectors. Currently there are no tests asserting that `output.__class__`, `output.__dict__`, or `__import__('os')` raise `ConditionEvaluationError`.  
**Proposed Fix:** Add a parametrised security test:
```python
@pytest.mark.parametrize("expr", [
    "output.__class__",
    "__import__('os').system('id')",
    "[x for x in output]",
    "(lambda: 1)()",
])
def test_condition_rejects_dangerous_expressions(expr):
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition(expr, {"output": []})
```

### D6 — Security

No critical issues. See security check above.

### D7 — Documentation

No issues found. Module docstring is thorough.

### D8 — Convention Adherence

No issues found.

---

## File 6 — `app/core/events.py`

### D1 — Code Quality & Correctness

### [G2-27] `QueueSource.close()` called before `watch()` sets `_stop_event` — `close()` is a no-op
**File:** `app/core/events.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1  
**Description:** `_stop_event` is initialised to `None` in `__init__` and only set to an `asyncio.Event()` inside `watch()`. If `close()` is called before `watch()` starts (e.g., during error cleanup), `_stop_event` is `None` and `close()` silently does nothing. The same issue exists for `TimerSource` and `FileWatcherSource`. This means a source that was created but never started cannot be cleanly closed.  
**Evidence:** All three source classes: `self._stop_event: asyncio.Event | None = None` in `__init__`; `close()` checks `if self._stop_event is not None`.  
**Proposed Fix:** Initialise `_stop_event = asyncio.Event()` in `__init__` rather than in `watch()`. This makes `close()` safe to call at any time.

### [G2-28] `TimerSource` drift — uses `asyncio.wait_for` timeout, not wall-clock scheduling
**File:** `app/core/events.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1  
**Description:** `TimerSource` uses `asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_s)` to implement the interval. Each tick takes `interval_s` plus the time to execute the downstream pipeline. Over many ticks, the effective interval drifts. For a 1-second timer running a 0.5-second pipeline, ticks fire at 1.5s, 3.0s, 4.5s — not 1.0s, 2.0s, 3.0s.  
**Evidence:** `TimerSource.watch()` — no wall-clock anchor.  
**Proposed Fix:** Record `next_fire = asyncio.get_event_loop().time() + interval_s` before the loop and compute the remaining wait as `max(0, next_fire - loop.time())` after each tick.

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

### [G2-29] `FileWatcherSource` polling fallback swallows `OSError` silently
**File:** `app/core/events.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** The polling fallback in `FileWatcherSource.watch()` catches `OSError` with `pass`. If the watched directory is deleted or becomes inaccessible, the watcher silently stops yielding events without any log message or error. The caller has no way to distinguish "no new files" from "directory gone."  
**Evidence:** `except OSError: pass` in the polling fallback loop.  
**Proposed Fix:** Log the `OSError` at WARNING level and consider re-raising after N consecutive failures.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

### [G2-30] No test for `create_event_source` with unknown `source_type`
**File:** `app/core/events.py`  
**Severity:** 🔵 Low  
**Dimension:** D5  
**Description:** `create_event_source` raises `ValueError` for unknown types, but this path appears untested.  
**Proposed Fix:** Add: `with pytest.raises(ValueError, match="Unknown event source type"): create_event_source("nonexistent", {})`.

### D6 — Security

No issues found.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.


---

## File 7 — `app/core/ir/models.py`

### Open Item P-23 Verdict — `IRNode.config` mutability inside a frozen model

**Verdict: OPEN — mutable dict inside frozen model. The docstring acknowledges it; the risk is real.**

**Evidence:**
```python
class IRNode(BaseModel):
    model_config = ConfigDict(frozen=True)
    config: dict[str, Any] = {}
```
`frozen=True` prevents reassignment of `IRNode.config` (i.e., `node.config = new_dict` raises `ValidationError`), but it does NOT prevent in-place mutation of the dict itself:
```python
node = IRNode(id="a", node_type="clean", config={"sr": 16000})
node.config["sr"] = 8000   # ← succeeds silently, mutates the frozen model
node.config["injected"] = "evil"  # ← also succeeds
```
The docstring on `IRNode` acknowledges this: *"callers that need a truly immutable config should use `dict(node.config)` to take a shallow copy."* However, this is a documentation-only mitigation. The actual risk is that `_ir_to_pipeline_config` in `pipeline.py` does `config=dict(ir_node.config)` (shallow copy — correct), but `yaml_config_to_ir` in `yaml_shim.py` does `config=n.get("config", {})` — passing the original dict reference. If the caller mutates the raw YAML dict after calling `yaml_config_to_ir`, the `IRNode.config` is silently mutated.

**Fix recommendation:**
```python
from pydantic import field_validator
import copy

@field_validator("config", mode="before")
@classmethod
def _freeze_config(cls, v: dict) -> dict:
    return copy.deepcopy(v)  # deep copy on construction
```
Or use `MappingProxyType` for true immutability:
```python
from types import MappingProxyType
config: Any = {}  # stored as MappingProxyType

@field_validator("config", mode="before")
@classmethod
def _to_proxy(cls, v):
    return MappingProxyType(v) if isinstance(v, dict) else v
```

### D1 — Code Quality & Correctness

### [G2-31] `IRCapabilityMetadata.dependency_requirements` uses mutable default `[]`
**File:** `app/core/ir/models.py`  
**Severity:** 🟠 High  
**Dimension:** D1  
**Description:** `dependency_requirements: list[str] = []` uses a mutable list as a default value. In Pydantic v2, field defaults are copied per-instance, so this is safe at the Pydantic level. However, the list returned by `ir_node.capability_metadata.dependency_requirements` is the instance's own list — callers who do `meta.dependency_requirements.append("torch")` mutate the frozen model's list in place (same issue as `config`). Pydantic's `frozen=True` does not protect list contents.  
**Evidence:** `IRCapabilityMetadata.dependency_requirements: list[str] = []`.  
**Proposed Fix:** Use `tuple[str, ...]` instead of `list[str]` for true immutability, or use `Field(default_factory=list)` and document the mutation risk.

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

No issues found.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

### [G2-32] No round-trip test for `GraphIR` with all optional fields populated
**File:** `app/core/ir/models.py`  
**Severity:** 🟡 Medium  
**Dimension:** D5  
**Description:** The `load_ir(dump_ir(ir)) == ir` round-trip property (see correctness skeleton below) is not tested for `IRNode` instances with `capability_metadata`, `event_trigger`, and `label` all set simultaneously.  
**Proposed Fix:** See Hypothesis skeleton in the correctness properties section.

### D6 — Security

No issues found.

### D7 — Documentation

### [G2-33] `IREdge.condition` field has a duplicated sentence in its docstring
**File:** `app/core/ir/models.py`  
**Severity:** 🔵 Low  
**Dimension:** D7  
**Description:** The `condition` field docstring ends with "Optional boolean condition expression. Edge transmits data only when this evaluates to true." — this sentence is a verbatim repeat of the preceding paragraph.  
**Evidence:** `IREdge.condition` docstring, last line.  
**Proposed Fix:** Remove the duplicate sentence.

### D8 — Convention Adherence

No issues found.

---

## File 8 — `app/core/ir/loader.py`

### D1 — Code Quality & Correctness

### [G2-34] `load_ir` validates Pydantic schema before version check — wrong order
**File:** `app/core/ir/loader.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1  
**Description:** `load_ir` calls `GraphIR.model_validate(data)` first, then `_check_version(graph.schema_version)`. If a future IR document has a new required field that the current `GraphIR` model does not know about, `model_validate` will raise `pydantic.ValidationError` before the version check can raise the more informative `IRVersionError`. The user sees a confusing Pydantic error instead of "incompatible major version."  
**Evidence:** `load_ir`: `graph = GraphIR.model_validate(data)` then `_check_version(graph.schema_version)`.  
**Proposed Fix:** Check the version from the raw dict first:
```python
def load_ir(data: dict[str, Any]) -> GraphIR:
    raw_version = data.get("schema_version", "")
    _check_version(raw_version)  # raises IRVersionError before Pydantic
    return GraphIR.model_validate(data)
```

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

### [G2-35] `dump_ir_to_file` is not atomic — partial write on disk full or interrupt
**File:** `app/core/ir/loader.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** `dump_ir_to_file` opens the destination file with `p.open("w", ...)` and writes directly. If the process is interrupted (SIGKILL, disk full, power loss) mid-write, the file is left in a partially written, invalid JSON state. Subsequent `load_ir_from_file` calls will raise `json.JSONDecodeError`.  
**Evidence:** `dump_ir_to_file` — direct `p.open("w")` write.  
**Proposed Fix:** Write to a temp file in the same directory, then `os.replace` (atomic on POSIX):
```python
import tempfile
tmp = p.with_suffix(".tmp")
with tmp.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
tmp.replace(p)
```

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

### [G2-36] `IRValidationError` is never raised — dead code with no test
**File:** `app/core/ir/loader.py`  
**Severity:** 🔵 Low  
**Dimension:** D5  
**Description:** `IRValidationError` is defined and exported but never raised anywhere in the codebase. It is documented as "reserved for future use." This means it cannot be tested and its presence in `__all__` is misleading.  
**Proposed Fix:** Either raise it from a semantic validation pass (e.g., unreachable node detection) or mark it clearly as `# future use` and exclude it from `__all__` until it is used.

### D6 — Security

No issues found.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.

---

## File 9 — `app/core/ir/yaml_shim.py`

### D1 — Code Quality & Correctness

### [G2-37] `yaml_config_to_ir` crashes on empty `nodes` list with explicit edges
**File:** `app/core/ir/yaml_shim.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1  
**Description:** If `raw_nodes` is empty and `raw_edges` is also absent, the legacy auto-chain path produces an empty `ir_edges` list (correct). But if `raw_nodes` is empty and `raw_edges` is a non-empty list, the explicit-edge parser will produce `IREdge` objects referencing node IDs that don't exist, and `GraphIR._validate_graph` will raise `ValueError: IREdge references unknown source node id`. This is the correct behaviour, but the error message is confusing — it says nothing about the nodes list being empty.  
**Evidence:** `yaml_config_to_ir` — no guard for `len(raw_nodes) == 0`.  
**Proposed Fix:** Add an early guard: `if not raw_nodes: raise ValueError("Pipeline must contain at least one node")`.

### [G2-38] `load_yaml_with_deprecation` opens files without path validation
**File:** `app/core/ir/yaml_shim.py`  
**Severity:** 🟡 Medium  
**Dimension:** D6 (Security)  
**Description:** `load_yaml_with_deprecation(path)` opens `path` directly with `open(path, "r")`. There is no check that `path` is within an expected directory. A caller passing an attacker-controlled path (e.g., from an API request) could read arbitrary files on the filesystem.  
**Evidence:** `load_yaml_with_deprecation`: `with open(path, "r", encoding="utf-8") as f:`.  
**Proposed Fix:** This function is deprecated and should only be called from trusted contexts (CLI, SDK). Add a note to the docstring: "The caller is responsible for validating that `path` is within the expected workspace directory." For API-facing callers, use `migrate_yaml_to_ir_file` with a pre-validated path.

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

No issues found.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

No issues found.

### D6 — Security

See G2-38 above.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.

---

## File 10 — `app/core/ir/migrate.py`

### D1 — Code Quality & Correctness

### [G2-39] `migrate_yaml_to_ir_file` silently overwrites existing output file
**File:** `app/core/ir/migrate.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1  
**Description:** If `output_path` already exists (e.g., a previously migrated file), `dump_ir_to_file` overwrites it without warning. A user who has manually edited the IR JSON file will lose their changes silently.  
**Evidence:** `migrate_yaml_to_ir_file` — no existence check before `dump_ir_to_file(graph, output_path)`.  
**Proposed Fix:** Add an `overwrite: bool = False` parameter and raise `FileExistsError` when `overwrite=False` and the file exists:
```python
if not overwrite and Path(output_path).exists():
    raise FileExistsError(
        f"Output file already exists: {output_path}. "
        "Pass overwrite=True to replace it."
    )
```

### [G2-40] `migrate_yaml_to_ir_file` does not create parent directories of `output_path`
**File:** `app/core/ir/migrate.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3  
**Description:** `dump_ir_to_file` calls `p.open("w", ...)` which raises `FileNotFoundError` if the parent directory of `output_path` does not exist. `migrate_yaml_to_ir_file` does not create parent directories, so migrating to a new subdirectory fails with a confusing error.  
**Evidence:** `migrate_yaml_to_ir_file` — no `Path(output_path).parent.mkdir(parents=True, exist_ok=True)` call.  
**Proposed Fix:** Add `Path(output_path).parent.mkdir(parents=True, exist_ok=True)` before calling `dump_ir_to_file`.

### D2 — Architecture & Design

No issues found.

### D3 — Error Handling

See G2-40 above.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

No issues found.

### D6 — Security

No issues found.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.

---

## File 11 — `app/core/ir/__init__.py`

### D1 — Code Quality & Correctness

No issues found.

### D2 — Architecture & Design

### [G2-41] `yaml_shim` and `migrate` are not exported from `__init__.py`
**File:** `app/core/ir/__init__.py`  
**Severity:** 🔵 Low  
**Dimension:** D2  
**Description:** `yaml_config_to_ir`, `load_yaml_with_deprecation`, and `migrate_yaml_to_ir_file` are not re-exported from `app.core.ir`. Callers must import them directly from their submodules (`app.core.ir.yaml_shim`, `app.core.ir.migrate`). This is inconsistent with the package's stated purpose as a "public API surface." However, since these are deprecated/migration utilities, keeping them out of the main namespace is arguably intentional.  
**Evidence:** `__init__.py` — no imports from `yaml_shim` or `migrate`.  
**Proposed Fix:** Either add them to `__init__.py` with a deprecation note, or add a comment in `__init__.py` explicitly stating they are intentionally excluded: `# yaml_shim and migrate are intentionally not re-exported (deprecated utilities)`.

### D3 — Error Handling

No issues found.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

No issues found.

### D6 — Security

No issues found.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.


---

## OPEN ITEM VERDICTS

---

### P-14 — `pipeline_cache.py`: Two cache formats with no migration path

**Verdict: DEFER**

**Evidence:**

Two storage formats coexist in `PipelineCache`:

| Format | File | Written by | Read by |
|--------|------|-----------|---------|
| Legacy | `manifest.json` + `*.wav` | `save()` when any port has `list[AudioSample]` | `load()` — legacy branch |
| New | `outputs.json` | `save()` for all other output types | `load()` — new branch |

`load()` checks for `outputs.json` first; if absent, falls back to `manifest.json`. This means:
- New-format entries are read correctly ✅
- Legacy-format entries are read correctly ✅
- A cache entry cannot contain both formats simultaneously (save writes one or the other) ✅
- There is **no migration path** to convert existing `manifest.json` entries to `outputs.json` ⚠️

**Why DEFER (not Fix Now):**
The two-format coexistence is functional — `load()` handles both transparently. The absence of a migration path means legacy cache entries persist indefinitely, but they are still readable. The real risk (G2-17) is that the legacy format only caches the first AudioSample port, which is a correctness bug independent of the migration question.

**Recommended action:** Fix G2-17 (multi-port AudioSample caching) as a Fix Now. Add a `migrate_cache()` utility method as a Defer item for the next maintenance cycle. Add a `# TODO: add migrate_cache() to convert manifest.json entries to outputs.json` comment in `pipeline_cache.py`.

---

### P-23 — `ir/models.py`: `IRNode.config` mutable inside a frozen model

**Verdict: OPEN — acknowledged in docstring but not enforced**

**Evidence:** See full analysis in File 7 section above.

`frozen=True` on `IRNode` prevents attribute reassignment but does NOT prevent in-place mutation of the `config` dict:
```python
node = IRNode(id="a", node_type="clean", config={"sr": 16000})
node.config["sr"] = 8000  # succeeds — Pydantic does not protect dict contents
```

The docstring acknowledges this and advises callers to use `dict(node.config)`. `pipeline.py`'s `_ir_to_pipeline_config` correctly takes a shallow copy. However, `yaml_shim.py`'s `yaml_config_to_ir` passes the raw dict reference from the YAML parse result directly to `IRNode(config=n.get("config", {}))` — if the caller mutates the original `raw` dict after calling `yaml_config_to_ir`, the `IRNode.config` is silently mutated.

**Recommended fix:** Add a `field_validator("config", mode="before")` that deep-copies the input dict on construction. This is a one-line fix with no API impact.

---

## CORRECTNESS PROPERTY SKELETONS

---

### Property 1 — `conditions.evaluate_condition` is deterministic

```python
# tests/core/test_conditions_property.py
"""Property: evaluate_condition(expr, ctx) is deterministic.

For any valid expression and any output dict, calling evaluate_condition
twice with the same arguments must return the same result.
"""
from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

from app.core.conditions import evaluate_condition, ConditionEvaluationError

# Strategy: generate simple, valid condition expressions
_SIMPLE_EXPRS = st.sampled_from([
    "len(output['items']) > 0",
    "len(output['items']) == 0",
    "output['score'] > 0.5",
    "output['score'] <= 1.0",
    "len(output['items']) > 0 and output['score'] > 0.5",
    "not (len(output['items']) == 0)",
])

# Strategy: generate output dicts compatible with the expressions above
_OUTPUT_DICTS = st.fixed_dictionaries({
    "items": st.lists(st.integers(), min_size=0, max_size=20),
    "score": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
})


@given(expr=_SIMPLE_EXPRS, output=_OUTPUT_DICTS)
@settings(max_examples=200)
def test_evaluate_condition_is_deterministic(expr: str, output: dict) -> None:
    """evaluate_condition must return the same result on two consecutive calls."""
    try:
        result_1 = evaluate_condition(expr, output)
        result_2 = evaluate_condition(expr, output)
        assert result_1 == result_2, (
            f"Non-deterministic result for expr={expr!r}, output={output!r}: "
            f"{result_1} != {result_2}"
        )
    except ConditionEvaluationError:
        # A ConditionEvaluationError is acceptable (e.g., KeyError on missing key)
        # but it must be raised consistently on both calls — tested separately.
        pass


@given(expr=_SIMPLE_EXPRS, output=_OUTPUT_DICTS)
@settings(max_examples=200)
def test_evaluate_condition_error_is_deterministic(expr: str, output: dict) -> None:
    """If evaluate_condition raises on the first call, it must raise on the second."""
    raised_first = False
    try:
        evaluate_condition(expr, output)
    except ConditionEvaluationError:
        raised_first = True

    raised_second = False
    try:
        evaluate_condition(expr, output)
    except ConditionEvaluationError:
        raised_second = True

    assert raised_first == raised_second, (
        f"Inconsistent exception behaviour for expr={expr!r}, output={output!r}"
    )
```

---

### Property 2 — `load_ir(dump_ir(ir)) == ir` (round-trip lossless)

```python
# tests/core/ir/test_ir_roundtrip_property.py
"""Property: load_ir(dump_ir(ir)) == ir for any valid GraphIR.

Serialising a GraphIR to a dict and deserialising it must produce an
object equal to the original.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ir.loader import load_ir, dump_ir
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode

# Strategy: generate valid node IDs
_node_id = st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,15}", fullmatch=True)

# Strategy: generate a single IRNode
_ir_node = st.builds(
    IRNode,
    id=_node_id,
    node_type=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_")),
    config=st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.one_of(st.integers(), st.floats(allow_nan=False), st.text(max_size=20), st.booleans()),
        max_size=5,
    ),
    label=st.one_of(st.none(), st.text(max_size=30)),
)


@st.composite
def _graph_ir(draw) -> GraphIR:
    """Draw a valid GraphIR with 1–5 nodes and 0–(N-1) edges."""
    # Draw unique node IDs
    n = draw(st.integers(min_value=1, max_value=5))
    ids = draw(st.lists(_node_id, min_size=n, max_size=n, unique=True))
    nodes = [
        IRNode(
            id=nid,
            node_type=draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz_")),
            config=draw(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(), max_size=3)),
        )
        for nid in ids
    ]
    # Draw 0 to N-1 edges (linear chain or empty)
    edges = []
    if n > 1 and draw(st.booleans()):
        for i in range(n - 1):
            edges.append(IREdge(
                src_id=ids[i],
                src_port="output",
                dst_id=ids[i + 1],
                dst_port="input",
            ))
    return GraphIR(
        schema_version="1.1",
        metadata=IRMetadata(name=draw(st.text(min_size=1, max_size=20)), seed=draw(st.integers())),
        nodes=nodes,
        edges=edges,
    )


@given(ir=_graph_ir())
@settings(max_examples=300)
def test_ir_roundtrip_lossless(ir: GraphIR) -> None:
    """load_ir(dump_ir(ir)) must equal the original GraphIR."""
    dumped = dump_ir(ir)
    restored = load_ir(dumped)
    assert restored == ir, (
        f"Round-trip failed.\nOriginal: {ir}\nRestored: {restored}"
    )
```

---

### Property 3 — `PipelineCache.get(key)` after `put(key, val)` returns `val`

```python
# tests/core/test_pipeline_cache_property.py
"""Property: cache.load(key) after cache.save(key, val) returns val.

For any JSON-serialisable outputs dict, saving then loading must return
an equivalent dict.
"""
import tempfile
from pathlib import Path

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.pipeline_cache import PipelineCache

# Strategy: generate JSON-serialisable outputs dicts
_json_value = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.text(max_size=50),
)

_outputs_dict = st.dictionaries(
    keys=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    values=_json_value,
    min_size=1,
    max_size=5,
)


@given(
    node_type=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    config=st.dictionaries(st.text(min_size=1, max_size=10), st.integers(), max_size=3),
    outputs=_outputs_dict,
)
@settings(max_examples=200)
def test_cache_put_then_get_returns_value(
    node_type: str,
    config: dict,
    outputs: dict,
) -> None:
    """After save(key, outputs), load(key) must return an equivalent dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = PipelineCache()
        cache.BASE = Path(tmpdir)

        input_hash = cache.input_hash([1, 2, 3])  # stable dummy input
        key = cache.key(node_type, config, input_hash)

        # Precondition: cache is empty
        assume(not cache.has(key))

        cache.save(key, outputs)
        assert cache.has(key), "has() must return True after save()"

        loaded = cache.load(key)
        assert loaded is not None, "load() must not return None after save()"

        # Only compare keys that are JSON-serialisable (None values may be skipped)
        for port, value in outputs.items():
            if value is not None:
                assert port in loaded, f"Port '{port}' missing from loaded cache"
                assert loaded[port] == value, (
                    f"Port '{port}': expected {value!r}, got {loaded[port]!r}"
                )
```


---

## SUMMARY TABLE

| ID | Title | File | Severity | Dimension |
|----|-------|------|----------|-----------|
| G2-01 | `asyncio.run()` inside running event loop | `pipeline.py` | 🔴 Critical | D1 |
| G2-02 | `parallel=True` + `event_driven=True` both execute | `pipeline.py` | 🟠 High | D1 |
| G2-03 | Condition expression evaluated twice (TOCTOU) | `pipeline.py` | 🟡 Medium | D1 |
| G2-04 | `_write_checkpoint` path traversal via `node_id` | `pipeline.py` | 🟠 High | D6 |
| G2-05 | No cancel check between waves in parallel mode | `pipeline.py` | 🟠 High | D3 |
| G2-06 | Event-driven mode ignores conditional edges | `pipeline.py` | 🟠 High | D1 |
| G2-07 | `run_pipeline_ir_async` is 740 lines — violates SRP | `pipeline.py` | 🟡 Medium | D2 |
| G2-08 | Partial checkpoint data silently discarded | `pipeline.py` | 🟡 Medium | D3 |
| G2-09 | O(N²) `_resolve_capability` scan in sequential loop | `pipeline.py` | 🟡 Medium | D4 |
| G2-10 | `event_loop` parameter accepted but never used | `pipeline.py` | 🔵 Low | D7 |
| G2-11 | Late imports inside hot execution loop | `pipeline.py` | 🔵 Low | D8 |
| G2-12 | `_validate_dag_edges` does not guard `None` node IDs | `validation.py` | 🟠 High | D1 |
| G2-13 | `_validate_connections` swallows non-ValueError silently | `validation.py` | 🟡 Medium | D3 |
| G2-14 | No test for DAG-format edge validation | `validation.py` | 🟡 Medium | D5 |
| G2-15 | `validate_node_config` tombstone lacks migration example | `validation.py` | 🔵 Low | D7 |
| G2-16 | `has()` / `load()` TOCTOU race | `pipeline_cache.py` | 🟠 High | D1 |
| G2-17 | `save()` drops all but first AudioSample port | `pipeline_cache.py` | 🟠 High | D1 |
| G2-18 | `clear()` not atomic — partial deletion on error | `pipeline_cache.py` | 🟡 Medium | D3 |
| G2-19 | Double JSON serialization in `save()` | `pipeline_cache.py` | 🟡 Medium | D4 |
| G2-20 | No test for multi-port AudioSample caching | `pipeline_cache.py` | 🟡 Medium | D5 |
| G2-21 | `BASE.setter` undocumented as private API | `pipeline_cache.py` | 🔵 Low | D7 |
| G2-22 | `node_outputs` / artifact registration concurrent access | `executor.py` | 🟠 High | D1 |
| G2-23 | Only first wave exception surfaced; others discarded | `executor.py` | 🟡 Medium | D3 |
| G2-24 | No test for multi-node wave failure | `executor.py` | 🟡 Medium | D5 |
| G2-25 | Walrus operator not documented as unsupported | `conditions.py` | 🔵 Low | D1 |
| G2-26 | No security regression tests for AST bypass vectors | `conditions.py` | 🟡 Medium | D5 |
| G2-27 | `close()` before `watch()` is a no-op on all sources | `events.py` | 🟡 Medium | D1 |
| G2-28 | `TimerSource` interval drifts under load | `events.py` | 🟡 Medium | D1 |
| G2-29 | `FileWatcherSource` polling swallows `OSError` silently | `events.py` | 🟡 Medium | D3 |
| G2-30 | No test for `create_event_source` unknown type | `events.py` | 🔵 Low | D5 |
| G2-31 | `dependency_requirements` mutable list in frozen model | `ir/models.py` | 🟠 High | D1 |
| G2-32 | No round-trip test with all optional fields populated | `ir/models.py` | 🟡 Medium | D5 |
| G2-33 | `IREdge.condition` docstring has duplicate sentence | `ir/models.py` | 🔵 Low | D7 |
| G2-34 | Pydantic validation before version check — wrong order | `ir/loader.py` | 🟡 Medium | D1 |
| G2-35 | `dump_ir_to_file` not atomic — partial write on interrupt | `ir/loader.py` | 🟡 Medium | D3 |
| G2-36 | `IRValidationError` never raised — dead code | `ir/loader.py` | 🔵 Low | D5 |
| G2-37 | `yaml_config_to_ir` crashes with empty nodes + edges | `ir/yaml_shim.py` | 🟡 Medium | D1 |
| G2-38 | `load_yaml_with_deprecation` opens arbitrary file paths | `ir/yaml_shim.py` | 🟡 Medium | D6 |
| G2-39 | `migrate_yaml_to_ir_file` silently overwrites output | `ir/migrate.py` | 🟡 Medium | D1 |
| G2-40 | `migrate_yaml_to_ir_file` does not create parent dirs | `ir/migrate.py` | 🟡 Medium | D3 |
| G2-41 | `yaml_shim`/`migrate` not exported from `__init__.py` | `ir/__init__.py` | 🔵 Low | D2 |

### Totals by Severity

| Severity | Count |
|----------|-------|
| 🔴 Critical | 1 |
| 🟠 High | 10 |
| 🟡 Medium | 20 |
| 🔵 Low | 10 |
| **Total** | **41** |

### Totals by Dimension

| Dimension | Count |
|-----------|-------|
| D1 Code Quality & Correctness | 15 |
| D2 Architecture & Design | 2 |
| D3 Error Handling | 7 |
| D4 Performance | 3 |
| D5 Test Coverage Gaps | 8 |
| D6 Security | 3 |
| D7 Documentation | 4 |
| D8 Convention Adherence | 1 |

### Open Items

| Item | Verdict |
|------|---------|
| P-14 Two cache formats, no migration path | **DEFER** — both formats readable; fix G2-17 first |
| P-23 `IRNode.config` mutable in frozen model | **OPEN** — acknowledged in docstring; add `field_validator` deep-copy |

---

*End of report — G2 Pipeline & IR*
