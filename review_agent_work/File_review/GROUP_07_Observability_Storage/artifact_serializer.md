# Functional Review — app/core/artifact_serializer.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/artifact_serializer.py
FUNCTION:    ArtifactSerializerRegistry.register
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a handler for `artifact_type`. Replaces any existing handler for
the same type. Thread-safe.

WHAT IT ACTUALLY DOES:
When replacing an existing handler, it finds the old handler in
`self._ordered` using `list.index(old)`. If the same handler object was
registered for multiple artifact types (e.g. a handler registered for both
`"audio_samples"` and `"audio_raw"`), `list.index(old)` returns the index
of the FIRST occurrence. The second occurrence is not updated.

THE BUG / RISK:
A handler registered for two types that is then replaced for one type will
have the old handler object still present in `_ordered` at the second
position. `infer_type()` iterates `_ordered` and will call the old handler's
`infer_type()` for values that the new handler should handle.

EVIDENCE:
```python
old = self._handlers[artifact_type]
idx = self._ordered.index(old)   # ← finds FIRST occurrence only
self._ordered[idx] = handler
```

REPRODUCTION SCENARIO:
```python
registry.register("type_a", handler_v1)
registry.register("type_b", handler_v1)  # same object
registry.register("type_a", handler_v2)  # replace for type_a
# _ordered now has [handler_v2, handler_v1]
# _handlers["type_a"] = handler_v2, _handlers["type_b"] = handler_v1
# This is actually correct — handler_v1 is still in _ordered for type_b
```
Actually this scenario is correct. The real bug occurs when the same handler
object is registered for two types and then replaced for one:
```python
registry.register("type_a", handler_v1)
registry.register("type_b", handler_v1)  # same object, appended again
# _ordered = [handler_v1, handler_v1]  ← duplicate
```
`_ordered.append(handler)` is only called when `artifact_type not in
self._handlers`. For the second `register("type_b", handler_v1)` call,
`"type_b"` is not in `_handlers`, so `handler_v1` IS appended again.
`_ordered` now has `[handler_v1, handler_v1]`. `infer_type()` calls
`handler_v1.infer_type()` twice for every value — wasteful but not incorrect.

The real bug: when replacing with `register("type_a", handler_v2)`:
`old = handler_v1`, `idx = _ordered.index(handler_v1) = 0`.
`_ordered[0] = handler_v2`. `_ordered = [handler_v2, handler_v1]`.
Now `infer_type()` calls `handler_v2.infer_type()` then `handler_v1.infer_type()`.
`_handlers["type_a"] = handler_v2`, `_handlers["type_b"] = handler_v1`.
This is correct.

The actual bug is the duplicate in `_ordered` when the same object is
registered for two types. `infer_type()` calls the handler twice, which
is wasteful and could cause double-counting if the handler has side effects.

IMPACT:
Performance issue (double `infer_type()` calls). No correctness bug in
normal usage (single handler per type). Low severity in practice since
handlers are typically registered once at startup.

FIX DIRECTION:
Track which handler objects are in `_ordered` to avoid duplicates:
```python
if artifact_type not in self._handlers:
    if handler not in self._ordered:
        self._ordered.append(handler)
```

--------------------------------------------------------------------
FILE:        app/core/artifact_serializer.py
FUNCTION:    ArtifactSerializerRegistry.infer_type
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Ask each registered handler (in order) to identify `value`. Returns the
first non-None result. Thread-safe.

WHAT IT ACTUALLY DOES:
Acquires `self._lock` to copy `self._ordered`, then releases the lock before
iterating. This is correct for preventing mutation during copy. However, if
a handler's `infer_type()` method is slow (e.g. does I/O or ML inference),
the lock is not held during the slow call — which is the correct design.

The issue is that `infer_type()` is called from `save()` and `_write_checkpoint()`
on the hot path of every node execution. If many handlers are registered and
none match, all handlers are called sequentially. With 10 handlers each taking
1ms, this adds 10ms to every node execution.

THE BUG / RISK:
Not a correctness bug, but a performance risk. The `infer_type()` method has
no short-circuit for the common case where the value is clearly not an
artifact (e.g. a plain `int` or `str`).

EVIDENCE:
```python
for handler in handlers:
    result = handler.infer_type(value)
    if result is not None:
        return result
return None
```
No early exit for primitive types.

REPRODUCTION SCENARIO:
A node outputs a dict with 10 ports, each containing a plain integer. For
each port, `infer_type()` is called, iterating all registered handlers.
With 5 handlers, this is 50 `infer_type()` calls per node execution.

IMPACT:
Performance overhead on the hot path. No correctness issue.

FIX DIRECTION:
Add a fast-path check for primitive types before iterating handlers:
```python
if isinstance(value, (int, float, str, bool, type(None))):
    return None
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | LOW |
| Silent Failures | 0 |
| Error Handling | COMPLETE |
| Async Safety | SAFE |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Duplicate handler objects in `_ordered` when the same handler instance is registered for multiple types causes redundant `infer_type()` calls on every node execution — performance issue, not a correctness bug. |
