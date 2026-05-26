# Functional Review — app/core/node_executor.py

**Group:** 6 — Execution Runtime  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/node_executor.py
FUNCTION:    NodeExecutor.execute
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute the node synchronously with full lifecycle + retry, returning the output dict.

WHAT IT ACTUALLY DOES:
When `node.process(inputs)` returns `None` (a node that forgets to return its
outputs dict), the code proceeds to write `None` into `node._last_output_counts`
via `{k: _count_port_items(v) for k, v in outputs.items()}`, which raises
`AttributeError: 'NoneType' object has no attribute 'items'`.

THE BUG / RISK:
`outputs = node.process(inputs)` is never checked for `None`. If any node
returns `None` instead of a dict, the executor crashes with an `AttributeError`
at the `_last_output_counts` assignment rather than raising a clear contract
violation error. The caller sees a confusing `AttributeError` instead of a
`NodeContractError` or similar.

EVIDENCE:
```python
# line ~100
outputs = node.process(inputs)
# ...
node._last_output_counts = {k: _count_port_items(v) for k, v in outputs.items()}
#                                                                  ^^^^^^^^^^^^^^
# AttributeError if outputs is None
```

REPRODUCTION SCENARIO:
```python
class BadNode(Node):
    def process(self, inputs):
        return None   # forgot to return

exec_ = NodeExecutor(BadNode(), run_id="r1")
exec_.setup()
exec_.execute({})   # raises AttributeError, not a clear contract error
```

IMPACT:
Silent wrong behavior — the error message is misleading. `on_error()` is NOT
called because the exception is raised after `process()` returns, outside the
`try/except` that wraps `process()`. The observer never sees the error event.

FIX DIRECTION:
```python
outputs = node.process(inputs)
if outputs is None:
    outputs = {}   # or raise NodeContractError(f"{node_type}.process() returned None")
```

--------------------------------------------------------------------
FILE:        app/core/node_executor.py
FUNCTION:    NodeExecutor.execute
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Calls `on_error()` on the last failed attempt and then re-raises.

WHAT IT ACTUALLY DOES:
When `node.process(inputs)` raises, the `except` block calls `node.on_error(exc)`
and sets `last_exc = exc`, then `continue`s to the next attempt. However, the
`AttributeError` from `outputs.items()` (when `outputs is None`) is raised
**outside** the `try/except` block that wraps `process()`, so `on_error()` is
never called for that failure mode.

THE BUG / RISK:
Any exception raised between `outputs = node.process(inputs)` and `return outputs`
(e.g., the `_last_output_counts` assignment) bypasses the `on_error()` call and
the retry loop entirely — it propagates directly to the caller without observer
notification and without retry.

EVIDENCE:
```python
try:
    outputs = node.process(inputs)
except Exception as exc:
    node.on_error(exc)
    last_exc = exc
    continue

# ← code here is NOT inside the try/except
node._last_duration = duration
node._last_input_counts = ...
node._last_output_counts = {k: _count_port_items(v) for k, v in outputs.items()}
# ↑ AttributeError here skips on_error() and retry
node.on_end()
return outputs
```

REPRODUCTION SCENARIO:
Any node returning `None` from `process()` triggers this path.

IMPACT:
Observer never receives `on_error` event. Retry policy is bypassed. Caller
receives `AttributeError` with no context about which node failed.

FIX DIRECTION:
Extend the `try/except` to cover the post-process bookkeeping, or validate
`outputs` immediately after `process()` returns.

--------------------------------------------------------------------
FILE:        app/core/node_executor.py
FUNCTION:    NodeExecutor.execute
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Calls `teardown()` after all retry attempts are exhausted.

WHAT IT ACTUALLY DOES:
After exhausting all attempts, the code calls `self.teardown()` if
`self._setup_done`. However, `teardown()` calls `self._node.teardown()` but
does NOT reset `self._setup_done = False`. If the caller catches the exception
and calls `setup()` again (e.g., in a retry-at-pipeline-level scenario), the
guard `if not self._setup_done` prevents `setup()` from running again, leaving
the node in a torn-down state while `_setup_done` is still `True`.

THE BUG / RISK:
`_setup_done` is never reset to `False` in `teardown()`. A caller that catches
the exception and calls `executor.setup()` again will get a no-op, then call
`execute()` on a node that was never re-initialized.

EVIDENCE:
```python
def teardown(self) -> None:
    self._node.teardown()
    # _setup_done is never reset to False
```

REPRODUCTION SCENARIO:
```python
exec_ = NodeExecutor(node, run_id="r1")
exec_.setup()
try:
    exec_.execute({})   # fails all retries → teardown() called internally
except Exception:
    exec_.setup()       # no-op! _setup_done is still True
    exec_.execute({})   # node was never re-setup
```

IMPACT:
Silent wrong result — node executes in a torn-down state.

FIX DIRECTION:
```python
def teardown(self) -> None:
    self._node.teardown()
    self._setup_done = False
```

--------------------------------------------------------------------
FILE:        app/core/node_executor.py
FUNCTION:    NodeExecutor.execute_stream
CATEGORY:    Async Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
`on_end()` fires in a `finally` block so it fires even when the caller breaks
out of the async for early.

WHAT IT ACTUALLY DOES:
`on_start()` is called before the `try` block. If `on_start()` raises, the
`finally` block still runs and calls `on_end()` — but `on_start()` never
completed, so the node is in an inconsistent state. Additionally, `on_error()`
is NOT called when `on_start()` raises (only when the generator body raises).

THE BUG / RISK:
If `node.on_start()` raises, `on_end()` is called via `finally` without a
matching successful `on_start()`, and `on_error()` is never called. This
mirrors the same asymmetry in `execute()` but is harder to notice in the
streaming path.

EVIDENCE:
```python
node.on_start()          # ← if this raises...
try:
    async for item in node.process_stream(inputs):
        yield item
except Exception as exc:
    node.on_error(exc)   # ← not reached for on_start() failure
    raise
finally:
    node.on_end()        # ← always called, even if on_start() raised
```

REPRODUCTION SCENARIO:
A node whose `on_start()` raises (e.g., resource unavailable) will trigger
`on_end()` without a matching `on_start()`, confusing observers.

IMPACT:
Observer receives `on_end` without `on_start`. Metrics/tracing systems that
track open spans will see unmatched end events.

FIX DIRECTION:
```python
started = False
try:
    node.on_start()
    started = True
    async for item in node.process_stream(inputs):
        yield item
except Exception as exc:
    node.on_error(exc)
    raise
finally:
    if started:
        node.on_end()
```

--------------------------------------------------------------------
FILE:        app/core/node_executor.py
FUNCTION:    NodeExecutor.execute
CATEGORY:    Async Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute the node synchronously.

WHAT IT ACTUALLY DOES:
Uses `time.sleep(wait)` for retry back-off. This is a blocking call. If
`execute()` is ever called from an async context (e.g., via
`loop.run_in_executor` in `executor.py`), the sleep blocks the thread-pool
thread, which is acceptable. However, if called directly from a coroutine
(not via executor), it blocks the event loop.

THE BUG / RISK:
`time.sleep()` in a sync method called from `loop.run_in_executor()` is safe.
But the docstring says "Execute the node synchronously" without warning that
calling it directly from a coroutine will block the event loop during retry
back-off.

EVIDENCE:
```python
if wait > 0:
    time.sleep(wait)   # blocks event loop if called from coroutine directly
```

REPRODUCTION SCENARIO:
Direct `await loop.run_in_executor(None, exec_.execute, inputs)` is safe.
But `exec_.execute(inputs)` called directly inside a coroutine with retry
back-off > 0 blocks the event loop.

IMPACT:
Event loop stall during retry back-off if misused. Low risk given current
call sites all use `run_in_executor`.

FIX DIRECTION:
Add a docstring warning: "Must not be called directly from a coroutine — use
`loop.run_in_executor()` to avoid blocking the event loop during retry back-off."

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `process()` returning `None` bypasses `on_error()`, skips retry, and raises a misleading `AttributeError` with no observer notification |
