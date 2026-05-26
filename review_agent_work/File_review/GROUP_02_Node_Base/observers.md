# Functional Review — app/core/nodes/observers.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/observers.py
FUNCTION:    LoggingObserver.on_node_error
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Emit a structured JSON error log including the traceback.

WHAT IT ACTUALLY DOES:
Calls `_traceback.format_exc()` at the time `on_node_error` is called.
`format_exc()` returns the *current* exception's traceback — i.e. the
traceback of whatever exception is active in the current thread at the
moment `on_node_error` is called.

The problem: `on_node_error` is called from `Node.on_error()` (base.py),
which is called by the executor *after* catching the exception. If the
executor catches the exception with `except Exception as exc:` and then
calls `node.on_error(exc)`, the exception context is still active and
`format_exc()` returns the correct traceback.

However, if the executor calls `on_error` *outside* the `except` block
(e.g. in a `finally` clause or after re-raising and re-catching), the
active exception context may be different or absent. In that case,
`format_exc()` returns `"NoneType: None\n"` — a silent wrong result.

Additionally, `format_exc()` returns the traceback of the *last* exception
in the current thread, not necessarily `exc`. If the observer itself raises
and is caught (e.g. in `CompositeObserver`), the active exception changes
and `format_exc()` in a subsequent observer call returns the wrong traceback.

THE BUG / RISK:
`format_exc()` is context-dependent. If called outside an active `except`
block, it returns `"NoneType: None\n"`. The log entry shows the exception
message correctly (from `str(exc)`) but the traceback is wrong or empty.

EVIDENCE:
Lines 103-110:
```python
def on_node_error(self, node_type: str, run_id: str, exc: Exception) -> None:
    self._log.error(json.dumps({
        ...
        "traceback": _traceback.format_exc(),
    }))
```

REPRODUCTION SCENARIO:
```python
try:
    node.process(inputs)
except Exception as exc:
    pass  # exception context cleared
node.on_error(exc)  # format_exc() returns "NoneType: None\n"
```

IMPACT:
Silent wrong result — error logs show `"NoneType: None\n"` as the traceback
instead of the actual stack trace. Debugging is severely hampered.

FIX DIRECTION:
Use `traceback.format_exception(type(exc), exc, exc.__traceback__)` which
extracts the traceback from the exception object directly, independent of
the current exception context:
```python
"traceback": "".join(_traceback.format_exception(
    type(exc), exc, exc.__traceback__
)),
```

--------------------------------------------------------------------
FILE:        app/core/nodes/observers.py
FUNCTION:    LoggingObserver.on_node_start / on_node_end / on_node_error
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Emit structured JSON log lines.

WHAT IT ACTUALLY DOES:
Calls `json.dumps(...)` with values that may not be JSON-serialisable.
Specifically, `input_counts` and `output_counts` are typed as
`dict[str, int]` — these are safe. However, `exc` is passed through
`str(exc)` which is safe. The risk is that a future caller passes a
non-serialisable value in `input_counts` or `output_counts` (e.g. a
numpy int64 instead of a Python int). `json.dumps` would raise
`TypeError`, which propagates out of `on_node_end` uncaught.

THE BUG / RISK:
If `input_counts` or `output_counts` contain non-JSON-serialisable values
(e.g. numpy integers), `json.dumps` raises `TypeError`. This exception
propagates to the caller (the executor), potentially crashing the pipeline.
The observer contract says observers should not crash the node — but this
observer can crash the executor.

EVIDENCE:
Lines 88-97:
```python
self._log.info(json.dumps({
    ...
    "input_counts": input_counts,
    "output_counts": output_counts,
}))
```
No try/except around `json.dumps`.

REPRODUCTION SCENARIO:
Executor passes `input_counts={"audio": numpy.int64(1)}`.
`json.dumps` raises `TypeError: Object of type int64 is not JSON serializable`.

IMPACT:
Crash in executor if observer receives non-serialisable counts.

FIX DIRECTION:
Wrap `json.dumps` in a try/except or use a custom encoder:
```python
try:
    self._log.info(json.dumps({...}))
except (TypeError, ValueError) as e:
    self._log.info(f"node_end event (serialization failed: {e})")
```

--------------------------------------------------------------------
FILE:        app/core/nodes/observers.py
FUNCTION:    CompositeObserver.__init__
CATEGORY:    State Safety
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Fan out events to a list of child observers.

WHAT IT ACTUALLY DOES:
Stores `self._observers = list(observers)`. This is a shallow copy of the
input list, so mutations to the original list after construction do not
affect `CompositeObserver`. However, the observer objects themselves are
shared references. If a child observer has mutable state (e.g. a counter),
that state is shared between the `CompositeObserver` and any other holder
of the same observer reference.

THE BUG / RISK:
Not a bug in `CompositeObserver` itself, but a documentation gap. The
class does not document that child observers are shared by reference.
If a caller modifies a child observer's state externally, the
`CompositeObserver` sees the change. This is expected Python behavior
but worth noting for testability.

EVIDENCE:
Line 122: `self._observers = list(observers)`

REPRODUCTION SCENARIO:
Low risk — standard Python reference semantics.

IMPACT:
Low — expected behavior, but undocumented.

FIX DIRECTION:
Document that child observers are held by reference, not copied.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `LoggingObserver.on_node_error` uses `traceback.format_exc()` which returns the wrong traceback when called outside an active except block, silently logging "NoneType: None" instead of the real stack trace. |
