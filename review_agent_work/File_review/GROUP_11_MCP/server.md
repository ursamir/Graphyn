# Functional Review — app/mcp/server.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/server.py
FUNCTION:    handle_call_tool
CATEGORY:    Async Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Dispatch a tool invocation asynchronously via the MCP protocol handler.

WHAT IT ACTUALLY DOES:
Calls `asyncio.get_running_loop().run_in_executor(None, lambda: handler(arguments))`.
All handlers are synchronous functions, so this is correct in principle.
However, the lambda captures `handler` and `arguments` by reference from the
enclosing scope. In Python, closures in a loop capture the variable, not the
value — but here there is no loop, so the capture is safe. The real issue is
that `run_in_executor` submits to the default executor (a `ThreadPoolExecutor`
with a thread count equal to `min(32, os.cpu_count() + 4)`). This is a
different executor from `_PIPELINE_EXECUTOR` in `execution.py`. Under high
concurrency, the default executor can spawn many threads, each potentially
blocking on I/O or ML inference, with no bound.

THE BUG / RISK:
The default executor has no explicit `max_workers` cap. Under sustained load
(many concurrent MCP tool calls), the default executor can grow to 32+ threads,
each potentially running a long-running handler (e.g. `execute_pipeline_handler`
which itself submits to `_PIPELINE_EXECUTOR`). This creates two unbounded thread
pools stacked on top of each other for the execution path.

EVIDENCE:
Line ~85:
```python
result = await asyncio.get_running_loop().run_in_executor(
    None, lambda: handler(arguments)
)
```
`None` = use the default executor (no max_workers bound set here).

REPRODUCTION SCENARIO:
Send 50 concurrent `execute_pipeline` MCP calls. The default executor spawns
up to 32 threads, each of which submits to `_PIPELINE_EXECUTOR` (4 workers).
The 32 executor threads all block waiting for `_PIPELINE_EXECUTOR.submit()`
to return (which is non-blocking), so the actual execution is fine — but the
32 threads are wasted waiting for a non-blocking call, consuming OS resources.

IMPACT:
Resource waste; potential thread exhaustion under sustained load. Not a
correctness bug for the current handler set (all handlers return quickly after
submitting to background executors), but becomes a correctness bug if any
handler is added that does real blocking work inline.

FIX DIRECTION:
Create a module-level bounded executor for handler dispatch:
```python
_HANDLER_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-handler")
# then in handle_call_tool:
result = await asyncio.get_running_loop().run_in_executor(
    _HANDLER_EXECUTOR, lambda: handler(arguments)
)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/server.py
FUNCTION:    handle_call_tool
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a structured JSON error dict when a handler raises an exception.

WHAT IT ACTUALLY DOES:
Catches `Exception` and returns a structured error dict. However, if
`json.dumps(result)` raises (e.g. the handler returns a non-serialisable
object like a numpy array, a datetime, or a Pydantic model), the exception
propagates out of `handle_call_tool` uncaught, which causes the MCP server
to return a protocol-level error rather than a structured tool error.

THE BUG / RISK:
If any handler returns a value that is not JSON-serialisable, `json.dumps(result)`
raises `TypeError`. This exception is NOT caught by the `except Exception` block
(which only wraps `handler(arguments)`, not `json.dumps`). The MCP transport
layer receives an unhandled exception and may close the connection or return
a malformed response.

EVIDENCE:
Lines ~88–97:
```python
try:
    result = await asyncio.get_running_loop().run_in_executor(
        None, lambda: handler(arguments)
    )
    log.info("tool=%s outcome=success", name)
    return [types.TextContent(type="text", text=json.dumps(result))]  # ← can raise
except Exception as exc:
    ...  # only catches handler() exceptions, not json.dumps() exceptions
```

REPRODUCTION SCENARIO:
A handler returns `{"data": datetime.now()}`. `json.dumps` raises `TypeError:
Object of type datetime is not JSON serializable`. This propagates to the MCP
transport layer.

IMPACT:
Silent wrong behavior from the caller's perspective — the tool call fails at
the protocol level instead of returning a structured error. Hard to debug.

FIX DIRECTION:
```python
try:
    result = await asyncio.get_running_loop().run_in_executor(
        None, lambda: handler(arguments)
    )
    text = json.dumps(result, default=str)  # fallback serialiser
except Exception as exc:
    text = json.dumps({"error": True, "error_type": type(exc).__name__, "message": str(exc)})
return [types.TextContent(type="text", text=text)]
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/server.py
FUNCTION:    _startup
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register all tools; exit with code 1 on any registration failure.

WHAT IT ACTUALLY DOES:
Wraps the entire startup block in a single `try/except Exception`. This means
a partial registration (e.g. 10 of 15 tools registered before an import error)
results in `sys.exit(1)` — correct. However, the log message only shows the
exception, not which tool or handler caused the failure, making diagnosis slow.

THE BUG / RISK:
Low severity: the failure is caught and the process exits cleanly. But the
error message `"Tool registration failed: %s"` does not include the traceback
context of which specific import or handler caused the failure, even though
`exc_info=True` is passed (which does log the traceback to stderr). This is
actually fine — `exc_info=True` does include the full traceback. No real bug.

EVIDENCE:
Lines ~107–115: `log.error("Tool registration failed: %s", exc, exc_info=True)`
— `exc_info=True` correctly logs the full traceback.

REPRODUCTION SCENARIO:
N/A — this is actually handled correctly.

IMPACT:
None — logging is adequate.

FIX DIRECTION:
No fix needed.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `json.dumps(result)` is outside the exception handler — a non-serialisable handler return value causes an unhandled protocol-level error instead of a structured tool error. |
