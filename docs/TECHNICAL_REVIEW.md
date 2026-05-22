# Graphyn Pipeline Engine — Technical Review

> **Reviewer:** Principal Software Architect  
> **Date:** 2026-05-22  
> **Codebase root:** `/home/meritech/Desktop/newAudio3`  
> **Review basis:** Direct source-code inspection of all key modules.  
> **Prior context:** `docs/PLATFORM_HANDOFF.md`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Verification of Completed Work](#2-verification-of-completed-work)
3. [Remaining Issues — Security](#3-remaining-issues--security)
4. [Remaining Issues — Architecture](#4-remaining-issues--architecture)
5. [Remaining Issues — Bugs](#5-remaining-issues--bugs)
   - [5b. Remaining Issues — Scalability](#5b-remaining-issues--scalability)
6. [New Issues Discovered](#6-new-issues-discovered)
7. [Resolved Issues](#7-resolved-issues)
8. [Prioritized Next Actions](#8-prioritized-next-actions)
9. [Architectural Assessment](#9-architectural-assessment)

---

## 1. Executive Summary

The completed work is **largely correct and well-executed**. The module splits
are clean, the shims are minimal, and the domain separation is complete with no
shim files left behind. No regressions were introduced.

However, **eight security issues remain open** (three new ones discovered in
this review), and **eleven bugs** plus **nine architectural issues** are tracked.
The platform is **not production-safe** until the security items in Section 3
are closed. Three new issues were also discovered that were not in the original
review.

---

## 2. Verification of Completed Work

### 2.1 Phase 2 Bug Fixes

All five critical bugs are confirmed fixed by direct source inspection.

| Bug | File | Evidence |
|---|---|---|
| Duplicate `run_pipeline_ir_async` | `orchestrator.py` | Exactly one definition exists |
| Dual `run_id` | `orchestrator.py` line 113 | `run_id = run.run_id` — no local UUID generation |
| `ResumeError` circular import | `nodes/errors.py` line 19 | Top-level class, no deferred imports anywhere |
| `_infer_artifact_type` in wrong layer | `artifact_store.py` | Imported cleanly by `orchestrator.py` and `executor.py` |
| `Pipeline.validate()` broken | `sdk.py` | No callers raise `TypeError` on registry argument |

### 2.2 pipeline.py Split

`pipeline.py` is a pure re-export shim — 80 lines, zero logic. All five real
modules have correct single responsibilities:

| Module | Responsibility |
|---|---|
| `app/core/planner.py` | `PipelineGraph`, topo sort, wave computation, `_ir_to_pipeline_config` |
| `app/core/node_executor.py` | `NodeExecutor` — lifecycle, retry, streaming |
| `app/core/checkpoint.py` | `_write_checkpoint`, `_load_checkpoint_outputs` |
| `app/core/orchestrator.py` | `run_pipeline_ir_async`, `run_pipeline_ir`, `_resolve_capability` |
| `app/core/pipeline.py` | Re-export shim only — backward compat |

No internal cross-shim dependencies were found. All internal imports point
directly to the real modules.

### 2.3 run_manager.py Split

`run_manager.py` is a pure re-export shim — 20 lines, zero logic. The two real
modules are clean:

| Module | Responsibility |
|---|---|
| `app/core/run_journal.py` | `RunManager` — filesystem persistence, pause/cancel state, resume state, artifact facade |
| `app/core/run_control.py` | `_ACTIVE_RUNS` registry, `register/get/deregister_active_run` |

`run_control.py` correctly documents the process-local limitation and the Redis
migration path in its module docstring.

### 2.4 Hardcoded Path Fixes

`app/api/routers/system.py` and `app/api/routers/pipelines.py` are both fixed.
`system.py` uses `runs_dir()` and `cache_dir()` from `config.py`. `pipelines.py`
uses a `_templates_dir()` function that calls `project_dir()`. **One instance
was missed** — see NEW-1 in Section 6.

### 2.5 Domain Separation

Complete and correct. `app/domain/` contains all three services:

```
app/domain/
├── __init__.py
├── ingestion.py        (moved from app/core/ingestion.py)
├── project_manager.py  (moved from app/core/project_manager.py)
└── quality_checker.py  (moved from app/core/quality_checker.py)
```

No `app/core/ingestion.py`, `app/core/project_manager.py`, or
`app/core/quality_checker.py` files remain. No shims were left behind — this
is the correct approach. All callers (`routers/ingest.py`, `routers/projects.py`,
`routers/system.py`, all unit tests) import from `app.domain` directly.

The graph hash double-computation was also fixed: `orchestrator.py` uses
`run._graph_hash` (set by `save_graph_ir()`) rather than recomputing it.

---

## 3. Remaining Issues — Security

> ⚠️ **Fix all of these before any production deployment or external exposure.**

### SEC-1 — Auth token read at import time (`app/mcp/auth.py` line 12)

```python
# CURRENT — wrong
_TOKEN = _api_token()   # captured once at module import

def check_auth(arguments):
    if not _TOKEN:       # always uses the import-time value
        return None
```

**Impact:** If `GRAPHYN_API_TOKEN` is injected after process start (secrets
manager, container orchestrator, test harness), the server runs without
authentication for the lifetime of the process. Rotating the token requires a
full process restart.

**Fix:**
```python
def check_auth(arguments):
    token = _api_token()   # read on every call
    if not token:
        return None
    provided = (arguments or {}).get("_meta", {}).get("auth_token", "")
    if provided != token:
        return {"error": True, "error_type": "unauthorized", ...}
    return None
```

### SEC-2 — Auth token read at import time (`app/api/main.py` line 35)

```python
# CURRENT — wrong
_API_TOKEN = api_token()   # module-level

def _auth_dep(credentials=Depends(_bearer)):
    if not _API_TOKEN:     # frozen at import
        return
```

**Impact:** Same as SEC-1. Token rotation requires server restart.

**Fix:** Call `api_token()` inside `_auth_dep()` on every request, or cache
with a short TTL using `functools.lru_cache`.

### SEC-3 — Webhook SSRF (`app/core/webhook.py`)

`save()` validates scheme (`http`/`https`) and netloc, which prevents
`file://` and bare paths. But `_send()` makes the actual HTTP request with no
private IP blocking. An attacker who can call `PUT /api/v1/system/webhooks`
can set `url = "http://169.254.169.254/latest/meta-data/"` (AWS IMDS) or
`http://10.0.0.1/admin`.

**Impact:** Full SSRF — internal network scanning, cloud metadata exfiltration.

**Fix:** In `save()`, resolve the hostname and reject RFC 1918, loopback, and
link-local ranges before writing the config:
```python
import ipaddress, socket
host = parsed.hostname
ip = ipaddress.ip_address(socket.gethostbyname(host))
if ip.is_private or ip.is_loopback or ip.is_link_local:
    raise ValueError(f"Webhook URL resolves to a private address: {ip}")
```

### SEC-4 — Ingest URL: no download size limit (`app/domain/ingestion.py` ~line 145)

```python
# CURRENT — wrong
response = client.get(url)
dest_path.write_bytes(response.content)   # buffers entire body in memory
```

**Impact:** A 10 GB response exhausts server memory. Denial of service via a
single ingest request.

**Fix:** Use `httpx` streaming with a max-bytes counter:
```python
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB

with client.stream("GET", url) as r:
    r.raise_for_status()
    total = 0
    with open(dest_path, "wb") as f:
        for chunk in r.iter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                dest_path.unlink(missing_ok=True)
                raise ValueError("Download exceeds size limit")
            f.write(chunk)
```

### SEC-5 — CORS `allow_headers=["*"]` with `allow_credentials=True` (`app/api/main.py` lines 56–65)



```python
# CURRENT — wrong
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_headers=["*"],    # invalid combination per CORS spec
)
```

**Impact:** The [CORS specification](https://fetch.spec.whatwg.org/#cors-protocol-and-credentials)
forbids `allow_headers=*` when `allow_credentials=True`. Browsers reject such
responses. The API is effectively broken for credentialed cross-origin requests
from any browser.

**Fix:** Enumerate specific headers:
```python
allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
```

### SEC-6 — Plugin install accepts arbitrary remote code (`app/api/routers/plugins.py`)

`POST /api/v1/plugins/install` accepts a `source` string passed directly to
`PluginInstaller.resolve()`, which fetches and executes code from `git+`,
`http://`, or `https://` URLs. There is no allowlist, no signature verification,
and no sandboxing. Any authenticated user can install a plugin that registers a
malicious `Node` subclass running arbitrary Python when `process()` is called.

**Impact:** Remote code execution on the server.

**Note:** This is an inherent risk of any plugin system. The minimum mitigations
are: require auth for install endpoints (already done when token is set), add
plugin checksum/signature verification, and document clearly that the install
endpoint must never be exposed publicly.

### SEC-7 — `_run_dir()` validation weaker than `_safe_child()` (`app/api/routers/runs.py` line 18)

```python
if not run_id.replace("-", "").isalnum():
    raise HTTPException(status_code=400, detail="Invalid run_id")
path = _get_runs_root() / run_id   # no resolve() + is_relative_to() check
```

The validation strips hyphens before `isalnum()`, so `--` passes (empty string
after stripping). More importantly, the path is constructed without a `resolve()`
+ `is_relative_to()` check — inconsistent with the `_safe_child()` guard used
in `data.py`.

**Impact:** Low risk currently, but the pattern is weaker than the established
`_safe_child()` convention.

**Fix:** Apply the same `_safe_child()` pattern: `resolve()` the final path and
assert it is relative to the runs root.

### SEC-8 — Condition evaluator: no AST depth limit (`app/core/conditions.py`)

The condition evaluator uses `eval()` with a compiled AST after whitelist
validation. The whitelist correctly restricts node types and `__builtins__`.
However, there is no depth limit on the AST. A deeply nested expression like
`len(len(len(len(...))))` passes the whitelist (all `len` calls) but fails at
runtime with a `TypeError`, producing confusing error messages rather than a
clean `ConditionEvaluationError`.

**Impact:** Not exploitable, but produces misleading errors and could be used
for minor DoS via slow AST traversal.

**Fix:** Add a max-depth check during AST validation (e.g., reject trees deeper
than 10 levels).

---

## 4. Remaining Issues — Architecture

### ARCH-1 — Domain leak: `pipeline_cache.py` imports `AudioSample`

`app/core/pipeline_cache.py` line 9:
```python
from app.models.audio_sample import AudioSample
```

The `load()` method constructs `AudioSample` objects directly. The platform
cache must not know about audio. The `save()` method uses duck-typing
(`hasattr(first, "path") and hasattr(first, "sample_rate")`) which is better,
but `load()` still hard-codes `AudioSample`.

**Fix:** Pluggable serializer/deserializer registry. The domain registers its
handler at startup; the platform calls it by type string.

### ARCH-2 — Domain leak: `artifact_store.py` contains WAV serialization

`_serialize_audio_samples()` writes WAV files using `soundfile`. `_infer_artifact_type()`
contains audio-specific duck-typing. Both are audio-domain knowledge inside
platform infrastructure.

**Fix:** Same serializer registry pattern as ARCH-1.

### ARCH-3 — `checkpoint.py` is entirely audio-domain

`_write_checkpoint()` imports `soundfile` and `numpy`, writes WAV files, and
reads `sample.data`, `sample.sample_rate`, `sample.label`. `_load_checkpoint_outputs()`
imports `AudioSample` directly. This module is not platform infrastructure — it
is an audio-domain checkpoint serializer living in the wrong layer.

**Fix:** Replace with the pluggable serializer pattern. The platform writes
opaque bytes; the domain provides the serializer/deserializer.

### ARCH-4 — `_write_checkpoint` only saves first list port

`app/core/checkpoint.py` lines 44–47:
```python
result = None
for v in outputs.values():
    if isinstance(v, list):
        result = v
        break   # stops at first list port — all others are lost
```

`pipeline_cache.py` `save()` was correctly updated to use `port_<name>/`
subdirectories for all ports, but `checkpoint.py` was not updated to match.
Multi-port nodes that produce lists on more than one port will silently drop
all but the first port on resume.

**Fix:** Iterate all ports, write each to its own subdirectory (same pattern
as `pipeline_cache.py`).

### ARCH-5 — `PipelineNode._ir_node` always uses `_0` suffix

`app/core/sdk.py` — `PipelineNode._ir_node` always appends `_0` regardless of
the node's position in the pipeline. This produces duplicate node IDs when a
pipeline contains more than one node of the same type.

**Fix:** Use `to_ir_node(node_index)` with the actual position index.

### ARCH-6 — `ArtifactStore` serialization runs inside global lock (`app/core/artifact_store.py`)

The entire `register()` method — including `_serialize_data()` which writes WAV
files to disk — runs under `self._lock`. For large audio datasets, serialization
can take seconds, blocking all concurrent artifact registrations for the entire
duration. In parallel wave execution, multiple nodes complete simultaneously and
all try to register artifacts under the same lock.

**Impact:** Parallel execution throughput is bottlenecked by sequential artifact
serialization. The lock that should protect only the index read-modify-write is
held for the entire disk write.

**Fix:** Serialize data outside the lock; hold the lock only for the index
read-modify-write:
```python
# Serialize first (no lock needed)
self._serialize_data(artifact_type, data, data_dir)
# Then lock only for index update
with self._lock:
    index = self._load_index()
    ...
    self._save_index(index)
```

### ARCH-7 — `ArtifactStore` has no eviction or size limit (`app/core/artifact_store.py`)

Artifacts are written to disk and indexed forever. There is no TTL, no size
limit, and no eviction policy. The `POST /api/v1/system/cleanup` endpoint only
deletes run directories, not the artifact store. Long-running deployments will
accumulate unbounded disk usage.

**Fix:** Add a `cleanup(older_than_days)` method to `ArtifactStore` and call it
from the system cleanup endpoint alongside run directory cleanup.

### ARCH-8 — `PipelineCache.input_hash()` `repr()` fallback is not stable across restarts (`app/core/pipeline_cache.py`)

The `input_hash()` method falls back to `repr()` for types it cannot serialize.
`repr()` includes object memory addresses for custom objects, which change on
every process restart. Cache keys for nodes that reach this fallback are
effectively random across restarts, making the cache useless for them.

**Impact:** Silent cache misses for multi-port nodes with non-serializable inputs.
The warning log is correct but the fallback is misleading — it implies caching
works when it does not.

**Fix:** Return a sentinel value (e.g., `""`) that forces `cacheable=False`
behaviour, or raise so the node is correctly marked non-cacheable.

### ARCH-9 — `PipelineCache.has()` TOCTOU not fixed at call sites

`app/core/pipeline_cache.py` `has()` docstring explicitly warns:
> TOCTOU: the entry may be deleted between has() and load(). Always treat
> load() returning None as a cache miss.

But `orchestrator.py` and `executor.py` still call `cache.has()` followed by
`cache.load()` as two separate operations. The fix is described in the docstring
but not applied at the call sites.

**Fix:** Remove `cache.has()` calls; call `cache.load()` directly and treat
`None` as a miss.

---

## 5. Remaining Issues — Bugs

### BUG-1 — Observer double-fire per node (confirmed present)

`app/core/node_executor.py` calls `observer.on_node_start/end/error` explicitly
(lines ~85, ~103). `app/core/nodes/base.py` `on_start()` and `on_end()` also
call `observer.on_node_start/end` (lines ~175, ~190). Since `NodeExecutor.execute()`
calls `node.on_start()` which calls the observer, and then also calls
`observer.on_node_start()` directly, every observer event fires **twice** per
node execution.

**Impact:** Duplicate telemetry in any observability system. Metrics, traces,
and dashboards will show double the actual node count and duration.

**Fix:** Remove the direct `observer.on_node_start/end/error` calls from
`NodeExecutor.execute()`. The lifecycle hooks in `base.py` already handle
observer notification. The executor's direct calls are redundant.

Note: `execute_stream()` only calls `node.on_start/end` via the base class —
it does not have the double-fire problem. Verify this remains true after the fix.

### BUG-2 — `asyncio.get_event_loop()` deprecated (`app/mcp/server.py` line 87)

```python
# CURRENT — deprecated in Python 3.10+
result = await asyncio.get_event_loop().run_in_executor(
    None, lambda: handler(arguments)
)
```

`asyncio.get_event_loop()` raises `DeprecationWarning` in async contexts in
Python 3.10+ and will raise `RuntimeError` in a future version.

**Fix:**
```python
result = await asyncio.get_running_loop().run_in_executor(
    None, lambda: handler(arguments)
)
```

### BUG-3 — `WebhookService` missing `__init__` (`app/core/webhook.py`)

There is no `__init__` method. `_config_cache` is never initialized on the
instance. `notify()` uses `hasattr(self, "_config_cache")` as a guard, which
works but means the cache is never populated — `self.load()` is called on
every `notify()` invocation (a disk read per event).

**Fix:** Add `__init__`:
```python
def __init__(self) -> None:
    self._config_cache: dict | None = None
```

### BUG-4 — `find_latest_checkpoint()` is O(N) (`app/core/run_journal.py`)

`find_latest_checkpoint()` scans all run directories on every call, reading
`meta.json` from each. For a system with thousands of runs this becomes a
blocking bottleneck on every partial-execution input assembly.

**Fix:** Maintain a secondary index (`checkpoints/by_node/{node_id}.json`)
updated by `_write_checkpoint()`, or accept the O(N) cost and add pagination
to `list_runs()` to bound N.

### BUG-5 — Unbounded streaming queue (`app/api/routers/pipelines.py` line ~100)

```python
queue: Queue = Queue()   # unbounded
```

A slow HTTP client causes the server to buffer unlimited log events in memory.

**Fix:**
```python
queue: Queue = Queue(maxsize=512)
```
Handle `queue.Full` in the producer by dropping or blocking with a timeout.

### BUG-6 — `on_error` called twice on final retry failure (`app/core/node_executor.py`)

In `NodeExecutor.execute()`, `node.on_error(exc)` is called inside the retry
loop on each failed attempt. After all attempts are exhausted, `node.on_error()`
is called *again* outside the loop before re-raising. The final exception
triggers two `on_error` calls — one from the last loop iteration and one from
the post-loop block.

```python
# Inside loop (last attempt):
node.on_error(exc)
if observer: observer.on_node_error(...)
last_exc = exc
continue

# After loop — duplicate:
node.on_error(last_exc)
if observer: observer.on_node_error(...)
```

**Impact:** Observer implementations that count errors will see an inflated
count on any node that exhausts its retry budget.

**Fix:** Remove the post-loop `on_error` call; the loop already called it on
the last attempt.

### BUG-7 — `list_runs()` reads all `meta.json` files on every request (`app/api/routers/runs.py`)

`GET /api/v1/runs` reads every `meta.json` file in the runs directory on every
call. There is no pagination, no index, and no caching. With thousands of runs
this is slow and unbounded.

**Fix:** Add `?limit=N&offset=M` pagination parameters and sort by directory
mtime before reading `meta.json` files, so only the requested page is read.

### BUG-8 — `_SISO` detection is fragile (`app/core/nodes/base.py`, `_maybe_wrap_siso()`)

SISO detection relies on the second parameter name not being `"inputs"`. A
multi-port node that names its parameter `process(self, data)` will be
incorrectly wrapped as SISO and receive a raw value instead of a dict. A SISO
node that names its parameter `process(self, inputs)` will be treated as
multi-port and receive a dict instead of the raw value. The convention is
undocumented at the call site.

**Impact:** Silent incorrect behaviour for any node that deviates from the
naming convention.

**Fix:** Document the convention explicitly in the `Node` base class docstring
and add a class-level `_siso: ClassVar[bool] = False` flag that subclasses can
set explicitly, removing the fragile parameter-name inference.

### BUG-9 — `SpeechEnhancerNode._resolve_backend()` called twice per process (`PluginPackage/Audio/speech_enhancer/nodes.py`)

`setup()` sets `self._resolved_backend`. But `process()` falls back to calling
`_resolve_backend()` again if `_resolved_backend` is falsy:

```python
backend = getattr(self, "_resolved_backend", None) or self._resolve_backend()
```

`_resolve_backend()` imports and probes packages. In unit tests that call
`process()` directly without calling `setup()` first, this triggers an
unnecessary package probe on every call.

**Fix:** Raise `RuntimeError("setup() must be called before process()")` if
`_resolved_backend` is not set, rather than silently re-probing.

### BUG-10 — `IngestionService` job store is process-local (`app/domain/ingestion.py`)

`_jobs` is a module-level dict. In a multi-worker deployment (e.g.,
`uvicorn --workers 4`), a job started on worker 1 cannot be streamed from
worker 2 — the `GET /api/v1/ingest/url/{job_id}/stream` request will return
404 if routed to a different worker.

**Impact:** Ingest job streaming is broken in any multi-worker deployment.

**Fix:** Same pattern as `_ACTIVE_RUNS` — document the limitation now, replace
with a Redis-backed store when multi-worker support is needed.

### BUG-11 — `ArtifactStore.get_versions()` performs a full directory scan (`app/core/artifact_store.py`)

```python
def get_versions(self, artifact_name: str) -> list[ArtifactRecord]:
    return [r for r in self.list() if r.name == artifact_name]
```

`self.list()` with no filters triggers the slow-path full directory scan —
O(N) disk reads where N = total artifacts. The docstring acknowledges this but
there is no `by_name/` secondary index.

**Fix:** Add a `by_name/` secondary index (same pattern as `by_run/`) updated
in `register()`.

---

## 5b. Remaining Issues — Scalability

These do not cause failures in single-worker deployments but will break or
degrade in multi-worker or high-volume production environments.

### SCALE-1 — Active run registry is process-local (`app/core/run_control.py`)

`_ACTIVE_RUNS` is a process-local dict. In a multi-worker deployment
(`uvicorn --workers 4`), pause/resume/cancel requests routed to a different
worker than the one running the pipeline will return 404 ("run not active").
The module docstring correctly documents this limitation and the Redis migration
path.

**Fix:** Replace `_ACTIVE_RUNS` with a Redis-backed store when multi-worker
support is required. The split into `run_control.py` was done specifically to
make this migration easy.

### SCALE-2 — `IngestionService` job store is process-local

See BUG-10. Same root cause as SCALE-1.

### SCALE-3 — `ParallelExecutor` creates a new `ThreadPoolExecutor` per wave (`app/core/executor.py`)

A new `ThreadPoolExecutor` is created and destroyed for every wave. For
pipelines with many waves, this means repeated pool creation/teardown overhead.
The pool is correctly shared across nodes within a wave (P-15 fix), but not
across waves.

**Fix:** Create one pool for the entire pipeline run and pass it through
`run_wave()`, or use a module-level shared pool with a bounded size.

---

## 6. New Issues Discovered

These were not in the original review or the handoff document.

### NEW-1 — Hardcoded `Path("workspace")` in `app/api/routers/data.py` lines 15–17

```python
# CURRENT — wrong
WORKSPACE_ROOT = Path("workspace").resolve()
INPUT_ROOT  = (WORKSPACE_ROOT / "datasets" / "input").resolve()
OUTPUT_ROOT = (WORKSPACE_ROOT / "datasets" / "output").resolve()
```

This is the same class of bug that was fixed in `system.py` and `pipelines.py`,
but `data.py` was missed in the sweep. It breaks when `GRAPHYN_PROJECT_DIR` is
set to anything other than `"workspace"`.

**Fix:**
```python
from app.core.config import datasets_input_dir as _input_dir
from app.core.config import datasets_output_dir as _output_dir

def _input_root() -> Path:
    return _input_dir()

def _output_root() -> Path:
    return _output_dir()
```
Replace all uses of `INPUT_ROOT` and `OUTPUT_ROOT` with `_input_root()` and
`_output_root()` calls (same pattern as `_templates_dir()` in `pipelines.py`).

### NEW-2 — Broken `_WORKSPACE` sentinel in `RunManager.__init__` (`app/core/run_journal.py` lines ~55–60)

```python
# CURRENT — confusing and effectively broken
if base_dir is None:
    import app.core.run_journal as _self_module
    _original_default = "workspace"
    if _self_module._WORKSPACE != _original_default:
        base_dir = str(Path(_self_module._WORKSPACE) / "runs")
    else:
        base_dir = str(_project_dir() / "runs")
```

`_WORKSPACE` is set to `str(_project_dir())` at module load time — an absolute
path. The condition `_WORKSPACE != "workspace"` is therefore almost always
`True`, meaning the `else` branch (which correctly uses `_project_dir()`) is
almost never reached. Both branches resolve to the same path, so there is no
functional bug today, but the logic is misleading and will confuse anyone who
tries to understand or modify it.

**Fix:** Remove the sentinel entirely:
```python
if base_dir is None:
    base_dir = str(_project_dir() / "runs")
```

### NEW-3 — `execute_stream()` observer coverage gap (`app/core/node_executor.py`)

`NodeExecutor.execute()` calls the observer directly (the double-fire bug).
`execute_stream()` does not — it relies solely on `node.on_start/on_end` from
the base class. This means:

- Before BUG-1 fix: `execute()` fires observer twice; `execute_stream()` fires once.
- After BUG-1 fix (removing direct calls from `execute()`): both fire once — correct.

This is not a bug today, but it must be tracked during the BUG-1 fix to ensure
the fix does not accidentally leave streaming nodes with zero observer events.

---

## 7. Resolved Issues

All items listed here were confirmed resolved by direct source inspection.

| Issue | Resolution |
|---|---|
| Duplicate `run_pipeline_ir_async` definition | Deleted — `orchestrator.py` has exactly one |
| Dual `run_id` (local UUID vs `run.run_id`) | Unified — `orchestrator.py` uses `run.run_id` |
| `ResumeError` circular import | Moved to `nodes/errors.py`; top-level import everywhere |
| `_infer_artifact_type` in wrong layer | Moved to `artifact_store.py`; imported by orchestrator and executor |
| `Pipeline.validate()` missing registry arg | Fixed in `sdk.py` |
| `pipeline.py` god module (1,457 lines) | Split into 5 focused modules; shim is clean |
| `run_manager.py` mixed responsibilities | Split into `run_journal.py` + `run_control.py`; shim is clean |
| Hardcoded `Path("workspace")` in `system.py` | Fixed — uses `runs_dir()`, `cache_dir()` |
| Hardcoded `TEMPLATES_DIR` in `pipelines.py` | Fixed — uses `_templates_dir()` function |
| Domain services in `app/core/` | Moved to `app/domain/`; all callers updated; no shims |
| Graph hash computed twice per run | Fixed — `orchestrator.py` uses `run._graph_hash` |
| `app/core/ingestion.py` still importable from old path | Deleted; no shim; callers updated |
| `app/core/project_manager.py` still importable from old path | Deleted; no shim; callers updated |
| `app/core/quality_checker.py` still importable from old path | Deleted; no shim; callers updated |

---

## 8. Prioritized Next Actions

### Tier 1 — Security (block production deployment)

These are one-to-five line fixes. Do them in a single commit before any
external exposure.

1. **SEC-1 + SEC-2** — Move `_TOKEN = _api_token()` inside `check_auth()` and
   `_auth_dep()`. Two files, two lines each.
2. **SEC-5** — Replace `allow_headers=["*"]` with an explicit list in
   `app/api/main.py`.
3. **SEC-3** — Add private IP blocking to `WebhookService.save()`.
4. **SEC-4** — Replace `response.content` with streaming download + byte
   counter in `app/domain/ingestion.py`.

### Tier 2 — Correctness (fix before serious use)

5. **BUG-1** — Remove direct `observer.on_node_start/end/error` calls from
   `NodeExecutor.execute()`. Verify `execute_stream()` is unaffected (NEW-3).
6. **BUG-2** — `asyncio.get_event_loop()` → `asyncio.get_running_loop()` in
   `server.py` line 87.
7. **BUG-3** — Add `__init__` to `WebhookService`.
8. **NEW-1** — Fix hardcoded `Path("workspace")` in `data.py`.
9. **NEW-2** — Simplify `RunManager.__init__` base_dir logic.
10. **ARCH-4** — Fix `_write_checkpoint` to iterate all ports (match the
    multi-port fix already done in `pipeline_cache.py`).

### Tier 3 — Architecture (platform build plan, Step 1 remaining)

11. **ARCH-1 + ARCH-2 + ARCH-3** — Implement pluggable serializer registry.
    `pipeline_cache.py`, `artifact_store.py`, and `checkpoint.py` all need to
    stop knowing about WAV/AudioSample. The domain registers its serializer at
    startup; the platform calls it by type string. This is the largest remaining
    architectural item and the prerequisite for package extraction.
12. **Step 5 of the build plan** — Write scoped `.kiro/steering/` files for
    each bounded context.

### Tier 4 — Code quality (fix when touching the file)

- **ARCH-5** — `PipelineNode._ir_node` always `_0` suffix (`sdk.py`)
- **BUG-4** — `find_latest_checkpoint()` O(N) scan
- **BUG-5** — Unbounded streaming queue in `pipelines.py`
- **BUG-7** — `list_runs()` no pagination (`runs.py`)
- **BUG-8** — SISO detection fragile (`nodes/base.py`)
- **BUG-9** — `SpeechEnhancerNode._resolve_backend()` called twice
- **BUG-11** — `ArtifactStore.get_versions()` full scan
- **ARCH-7** — `ArtifactStore` no eviction/size limit
- **ARCH-8** — `PipelineCache.input_hash()` `repr()` fallback not stable
- **ARCH-9** — `PipelineCache.has()` TOCTOU not fixed at call sites
- **SEC-7** — `_run_dir()` validation weaker than `_safe_child()`
- **SEC-8** — Condition evaluator no AST depth limit
- `AudioClassifierNode` input port `data_type=list` — type safety bypassed (`audio_classifier/nodes.py`)
- `TrainerNode` / `ModelBuilderNode` `data_type=object` — type safety bypassed (`trainer/nodes.py`)
- `document_processor` plugin directory is empty
- `audio_exporter` missing `__init__.py`
- `setup.py` open version ranges vs pinned `requirements.txt`

---

## 9. Architectural Assessment

### What is now clean

**Module boundaries are correct.** `orchestrator.py`, `planner.py`,
`node_executor.py`, `checkpoint.py`, `run_journal.py`, and `run_control.py`
each have a single clear reason to change. The shims (`pipeline.py`,
`run_manager.py`) are minimal and correct.

**Domain separation is complete.** `app/core/` contains zero audio, ML, or
HuggingFace knowledge — except in the three remaining domain leaks
(`pipeline_cache.py`, `artifact_store.py`, `checkpoint.py`). All three are
known and tracked.

**The control plane split anticipates the right future.** `run_control.py`
is correctly separated from `run_journal.py` with a clear comment that
`_ACTIVE_RUNS` needs to become Redis-backed for multi-worker deployments.
The split was done before it was needed, which is the right time.

**The bounded context map is accurate.** BC1 (Graph Language) and BC2 (Node
Contract) are ready for package extraction now. BC3–BC6 need the serializer
registry work (ARCH-1/2/3) to complete before extraction is safe.

### What is still problematic

**`checkpoint.py` is the most egregious remaining domain leak.** It is
entirely audio-specific code — WAV writing, `soundfile`, `numpy`, `AudioSample`
— living inside platform infrastructure. It should be the first target of the
serializer registry work.

**The observer double-fire (BUG-1) will corrupt any production observability
system.** Every node will appear to execute twice in metrics, traces, and
dashboards. This is a correctness issue, not just a code smell.

**Three security issues are straightforward one-line fixes** (SEC-1, SEC-2,
SEC-5) that should have been caught in the original review. They are not
architectural problems — they are implementation oversights that need to be
closed before any external exposure.

**`data.py` was missed in the hardcoded-path sweep (NEW-1).** The fix pattern
is identical to what was already done in `system.py` and `pipelines.py`. It
should be included in the same commit as those fixes retroactively.

### Stability classification (updated)

| Bounded Context | Module(s) | Stability | Extraction Ready |
|---|---|---|---|
| BC1: Graph Language | `app/core/ir/` | VERY STABLE | ✅ Now |
| BC2: Node Contract | `nodes/base.py`, `ports.py`, `config.py`, `retry.py` | VERY STABLE | ✅ After BC1 |
| BC3: Node Catalog | `registry.py`, `discovery.py`, `metadata.py` | EVOLVING | ❌ After ARCH-1/2/3 |
| BC4: Execution Planner | `planner.py` | STABLE | ❌ After ARCH-1/2/3 |
| BC5: Execution Runtime | `orchestrator.py`, `node_executor.py`, `executor.py` | EVOLVING | ❌ After ARCH-1/2/3 |
| BC6: Observability & Storage | `run_journal.py`, `artifact_store.py`, `provenance.py` | STABLE | ❌ After ARCH-1/2/3 |

---

*End of review. Next session should start with Tier 1 security fixes.*
