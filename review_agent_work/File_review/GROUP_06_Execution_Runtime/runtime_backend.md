# Functional Review — app/core/runtime_backend.py

**Group:** 6 — Execution Runtime  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/runtime_backend.py
FUNCTION:    get_backend
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a cached backend instance by ID; raises `KeyError` if `backend_id`
is not registered.

WHAT IT ACTUALLY DOES:
The function raises `KeyError` with a helpful message when the backend is not
found. However, `KeyError` is an unusual exception type for a "not found"
condition in an API context — callers typically expect `ValueError` or a
custom exception for invalid configuration. The docstring says "Raises:
KeyError" which is accurate, but callers that catch `ValueError` for
configuration errors will miss this.

THE BUG / RISK:
`KeyError` is semantically a dict-access error, not a "backend not configured"
error. Callers that do `except ValueError` to handle misconfiguration will
not catch this. The SDK, API, and CLI all call `get_backend()` and may not
handle `KeyError` specifically.

EVIDENCE:
```python
if backend_id not in _BACKEND_REGISTRY:
    available = sorted(_BACKEND_REGISTRY)
    raise KeyError(
        f"Unknown runtime backend '{backend_id}'. "
        f"Available backends: {available}"
    )
```

REPRODUCTION SCENARIO:
`get_backend("nonexistent")` → `KeyError`. A caller doing
`except ValueError: handle_config_error()` will not catch it.

IMPACT:
Unhandled `KeyError` propagates as an unformatted exception to the user.
Medium risk — depends on caller error handling.

FIX DIRECTION:
Raise `ValueError` instead of `KeyError`, consistent with other registry
lookups in the codebase:
```python
raise ValueError(
    f"Unknown runtime backend '{backend_id}'. "
    f"Available backends: {available}"
)
```

--------------------------------------------------------------------
FILE:        app/core/runtime_backend.py
FUNCTION:    register_backend
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a custom backend class under `backend_id`; invalidate any cached
instance so the new class is used on next `get_backend()`.

WHAT IT ACTUALLY DOES:
`_BACKEND_REGISTRY[backend_id] = backend_class` is performed outside the
`_BACKEND_INSTANCES_LOCK`. The registry write and the instance cache
invalidation are not atomic. A concurrent `get_backend()` call could:
1. Read `_BACKEND_REGISTRY[backend_id]` (old class) after the registry is
   updated but before the instance cache is invalidated.
2. Find the old instance in `_BACKEND_INSTANCES` and return it.
3. The new class is never used until the old instance is evicted.

THE BUG / RISK:
`_BACKEND_REGISTRY` is written without holding `_BACKEND_INSTANCES_LOCK`.
The registry update and cache invalidation are not atomic. A concurrent
`get_backend()` could return a stale instance of the old class.

EVIDENCE:
```python
def register_backend(backend_id, backend_class):
    ...
    _BACKEND_REGISTRY[backend_id] = backend_class   # ← outside lock
    with _BACKEND_INSTANCES_LOCK:
        _BACKEND_INSTANCES.pop(backend_id, None)    # ← inside lock
```

REPRODUCTION SCENARIO:
Thread A calls `register_backend("local_python", NewBackend)`.
Thread B calls `get_backend("local_python")` concurrently.
Thread B may read the old class from `_BACKEND_REGISTRY` and return the
old cached instance, even after `register_backend` completes.

IMPACT:
Stale backend instance returned after re-registration. Low risk in practice
(backends are rarely re-registered) but a correctness issue.

FIX DIRECTION:
Perform both the registry write and cache invalidation under the lock:
```python
with _BACKEND_INSTANCES_LOCK:
    _BACKEND_REGISTRY[backend_id] = backend_class
    _BACKEND_INSTANCES.pop(backend_id, None)
```

--------------------------------------------------------------------
FILE:        app/core/runtime_backend.py
FUNCTION:    LocalPythonBackend.execute
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute via the local `run_pipeline_ir` function; the backend instance is
stateless and may be used to execute multiple pipelines concurrently.

WHAT IT ACTUALLY DOES:
`LocalPythonBackend.execute()` calls `run_pipeline_ir()` (the synchronous
shim), which calls `asyncio.run()`. `asyncio.run()` creates a new event loop
for each call. If `execute()` is called from an async context (e.g., from
an async API handler), `run_pipeline_ir()` raises `RuntimeError: cannot be
called from an async context`. The backend's docstring says it is the backend
"used by all current interfaces" — but the API and MCP server are async and
must call `run_pipeline_ir_async()` directly, bypassing the backend entirely.

THE BUG / RISK:
`LocalPythonBackend.execute()` is unusable from async contexts. The docstring
claims it is "the backend used by all current interfaces" but async interfaces
(API, MCP) cannot use it. This means the backend abstraction is effectively
bypassed by all async callers.

EVIDENCE:
```python
def execute(self, graph, **kwargs):
    from app.core.orchestrator import run_pipeline_ir  # ← sync shim
    return run_pipeline_ir(graph, **kwargs)
    # ↑ raises RuntimeError if called from async context
```

REPRODUCTION SCENARIO:
```python
async def api_handler():
    backend = get_backend("local_python")
    result = backend.execute(graph)   # RuntimeError: running event loop detected
```

IMPACT:
`LocalPythonBackend` cannot be used from async contexts. The backend
abstraction is incomplete — async callers must bypass it.

FIX DIRECTION:
Add an `async def execute_async()` method to `RuntimeBackend` ABC, or make
`LocalPythonBackend.execute()` detect the async context and call
`run_pipeline_ir_async()` directly:
```python
def execute(self, graph, **kwargs):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # Return a coroutine for async callers
        from app.core.orchestrator import run_pipeline_ir_async
        return run_pipeline_ir_async(graph, **kwargs)
    from app.core.orchestrator import run_pipeline_ir
    return run_pipeline_ir(graph, **kwargs)
```

--------------------------------------------------------------------
FILE:        app/core/runtime_backend.py
FUNCTION:    get_backend / _BACKEND_INSTANCES
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Singleton cache: backend_id → instance. Stateless backends are safe to share
across calls.

WHAT IT ACTUALLY DOES:
`_BACKEND_INSTANCES` is a module-level dict. In test environments, tests that
call `register_backend()` or `get_backend()` will pollute the singleton cache
across test cases. There is no `reset_backends()` or `clear_instances()`
function for test teardown.

THE BUG / RISK:
Module-level singleton state leaks between test cases. A test that registers
a mock backend will affect all subsequent tests in the same process.

EVIDENCE:
```python
_BACKEND_INSTANCES: dict[str, RuntimeBackend] = {}   # module-level singleton
```

REPRODUCTION SCENARIO:
Test A registers a mock backend: `register_backend("local_python", MockBackend)`.
Test B calls `get_backend("local_python")` and gets `MockBackend` instead of
`LocalPythonBackend`.

IMPACT:
Test isolation failure. Low production impact.

FIX DIRECTION:
Add a `_reset_backend_registry()` function for test teardown, or use
dependency injection instead of a module-level singleton.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | `LocalPythonBackend.execute()` raises `RuntimeError` when called from an async context, making the backend abstraction unusable by the API and MCP server — async callers must bypass the backend entirely and call `run_pipeline_ir_async()` directly |
