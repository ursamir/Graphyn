# Pipeline & IR Layer Review

**Date:** 2026-05-18  
**Files:** `pipeline.py`, `validation.py`, `pipeline_cache.py`, `executor.py`, `conditions.py`, `events.py`, `ir/models.py`, `ir/loader.py`, `ir/migrate.py`, `ir/yaml_shim.py`

---

## `pipeline.py`

### P-01 🟠 `asyncio.run()` crashes inside a running event loop
`run_pipeline_ir()` is a sync shim that calls `asyncio.run(run_pipeline_ir_async(...))`. Calling this from inside an already-running event loop (FastAPI endpoint, Jupyter notebook, pytest-asyncio) raises:
```
RuntimeError: This event loop is already running
```

**Fix:** Use `asyncio.get_event_loop().run_until_complete()` with a fallback, or add `nest_asyncio` support, or expose `run_pipeline_ir_async` as the primary API and make the sync shim optional.

---

### P-02 🟡 `EdgeSpec` does not carry `condition` — split representation
`IREdge.condition` is not copied into `EdgeSpec` during `_ir_to_pipeline_config()`. The condition is re-read from `graph.edges` via a separate `edge_conditions` dict in `run_pipeline_ir_async`. This split representation means:
- `PipelineGraph` has no knowledge of conditions
- Any code that works with `EdgeSpec` (e.g. `ParallelExecutor`) must also receive `edge_conditions` separately

**Fix:** Add `condition: str | None = None` to `EdgeSpec` and populate it in `_ir_to_pipeline_config()`.

---

### P-03 🟡 `_write_checkpoint` silently skips on disk-full
```python
except Exception as exc:
    log.warning("Checkpoint write failed for node '%s': %s", node_id, exc)
```
A disk-full error is logged as a warning and execution continues. The checkpoint is then missing, and a subsequent `resume_run_id` call will silently re-execute the node. The user has no indication that resume will not work.

**Fix:** Emit a structured `checkpoint_failed` event via the logger so the API/CLI can surface it.

---

### P-04 🟡 `_infer_artifact_type` uses fragile duck-typing
```python
if hasattr(value, "X_train"):
    return "generic"
```
Checking for `X_train` to detect `DatasetArtifact` is brittle. Any object with an `X_train` attribute (including mocks in tests) will be misclassified.

**Fix:** Use `isinstance` against the actual model class:
```python
from app.models.dataset_artifact import DatasetArtifact
if isinstance(value, DatasetArtifact):
    return "generic"
```

---

### P-05 🟡 `PipelineGraph._compute_waves` is O(N×E)
```python
preds = [e.src_id for e in self._edges if e.dst_id == node_id]
```
This inner loop runs for every node, scanning all edges each time. For a graph with N nodes and E edges this is O(N×E).

**Fix:** Precompute a predecessors dict once:
```python
predecessors: dict[str, list[str]] = defaultdict(list)
for e in self._edges:
    predecessors[e.dst_id].append(e.src_id)
```

---

### P-06 🟡 `NodeExecutor.execute_stream` — `on_end()` not called on early exit
```python
async def execute_stream(self, inputs):
    node.on_start()
    try:
        async for item in node.process_stream(inputs):
            yield item
    except Exception as exc:
        node.on_error(exc)
        raise
    node.on_end()   # ← never reached if caller breaks out of async for
```
If the caller breaks out of the `async for` early, `on_end()` is never called, leaving the node in a started-but-not-ended state.

**Fix:**
```python
async def execute_stream(self, inputs):
    node.on_start()
    try:
        async for item in node.process_stream(inputs):
            yield item
    except Exception as exc:
        node.on_error(exc)
        raise
    finally:
        node.on_end()
```

---

### P-07 🔵 `_count_payload` / `_payload_count` are dead code
These legacy helpers duplicate logic from `_count_port_items` and are only used for string formatting in old code paths. They should be removed or consolidated.

---

## `validation.py`

### P-08 🟡 `_validate_connections` uses `__new__` to access `ClassVar`
```python
instance = node_class.__new__(node_class)
```
`input_ports` and `output_ports` are `ClassVar` — they can be accessed directly on the class without instantiation:
```python
node_class.output_ports
```
The `__new__` approach is fragile if `__init_subclass__` has side effects (e.g. the SISO wrapper installation).

---

### P-09 🔴 `validate_node_config` always returns `{}` — silent false pass
```python
def validate_node_config(node_type: str, config: dict, schema: dict) -> dict:
    errors: dict[str, str] = {}
    # This function is kept only for any external callers...
    return errors
```
Any caller relying on this function for validation gets an empty dict (no errors) regardless of input. This is a silent correctness bug for any code that hasn't been migrated.

**Fix:** Replace the body with:
```python
raise NotImplementedError(
    "validate_node_config is deprecated. Use registry.get_class(node_type).Config.model_validate(config) instead."
)
```

---

### P-10 🟡 Edge `"from"` field type not validated in `_validate_dag_edges`
```python
edge.get("from", [None])[0]
```
If `"from"` is a string (e.g. `"input_0"`) instead of a list, `[0]` returns the first character of the string. No type check is performed before indexing.

---

## `pipeline_cache.py`

### P-11 🔴 `input_hash` repr() fallback is not stable across runs
```python
return hashlib.sha256(repr(inputs).encode()).hexdigest()
```
`repr()` of numpy arrays can include memory addresses in edge cases. Cache keys derived from `repr()` will miss on the second run, silently defeating the cache for those node types (e.g. `DatasetArtifact` with numpy arrays).

**Fix:** For numpy arrays, use a deterministic hash of the array data:
```python
import numpy as np
if isinstance(inputs, np.ndarray):
    return hashlib.sha256(inputs.tobytes()).hexdigest()
```

---

### P-12 🟠 Non-serializable ports are silently skipped during `save()`
```python
logger.debug("Cache.save: port '%s' not serializable — skipping port", port_name)
```
If a node produces a numpy array on its `"output"` port, the cache write is silently skipped. The next run re-executes the node even though `use_cache=True`. No warning is emitted to the user.

**Fix:** Emit at `WARNING` level, not `DEBUG`, so operators can identify uncacheable nodes.

---

### P-13 🟡 `PipelineCache.BASE` property with setter is a test-only hack in the public API
The `_base_override` / `BASE.setter` pattern was added for test isolation but is now part of the public API. Tests should use `monkeypatch` on the `_cache_dir` config function instead.

---

### P-14 🟡 Two storage formats add complexity with no migration path
`load()` tries `outputs.json` first, then falls back to `manifest.json`. Old cache entries in WAV format are never migrated to the new JSON format. The dual-format logic will persist indefinitely.

**Recommendation:** Add a `migrate_cache()` utility that converts old manifest.json entries to outputs.json format, and document a deprecation timeline for the WAV format.

---

## `executor.py` (ParallelExecutor)

### P-15 🔴 New `ThreadPoolExecutor` created per node — extreme overhead
```python
with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
    outputs = await loop.run_in_executor(pool, exec_.execute, inputs)
```
A new thread pool is created and destroyed for every single node execution. Thread pool creation involves OS-level thread spawning. For a 10-node pipeline this creates and destroys 10 thread pools.

**Fix:** Create one pool per wave (or per `ParallelExecutor` instance) and reuse it:
```python
async def run_wave(self, wave, ...):
    with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
        tasks = [asyncio.create_task(self._run_node(..., pool=pool)) for node_id in wave]
        ...
```

---

### P-16 🟡 `_run_node` imports `_resolve_capability` from `pipeline.py` — private cross-module coupling
```python
from app.core.pipeline import _write_checkpoint, _resolve_capability
```
Importing private functions from another module is a design smell. `_resolve_capability` and `_write_checkpoint` should either be moved to a shared utilities module or made public.

---

### P-17 🟡 `node_index_map.get(node_id, 0)` — unknown nodes logged as index 0
If a node_id is not in `node_index_map`, index `0` is used for logging, making all unknown nodes appear as "node 0" in the log output. Should use `-1` or `"?"` as a sentinel.

---

## `conditions.py`

### P-18 🟡 No depth/complexity limit on condition expressions
A deeply nested expression like `len(output["a"]) + len(output["b"]) + ...` repeated 1000 times is syntactically valid and will be evaluated. No DoS protection for maliciously crafted condition strings.

**Fix:** Add a max expression length check:
```python
if len(expression) > 500:
    raise ConditionEvaluationError("Condition expression exceeds maximum length of 500 characters")
```

---

### P-19 🔵 `ast.Index` in `_ALLOWED_NODE_TYPES` is misleading
`ast.Index` was removed in Python 3.9. The project uses Python 3.12 (per `__pycache__` filenames). Including it in the whitelist is harmless but the comment "Python 3.8 compat" is misleading and should be removed.

---

## `events.py`

### P-20 🟠 `TimerSource` and `QueueSource` have no stop mechanism
`TimerSource.watch()` runs `while True` with no cancellation path. `close()` is a no-op. The only way to stop these sources is to cancel the asyncio task from outside, which is not documented.

**Fix:** Add a `_stop_event: asyncio.Event` to both classes, set it in `close()`, and check it in the `while True` loop.

---

### P-21 🟡 `FileWatcherSource` polling fallback interval is hardcoded at 1 second
```python
await asyncio.sleep(1.0)
```
For high-frequency file events (e.g. streaming audio chunks) this is too slow. The interval should be configurable via `source_config`.

---

### P-22 🔵 `create_event_source` passes `source_config` as `**kwargs` without validation
If `source_config` contains unexpected keys, the constructor raises `TypeError` with a confusing message like `"__init__() got an unexpected keyword argument 'foo'"`. Should validate keys against the constructor signature and raise a clear `ValueError`.

---

## IR (`ir/`)

### P-23 🟡 `IRNode.config` is a mutable dict inside a frozen model
`GraphIR` and `IRNode` use `ConfigDict(frozen=True)` but `config: dict[str, Any]` is a mutable dict. The dict itself can be mutated even though the model is "frozen":
```python
node = IRNode(id="n1", node_type="clean", config={"sr": 16000})
node.config["sr"] = 8000  # succeeds silently — frozen model is not truly immutable
```

**Fix:** Use `types.MappingProxyType` for the config dict, or document this limitation clearly.

---

### P-24 🟡 `IRMetadata.name` validator does not strip whitespace from stored value
```python
@field_validator("name")
@classmethod
def _name_non_empty(cls, v: str) -> str:
    if not v.strip():
        raise ValueError(...)
    return v   # ← returns original v, not v.strip()
```
`"  pipeline  "` passes validation but is stored with leading/trailing spaces.

**Fix:** `return v.strip()`

---

### P-25 🟡 `load_ir_from_file` does not check `p.is_file()`
```python
if not p.exists():
    raise FileNotFoundError(...)
```
`Path.exists()` returns `True` for directories. Passing a directory path will proceed to `json.load()` and raise a confusing `IsADirectoryError` instead of a clear `FileNotFoundError`.

**Fix:** `if not p.is_file(): raise FileNotFoundError(...)`
