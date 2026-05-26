# Functional Review — app/core/run_control.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/run_control.py
FUNCTION:    _get_redis_client
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a connected redis.Redis client, or None if redis-py is absent or
GRAPHYN_REDIS_URL is not configured. The docstring states: "The client is
created fresh on each call — callers that need connection pooling should
cache the result themselves."

WHAT IT ACTUALLY DOES:
Creates a new `redis.Redis` client on every call. `redis.Redis.from_url()`
creates a new connection pool by default. Each call to
`register_active_run`, `get_active_run`, or `deregister_active_run` creates
a new connection pool and opens a new TCP connection to Redis.

THE BUG / RISK:
`register_active_run`, `get_active_run`, and `deregister_active_run` each
call `_get_redis_client()` once. In a high-throughput system with many
concurrent runs, this creates a large number of short-lived connection pools.
Each pool holds open TCP connections until garbage collected. Under load,
this can exhaust the Redis server's connection limit (default: 10,000) and
the OS file descriptor limit.

EVIDENCE:
```python
def _get_redis_client():
    ...
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
```
Called from `register_active_run`, `get_active_run`, `deregister_active_run`
— three new connection pools per run lifecycle.

REPRODUCTION SCENARIO:
1000 concurrent runs each calling `register_active_run` → 1000 new Redis
connection pools. Each pool opens at least 1 TCP connection. Redis server
receives 1000 new connections simultaneously. If Redis max connections is
1000, subsequent connections are refused.

IMPACT:
Redis connection exhaustion under load. `register_active_run` and
`deregister_active_run` silently fall back to in-process store (the
`except Exception` catches the connection error and logs a warning). Run
control signals are not delivered to Redis, breaking multi-worker deployments.

FIX DIRECTION:
Cache the client at module level (created once on first use):
```python
_redis_client = None
_redis_client_lock = threading.Lock()

def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _redis_client_lock:
        if _redis_client is None:
            url = _redis_url()
            if not url:
                return None
            try:
                import redis
                _redis_client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
            except Exception as exc:
                log.warning(...)
                return None
    return _redis_client
```

--------------------------------------------------------------------
FILE:        app/core/run_control.py
FUNCTION:    get_active_run
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the active RunManager for run_id, or None if not active.

WHAT IT ACTUALLY DOES:
In Redis mode, when the run is active on another worker, logs a debug message
and returns `None`. The docstring (SA-RC2) documents this behavior. However,
the function signature returns `RunManager | None` — callers cannot
distinguish between "run does not exist", "run has completed", and "run is
on another worker". All three cases return `None`.

THE BUG / RISK:
API routers that call `get_active_run(run_id)` and receive `None` return
HTTP 404 "run not found". In a multi-worker deployment, a pause/resume/cancel
request for a run on another worker silently returns 404 instead of a more
informative error (e.g. 503 "run is active on another worker").

EVIDENCE:
```python
# SA-RC2: Returns None in all of these cases:
#   - The run never existed in this process
#   - The run has already completed and been deregistered
#   - The run is executing on a different worker (SCALE-1)
```

REPRODUCTION SCENARIO:
Multi-worker deployment. Run R is executing on worker W2. User sends
`POST /runs/R/pause` to worker W1. `get_active_run("R")` returns `None`.
API returns 404. User thinks the run doesn't exist.

IMPACT:
Misleading error response in multi-worker deployments. No data corruption.

FIX DIRECTION:
Return a sentinel value or raise a specific exception to distinguish
"on another worker" from "not found". Or add a separate
`is_active_on_another_worker(run_id)` function that callers can use to
produce a better error message.

--------------------------------------------------------------------
FILE:        app/core/run_control.py
FUNCTION:    register_active_run
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a RunManager as the active run for its run_id.

WHAT IT ACTUALLY DOES:
Stores the RunManager in `_ACTIVE_RUNS` under `_ACTIVE_RUNS_LOCK`, then
calls `_get_redis_client()` OUTSIDE the lock. If two concurrent calls to
`register_active_run` with the same `run_id` race, both will store their
RunManager in `_ACTIVE_RUNS` (the second overwrites the first), and both
will attempt to write to Redis. The Redis write is idempotent (`SET` with
TTL), so this is safe. But the in-process dict now holds the second
RunManager, while the first RunManager's pause/cancel events will never
be delivered.

THE BUG / RISK:
Two RunManagers with the same `run_id` (possible due to the 16-char truncation
bug in `RunManager.__init__`) will race. The second registration overwrites
the first in `_ACTIVE_RUNS`. The first run's pause/cancel signals are lost.

EVIDENCE:
```python
with _ACTIVE_RUNS_LOCK:
    _ACTIVE_RUNS[run.run_id] = run   # ← second call overwrites first

client = _get_redis_client()   # ← outside lock
if client is not None:
    client.set(...)
```

REPRODUCTION SCENARIO:
Two runs with the same `run_id` (due to UUID truncation collision). Both
call `register_active_run`. The second overwrites the first in `_ACTIVE_RUNS`.
Pause/cancel signals for the first run are delivered to the second run's
RunManager.

IMPACT:
Wrong run receives control signals. Low probability due to UUID collision
being rare, but the consequence is severe (wrong run paused/cancelled).

FIX DIRECTION:
This is a consequence of the `run_id` truncation bug in `RunManager.__init__`.
Fix the truncation there. Additionally, add a check here:
```python
with _ACTIVE_RUNS_LOCK:
    if run.run_id in _ACTIVE_RUNS:
        log.warning("run_control: run_id %r already registered — overwriting", run.run_id)
    _ACTIVE_RUNS[run.run_id] = run
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | SAFE |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_get_redis_client()` creates a new connection pool on every call — under concurrent load this exhausts Redis connections and silently degrades to in-process-only mode, breaking multi-worker run control. |
