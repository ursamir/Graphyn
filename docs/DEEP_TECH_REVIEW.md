# Deep Technical Review — Graphyn Pipeline Engine

---

## 1. Architecture Overview

The system is a well-structured AI/workflow pipeline engine with four interfaces (REST API, SDK, CLI, MCP) sharing a common `app/core/` layer. The plugin system, node registry, IR model, and execution engine are all clearly separated. The codebase shows evidence of iterative hardening (many `G2-xx`, `P-xx`, `B-xx` fix comments), which is a positive sign, but also reveals a pattern of reactive patching rather than proactive design.

---

## 2. Security Issues

### 2.1 — MCP Auth Token Evaluated at Module Import Time (Critical)
**File:** `app/mcp/auth.py`, line 12

```python
_TOKEN = _api_token()  # module-level, evaluated once at import
```

The token is read once when the module is first imported. If `GRAPHYN_API_TOKEN` is set after the process starts (e.g., via a secrets manager, a `.env` loader, or a test fixture), the MCP server will run without auth for the entire lifetime of the process. The REST API has the same issue in `app/api/main.py` line 30.

**Impact:** Silent auth bypass in any deployment that injects secrets after process start.

**Fix:** Read the token inside `check_auth()` on every call, or use a lazy-loaded singleton that re-reads the env var.

---

### 2.2 — CORS Wildcard Headers (`allow_headers=["*"]`)
**File:** `app/api/main.py`, line 47

```python
allow_headers=["*"],
```

Combined with `allow_credentials=True`, this is a CORS misconfiguration. The `Access-Control-Allow-Headers: *` wildcard is not honoured by browsers when credentials are included — but the intent is clearly to allow all headers, which means any origin that matches the allowlist can send arbitrary headers including `Authorization`. This is fine for the listed localhost origins, but if the origin list is ever widened (e.g., to a wildcard or a production domain), this becomes a credential-leaking CORS vulnerability.

**Impact:** Medium risk now; high risk if origins are ever relaxed.

**Fix:** Enumerate the specific headers needed (`Authorization`, `Content-Type`) instead of `*`.

---

### 2.3 — Webhook SSRF: No Private IP Blocking
**File:** `app/core/webhook.py`, `save()` method

The `save()` method validates that the URL uses `http`/`https` and has a host, but does not block private/loopback addresses (`127.0.0.1`, `10.x.x.x`, `192.168.x.x`, `169.254.x.x`, `::1`). An authenticated user can configure a webhook pointing to `http://127.0.0.1:8001/api/v1/system/cleanup` and trigger it via `POST /api/v1/system/webhooks/test`, causing the server to make requests to itself or internal services.

**Impact:** SSRF — internal service enumeration and potential destructive self-requests.

**Fix:** Resolve the hostname and reject RFC 1918 / loopback / link-local addresses before saving.

---

### 2.4 — Ingest URL: No Size Limit on Downloads
**File:** `app/core/ingestion.py`, `_run_url_job()`

```python
response = client.get(url)
response.raise_for_status()
dest_path.write_bytes(response.content)
```

`response.content` buffers the entire response body in memory before writing. There is no `Content-Length` check or streaming write. A malicious URL returning a multi-GB response will exhaust server memory.

**Impact:** Denial of service via memory exhaustion.

**Fix:** Use `httpx` streaming (`client.stream(...)`) with a maximum byte counter, rejecting responses that exceed a configurable limit (e.g., 500 MB).

---

### 2.5 — Plugin Install: Arbitrary Code Execution via `source` Parameter
**File:** `app/api/routers/plugins.py`, `install_plugin()` / `app/core/plugins/manager.py`

The `POST /api/v1/plugins/install` endpoint accepts a `source` string that is passed directly to `PluginInstaller.resolve()`, which can fetch and execute arbitrary code from `git+`, `http://`, or `https://` URLs. There is no allowlist, no signature verification, and no sandboxing. Any authenticated user (or any user when auth is disabled) can install a plugin that registers a malicious `Node` subclass that runs arbitrary Python when `process()` is called.

**Impact:** Remote code execution on the server.

**Fix:** This is an inherent risk of a plugin system. At minimum: require auth for install endpoints (already done when token is set), add a plugin signature/checksum verification step, and document clearly that the install endpoint must never be exposed publicly.

---

### 2.6 — `_run_dir()` Validation Is Insufficient
**File:** `app/api/routers/runs.py`, line 18

```python
if not run_id.replace("-", "").isalnum():
    raise HTTPException(status_code=400, detail="Invalid run_id")
path = _get_runs_root() / run_id
```

The validation strips hyphens before checking `isalnum()`, which means a run_id of `--` passes the check (empty string after stripping). More importantly, the path is constructed without a `resolve()` + `is_relative_to()` check. If `_get_runs_root()` returns a symlink target, a crafted run_id could escape the runs directory.

**Impact:** Low risk currently, but the pattern is inconsistent with the `_safe_child()` guard used in `data.py`.

**Fix:** Use the same `_safe_child()` pattern: `resolve()` the final path and assert it is relative to the runs root.

---

### 2.7 — Condition Evaluator: `eval()` with Compiled AST
**File:** `app/core/conditions.py`

The condition evaluator uses `eval()` with a compiled AST after whitelist validation. The whitelist is correct and the `__builtins__` is restricted to `{"len": len}`. However, `ast.Subscript` is allowed without restricting what is subscripted — only `ast.Name` nodes named `output` are blocked from being non-`output`/`len`. A crafted expression like `output.__class__.__mro__` would be caught because `ast.Attribute` is not in `_ALLOWED_NODE_TYPES`. This is correctly handled.

**Minor gap:** The 500-character length limit is a DoS guard, but there is no depth limit on the AST. A deeply nested expression like `len(len(len(...)))` would pass the whitelist check (all `len` calls) but fail at runtime with a `TypeError`. This is not exploitable but could produce confusing error messages.

---

## 3. Architectural Issues

### 3.1 — Dual `run_id` Variables in `run_pipeline_ir_async`
**File:** `app/core/pipeline.py`, lines ~760 and ~800

```python
run = RunManager()          # run.run_id = 16-char hex
...
run_id = str(uuid.uuid4())  # separate full UUID4
```

`RunManager` generates its own `run_id` (16-char hex). Then `run_pipeline_ir_async` creates a *second* `run_id` (full UUID4) and passes it to `NodeExecutor`. These two IDs are different. The `RunManager.run_id` is what gets persisted to disk and returned to the API caller. The `NodeExecutor.run_id` is what gets passed to observer callbacks. This means observer events reference a run_id that does not match the persisted run directory — a silent inconsistency that breaks any tooling that correlates observer events with run metadata.

**Impact:** Observer/monitoring integrations receive a run_id that cannot be looked up via the API.

**Fix:** Pass `run.run_id` to `NodeExecutor` instead of creating a new UUID.

---

### 3.2 — `run_pipeline_ir_async` Defined Twice
**File:** `app/core/pipeline.py`

The function `run_pipeline_ir_async` appears to be defined twice in the file (the file is 1510 lines; the first definition starts around line 450 and a second definition starts around line 680 with identical signature). The second definition silently shadows the first. This is a serious maintenance hazard — any changes to the first definition are invisible at runtime.

**Impact:** Dead code, confusion, potential divergence between the two implementations.

**Fix:** Remove the duplicate. Verify which definition is actually executed.

---

### 3.3 — `Pipeline.validate()` Calls `validate_pipeline()` Without `registry` Argument
**File:** `app/core/sdk.py`, `validate()` method

```python
errors: list[str] = []
try:
    validate_pipeline(pipeline_cfg)   # ← missing registry argument
except Exception as exc:
    errors.append(str(exc))
```

`validate_pipeline(config, registry)` requires two arguments. Calling it with one will raise `TypeError` at runtime, which is caught by the bare `except Exception` and returned as a validation error string. The method always returns a non-empty error list, making it completely broken.

**Impact:** `Pipeline.validate()` is silently non-functional.

**Fix:** Pass `get_registry()` as the second argument.

---

### 3.4 — `PipelineNode._ir_node` Uses Hardcoded `_0` Suffix
**File:** `app/core/sdk.py`, `PipelineNode.__init__()`

```python
self._ir_node = IRNode(
    id=f"{self.node_type}_0",   # always _0
    ...
)
```

When a `Pipeline` is built, `to_ir_node(node_index)` is called with the correct index. But `_ir_node` (used by `to_dict()`) always has `_0`. If two nodes of the same type exist in a pipeline, both `_ir_node` objects have the same `id`, which would fail `GraphIR`'s duplicate-id validator. This is only a problem if `_ir_node` is used directly rather than going through `to_ir_node()`, but it is a latent bug.

---

### 3.5 — `ArtifactStore` Global Lock Contention
**File:** `app/core/artifact_store.py`, `register()`

The entire `register()` method — including `_serialize_data()` which writes WAV files to disk — runs under `self._lock`. For large audio datasets, this serialization can take seconds, blocking all concurrent artifact registrations for the entire duration. In parallel wave execution, multiple nodes complete simultaneously and all try to register artifacts under the same lock.

**Impact:** Parallel execution throughput is bottlenecked by sequential artifact serialization.

**Fix:** Serialize data outside the lock; only hold the lock for the index read-modify-write.

---

### 3.6 — `IngestionService` Is a Module-Level Singleton
**File:** `app/api/routers/ingest.py`, line 16

```python
_svc = IngestionService()
```

This singleton is created at module import time. `IngestionService.BASE_INPUT` is a property that calls `_datasets_input_dir()` on every access, which is correct. But the `_jobs` dict is a module-level global shared across all requests and all test runs. There is no cleanup mechanism for the in-process job store between test runs, and the 200-job eviction limit only removes completed jobs — a long-running job that never completes will never be evicted.

**Impact:** Memory leak for stuck jobs; test isolation issues.

---

### 3.7 — `TEMPLATES_DIR` Is a Hardcoded Relative Path
**File:** `app/api/routers/pipelines.py`, line 22

```python
TEMPLATES_DIR = Path("workspace/configs/templates")
```

This is a relative path resolved from the process working directory, not from `GRAPHYN_PROJECT_DIR`. If the server is started from a directory other than the project root, templates will be read from and written to the wrong location. All other workspace paths use `app.core.config` functions.

**Impact:** Templates silently go missing or are created in unexpected locations.

**Fix:** Use `project_dir() / "configs" / "templates"` from `app.core.config`.

---

### 3.8 — `system.py` Cleanup Uses Hardcoded `Path("workspace")`
**File:** `app/api/routers/system.py`, lines 17–18

```python
WORKSPACE_ROOT = Path("workspace").resolve()
RUNS_ROOT = WORKSPACE_ROOT / "runs"
CACHE_ROOT = WORKSPACE_ROOT / "cache"
```

Same issue as 3.7 — these are resolved from the CWD, not from `GRAPHYN_PROJECT_DIR`. The cleanup endpoint will silently do nothing if the server is not started from the project root.

---

## 4. Code Quality Issues

### 4.1 — `NodeExecutor.execute()` Calls `on_error` and `on_end` Twice on Final Failure
**File:** `app/core/pipeline.py`, `NodeExecutor.execute()`

In the retry loop, `on_error()` is called inside the loop on each failed attempt. After all attempts are exhausted, `on_error()` is called *again* outside the loop before re-raising. This means the final exception triggers two `on_error` calls — one from the last loop iteration and one from the post-loop block. Observer implementations that count errors will see an inflated count.

```python
# Inside loop:
node.on_error(exc)
if observer: observer.on_node_error(...)
last_exc = exc
continue

# After loop:
node.on_error(last_exc)   # ← duplicate
if observer: observer.on_node_error(...)  # ← duplicate
```

---

### 4.2 — `_maybe_wrap_siso` SISO Detection Is Fragile
**File:** `app/core/nodes/base.py`, `_maybe_wrap_siso()`

The SISO detection relies on the second parameter name not being `"inputs"`. This means a node that uses `process(self, inputs)` with a single-value input (not a dict) will be treated as multi-port and receive a dict instead of the raw value. Conversely, a multi-port node that names its parameter something other than `"inputs"` (e.g., `process(self, data)`) will be incorrectly wrapped as SISO. The convention is fragile and undocumented at the call site.

---

### 4.3 — `PipelineCache.has()` TOCTOU Warning Is Documented but Not Fixed
**File:** `app/core/pipeline_cache.py`, `has()` method

The docstring explicitly warns about a TOCTOU race between `has()` and `load()`. The code in `executor.py` still calls `cache.has()` followed by `cache.load()` as two separate operations. The fix (call `load()` directly and treat `None` as a miss) is described in the docstring but not applied at the call site.

---

### 4.4 — `ArtifactStore.get_versions()` Performs a Full Directory Scan
**File:** `app/core/artifact_store.py`, `get_versions()`

```python
def get_versions(self, artifact_name: str) -> list[ArtifactRecord]:
    return [r for r in self.list() if r.name == artifact_name]
```

`self.list()` with no filters triggers the slow-path full directory scan. The docstring acknowledges this but there is no `by_name/` secondary index. For stores with thousands of artifacts, this is O(N) disk reads.

---

### 4.5 — `AudioClassifierNode` Input Port Uses `data_type=list` (Untyped)
**File:** `PluginPackage/Audio/audio_classifier/nodes.py`, line 57

```python
"input": InputPort(
    name="input",
    data_type=list,   # ← no element type
    ...
)
```

The port accepts `list` without specifying the element type (`list[AudioSample]` or `list[FeatureArray]`). The `CompatibilityChecker` cannot validate connections to this port — any `list`-producing node will be considered compatible. This defeats the type-safety of the port system.

---

### 4.6 — `TrainerNode` and `ModelBuilderNode` Use `data_type=object`
**File:** `PluginPackage/Common/trainer/nodes.py`

Both nodes declare `data_type=object` for their `model` and `dataset` ports. This is the same problem as 4.5 — the type system is bypassed entirely for the most complex nodes in the system.

---

### 4.7 — `SpeechEnhancerNode._resolve_backend()` Called Twice
**File:** `PluginPackage/Audio/speech_enhancer/nodes.py`

```python
def process(self, samples):
    backend = getattr(self, "_resolved_backend", None) or self._resolve_backend()
```

`setup()` sets `self._resolved_backend`. But `process()` falls back to calling `_resolve_backend()` again if `_resolved_backend` is falsy. Since `_resolve_backend()` imports and probes packages, this is an unnecessary overhead on every call when `setup()` was not called (e.g., in unit tests that call `process()` directly).

---

### 4.8 — `_write_checkpoint` Only Checkpoints the First List Port
**File:** `app/core/pipeline.py`, `_write_checkpoint()`

```python
for v in outputs.values():
    if isinstance(v, list):
        result = v
        break
```

Only the first list-valued output port is checkpointed. Multi-port nodes that produce lists on multiple ports will have all but the first silently dropped from the checkpoint. Resume will then re-execute those nodes even though they completed successfully.

---

### 4.9 — `NodeExecutor.execute()` Calls `on_start()` Then Calls Observer `on_node_start` Separately
**File:** `app/core/pipeline.py`, `NodeExecutor.execute()`

`node.on_start()` already calls `observer.on_node_start()` internally (in `Node.on_start()`). Then `NodeExecutor.execute()` calls `observer.on_node_start()` again directly. This results in every observer receiving two `on_node_start` events per node execution. The same double-firing applies to `on_end` and `on_error`.

---

## 5. Performance Bottlenecks

### 5.1 — Graph Hash Computed Twice Per Run
**File:** `app/core/pipeline.py`, `run_pipeline_ir_async()`

```python
# Line ~760:
run.save_graph_ir(dump_ir(graph))   # computes hash internally

# Line ~800:
graph_hash = _hashlib.sha256(
    json.dumps(dump_ir(graph), sort_keys=True).encode()
).hexdigest()
```

`dump_ir(graph)` is called twice, and the hash is computed twice. `run.save_graph_ir()` already computes and stores `self._graph_hash`. The second computation is redundant.

**Fix:** Use `run._graph_hash` after calling `save_graph_ir()`.

---

### 5.2 — `PipelineCache.input_hash()` Falls Back to `repr()` for Multi-Port Inputs
**File:** `app/core/pipeline_cache.py`, `input_hash()`

The method receives `list(inputs.values())` — a list of all port values. For multi-port nodes, this is a list of heterogeneous values. The `repr()` fallback is not stable across process restarts (object addresses in repr strings change). This means cache keys for multi-port nodes are effectively random across restarts, making the cache useless for them.

---

### 5.3 — `find_latest_checkpoint()` Scans All Run Directories
**File:** `app/core/run_manager.py`, `find_latest_checkpoint()`

```python
for run_dir_name in os.listdir(runs_dir_path):
    ...
    checkpoint_dir = os.path.join(runs_dir_path, run_dir_name, "checkpoints", f"node_{node_id}")
    manifest_path = os.path.join(checkpoint_dir, "manifest.json")
    if os.path.exists(manifest_path):
```

This scans every run directory on disk to find the latest checkpoint for a node. With thousands of runs, this is O(N) filesystem operations on every partial execution boundary.

---

### 5.4 — `list_runs()` Reads All `meta.json` Files on Every Request
**File:** `app/api/routers/runs.py`, `list_runs()`

Every call to `GET /api/v1/runs` reads every `meta.json` file in the runs directory. With thousands of runs, this is slow and unbounded. There is no pagination, no index, and no caching.

---

### 5.5 — `ParallelExecutor` Creates a New `ThreadPoolExecutor` Per Wave
**File:** `app/core/executor.py`, `run_wave()`

The comment says "One thread pool shared across all nodes in this wave (P-15 fix)" and uses a context manager. This is correct within a wave, but a new pool is created for every wave. For pipelines with many waves, this means repeated pool creation/teardown overhead. A single pool for the entire pipeline run would be more efficient.

---

## 6. Scalability Limitations

### 6.1 — In-Memory Active Run Registry Is Not Distributed
**File:** `app/core/run_manager.py`, `_ACTIVE_RUNS`

```python
_ACTIVE_RUNS: dict[str, "RunManager"] = {}
```

The active run registry is a process-local dict. In a multi-worker deployment (e.g., `uvicorn --workers 4`), pause/resume/cancel requests routed to a different worker than the one running the pipeline will return 404 ("run not active"). The steering docs acknowledge this for `run-async` but the problem extends to all run control operations.

---

### 6.2 — `IngestionService` Job Store Is Process-Local
**File:** `app/core/ingestion.py`

Same issue as 6.1 — `_jobs` is a module-level dict. In a multi-worker deployment, a job started on worker 1 cannot be streamed from worker 2.

---

### 6.3 — No Backpressure on the Streaming Queue
**File:** `app/api/routers/pipelines.py`, `run_pipeline_stream()`

```python
queue: Queue = Queue()   # unbounded
```

The streaming endpoint uses an unbounded `Queue`. If the client reads slowly (or disconnects), the pipeline thread keeps pushing events into the queue indefinitely. For long pipelines with many log events, this can exhaust memory.

**Fix:** Use `Queue(maxsize=N)` with a timeout on `put()`, or drop events when the queue is full.

---

### 6.4 — `ArtifactStore` Has No Eviction or Size Limit
**File:** `app/core/artifact_store.py`

Artifacts are written to disk and indexed forever. There is no TTL, no size limit, and no eviction policy. The `system/cleanup` endpoint only deletes run directories, not the artifact store. Long-running deployments will accumulate unbounded disk usage.

---

## 7. Bug Reports

### 7.1 — `Pipeline.validate()` Always Returns an Error (Confirmed Bug)
As described in §3.3 — `validate_pipeline(pipeline_cfg)` is called without the required `registry` argument, raising `TypeError` on every call.

---

### 7.2 — `NodeExecutor.on_start` / `on_end` / `on_error` Fire Twice Per Event
As described in §4.9 — both `Node.on_start()` (which calls the observer internally) and `NodeExecutor.execute()` (which calls the observer directly) fire for every lifecycle event.

---

### 7.3 — `run_id` Mismatch Between RunManager and NodeExecutor
As described in §3.1 — observer events reference a different `run_id` than the one persisted to disk.

---

### 7.4 — `_write_checkpoint` Silently Drops Multi-Port Outputs
As described in §4.8 — only the first list-valued port is checkpointed; resume will re-execute nodes that produced data on other ports.

---

### 7.5 — `document_processor` Plugin Directory Is Empty
**File:** `PluginPackage/Audio/document_processor/`

The directory exists but contains no files. If `AutoDiscovery` scans it, it will find nothing and silently skip it. If it is referenced in any pipeline template, execution will fail with `NodeNotFoundError`. This is likely an incomplete implementation.

---

### 7.6 — `audio_exporter` Plugin Has No `__init__.py`
**File:** `PluginPackage/Audio/audio_exporter/`

The directory contains `nodes.py` and `plugin.toml` but no `__init__.py`. This is inconsistent with all other plugins. While `PluginLoader` uses `spec_from_file_location` (not package imports) so this may not break loading, it is inconsistent and will cause issues if any code tries to import the plugin as a package.

---

### 7.7 — `MCP Server` Uses Deprecated `asyncio.get_event_loop()`
**File:** `app/mcp/server.py`, `handle_call_tool()`

```python
result = await asyncio.get_event_loop().run_in_executor(
    None, lambda: handler(arguments)
)
```

`asyncio.get_event_loop()` is deprecated in Python 3.10+ and raises a `DeprecationWarning` when called from a coroutine without a running loop. The correct call is `asyncio.get_running_loop()`.

---

### 7.8 — `WebhookService._config_cache` Is Not Initialized in `__init__`
**File:** `app/core/webhook.py`, `notify()`

```python
if not hasattr(self, "_config_cache") or self._config_cache is None:
    self._config_cache = self.load()
```

The cache is initialized lazily via `hasattr`. If `save()` is called before `notify()`, it sets `self._config_cache = None` (invalidation). But if `notify()` is called on a fresh instance, `hasattr` returns `False` and the cache is populated. This works, but the pattern is fragile — `_config_cache` should be initialized to `None` in `__init__` (which `WebhookService` doesn't define).

---

### 7.9 — `setup.py` Uses Open Version Ranges; `requirements.txt` Uses Exact Pins
The `requirements.txt` pins exact versions (correct for reproducibility), but `setup.py` uses open ranges (`fastapi>=0.100.0`, `numpy>=1.24.0`). When the package is installed as a library, pip will resolve the open ranges and may install incompatible versions. The two files are not kept in sync.

---

## 8. Summary Table

| # | Severity | Category | File | Issue |
|---|---|---|---|---|
| 2.1 | High | Security | `mcp/auth.py`, `api/main.py` | Token read at import time — bypassed by late env injection |
| 2.3 | High | Security | `core/webhook.py` | SSRF — no private IP blocking on webhook URLs |
| 2.4 | High | Security | `core/ingestion.py` | No download size limit — memory exhaustion DoS |
| 2.5 | High | Security | `api/routers/plugins.py` | Plugin install = arbitrary code execution |
| 3.1 | High | Bug | `core/pipeline.py` | Dual `run_id` — observer events reference wrong ID |
| 3.2 | High | Bug | `core/pipeline.py` | `run_pipeline_ir_async` defined twice — first definition is dead code |
| 3.3 | High | Bug | `core/sdk.py` | `Pipeline.validate()` always raises TypeError — completely broken |
| 7.2 | High | Bug | `core/pipeline.py` | Observer lifecycle events fire twice per node |
| 3.5 | Medium | Performance | `core/artifact_store.py` | Serialization inside global lock — parallel execution bottleneck |
| 3.7 | Medium | Bug | `api/routers/pipelines.py` | `TEMPLATES_DIR` hardcoded relative path |
| 3.8 | Medium | Bug | `api/routers/system.py` | Workspace paths hardcoded relative — cleanup silently fails |
| 4.8 | Medium | Bug | `core/pipeline.py` | Checkpoint only saves first list port — resume re-executes completed nodes |
| 5.1 | Medium | Performance | `core/pipeline.py` | Graph hash computed twice per run |
| 5.3 | Medium | Performance | `core/run_manager.py` | `find_latest_checkpoint` scans all run dirs — O(N) |
| 5.4 | Medium | Performance | `api/routers/runs.py` | `list_runs` reads all meta.json files — no pagination |
| 6.1 | Medium | Scalability | `core/run_manager.py` | Active run registry is process-local — multi-worker broken |
| 6.3 | Medium | Scalability | `api/routers/pipelines.py` | Unbounded streaming queue — memory leak on slow clients |
| 2.2 | Low | Security | `api/main.py` | CORS `allow_headers=["*"]` with credentials |
| 2.6 | Low | Security | `api/routers/runs.py` | `_run_dir()` validation weaker than `_safe_child()` |
| 4.1 | Low | Bug | `core/pipeline.py` | `on_error` called twice on final retry failure |
| 4.5 | Low | Quality | `audio_classifier/nodes.py` | Input port `data_type=list` — type safety bypassed |
| 4.6 | Low | Quality | `trainer/nodes.py` | `data_type=object` — type safety bypassed |
| 7.5 | Low | Bug | `PluginPackage/Audio/document_processor/` | Empty plugin directory |
| 7.7 | Low | Bug | `app/mcp/server.py` | Deprecated `get_event_loop()` in coroutine |
| 7.9 | Low | Quality | `setup.py` / `requirements.txt` | Open ranges in setup.py vs pinned in requirements.txt |