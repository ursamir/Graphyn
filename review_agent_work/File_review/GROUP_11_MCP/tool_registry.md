# Functional Review — app/mcp/tool_registry.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/tool_registry.py
FUNCTION:    register_all_tools
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Import all handlers and register them. Single place that wires handler
functions to tool names.

WHAT IT ACTUALLY DOES:
Calls `register(name, description, schema, handler)` 15 times. The
`register` function (from `server.py`) is `_register()`, which does:
```python
_TOOLS[name] = {"description": ..., "inputSchema": ..., "handler": ...}
```
This is a plain dict assignment — it silently overwrites any existing
entry with the same name. If `register_all_tools` is called twice (e.g.
in a test that re-initialises the server, or if `_startup()` is called
more than once), all 15 tools are silently re-registered with no warning.
This is not a crash, but it means duplicate registration is invisible.

THE BUG / RISK:
Silent duplicate registration: if `register_all_tools` is called twice,
the second call silently overwrites the first. No error, no warning. In
production this is harmless (same handlers), but in tests where a mock
handler is registered first and then `register_all_tools` is called, the
mock is silently replaced.

EVIDENCE:
`_register()` in server.py line ~46:
```python
_TOOLS[name] = {
    "description": description,
    "inputSchema": input_schema,
    "handler": handler,
}
```
No duplicate check.

REPRODUCTION SCENARIO:
1. Test registers a mock handler: `_register("execute_pipeline", ..., mock_fn)`
2. Test calls `register_all_tools(_register)` to set up other tools.
3. `execute_pipeline` is now the real handler, not the mock. Test passes
   against the real implementation silently.

IMPACT:
Test isolation failure; silent overwrite in production if startup is
called twice (e.g. after a SIGHUP reload). No data loss or crash.

FIX DIRECTION:
Add a duplicate check in `_register()`:
```python
if name in _TOOLS:
    log.warning("Tool '%s' already registered — overwriting.", name)
_TOOLS[name] = {...}
```
Or raise on duplicate in strict mode.
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/tool_registry.py
FUNCTION:    register_all_tools
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Import all handlers and register them.

WHAT IT ACTUALLY DOES:
All imports are inside the function body (lazy). If any handler module
has a syntax error or import-time exception, the entire `register_all_tools`
call raises, which is caught by `_startup()` and causes `sys.exit(1)`.
This is correct behavior — a broken handler should prevent startup.

However, the error message from `_startup()` will say "Tool registration
failed: <import error>" without identifying which specific handler module
failed. With 15 tools across 7 handler modules, this can be slow to
diagnose.

THE BUG / RISK:
Low severity: the failure is caught and the process exits. Diagnosis is
slightly harder than necessary because the module name is in the traceback
but not in the top-level log message.

EVIDENCE:
`_startup()` in server.py: `log.error("Tool registration failed: %s", exc, exc_info=True)`
— `exc_info=True` does include the full traceback, so the module name IS
visible in the logs. This is actually adequate.

REPRODUCTION SCENARIO:
Introduce a syntax error in `handlers/execution.py`. Server exits with
a traceback that includes the module name.

IMPACT:
None — `exc_info=True` provides sufficient diagnostic information.

FIX DIRECTION:
No fix needed.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | LOW |
| Silent Failures | 1 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | Silent duplicate tool registration — `_register()` overwrites without warning, breaking test isolation when mocks are registered before `register_all_tools`. |
