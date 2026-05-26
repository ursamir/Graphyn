# Functional Review — app/core/nodes/retry.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/retry.py
FUNCTION:    RetryPolicy (model) / wait_before_attempt
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
`RetryPolicy` defines retry configuration. The docstring states that
`wait_before_attempt(attempt_index)` returns the wait before retry
`attempt_index` (0-indexed), where `attempt_index=0` is the first retry.

WHAT IT ACTUALLY DOES:
`wait_before_attempt` is a pure configuration helper — it computes a wait
duration but has no knowledge of whether the attempt is retryable or not.
The `RetryPolicy` model has no `retryable_exceptions` field and no mechanism
to distinguish retryable from non-retryable exceptions. The executor that
uses `RetryPolicy` must implement that logic itself.

THE BUG / RISK:
The checkpoint focus area asks: "Does `retry.py` correctly handle
non-retryable exceptions vs retryable ones?" — The answer is: it does not.
`RetryPolicy` has no `retryable_exceptions` or `non_retryable_exceptions`
field. Any exception will be retried up to `max_attempts` times, including
`KeyboardInterrupt`, `SystemExit`, `MemoryError`, and application-level
permanent failures (e.g. `FileNotFoundError` for a missing model file).

This is a design gap: the policy model does not express which exceptions
should be retried. The executor must hard-code this logic or silently retry
everything.

EVIDENCE:
Lines 1-68 — no `retryable_exceptions` or `non_retryable_exceptions` field.
`wait_before_attempt` (lines 60-68) only computes timing.

REPRODUCTION SCENARIO:
A node raises `FileNotFoundError` (model file missing). With `max_attempts=3`,
the executor retries 3 times, each time failing with the same error. The
3-second total delay is wasted and the error message is delayed.

IMPACT:
Wasted retry attempts on permanent failures. No crash, but incorrect behavior
and delayed error surfacing.

FIX DIRECTION:
Add an optional field:
```python
retryable_exceptions: list[str] = []
# e.g. ["ConnectionError", "TimeoutError"]
```
Or document explicitly that the executor is responsible for exception filtering
and that `RetryPolicy` is timing-only.

--------------------------------------------------------------------
FILE:        app/core/nodes/retry.py
FUNCTION:    wait_before_attempt
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the wait time in seconds before retry `attempt_index` (0-indexed).

WHAT IT ACTUALLY DOES:
Returns `self.backoff_seconds * (self.backoff_multiplier ** attempt_index)`.
With `backoff_seconds=0.0` (the default), this always returns `0.0` regardless
of `attempt_index` or `backoff_multiplier`. This is mathematically correct but
means the default policy has no wait between retries — retries happen
immediately. For a node that fails due to a transient resource contention,
immediate retries may worsen the situation.

Additionally, there is no cap on the computed wait time. With
`backoff_seconds=1.0`, `backoff_multiplier=2.0`, and `max_attempts=30`,
`wait_before_attempt(28)` returns `268,435,456` seconds (~8.5 years). The
executor would hang indefinitely.

THE BUG / RISK:
No upper bound on computed wait time. An accidental large `max_attempts` with
exponential backoff produces an astronomically large wait.

EVIDENCE:
Lines 60-68:
```python
def wait_before_attempt(self, attempt_index: int) -> float:
    return self.backoff_seconds * (self.backoff_multiplier ** attempt_index)
```
No `max_wait_seconds` cap.

REPRODUCTION SCENARIO:
```python
policy = RetryPolicy(max_attempts=50, backoff_seconds=1.0, backoff_multiplier=2.0)
policy.wait_before_attempt(49)  # returns 562,949,953,421,312.0 seconds
```

IMPACT:
Executor hangs for an astronomically long time. No crash, but effectively
a hang.

FIX DIRECTION:
Add a `max_wait_seconds: float = 60.0` field and cap the return value:
```python
return min(self.backoff_seconds * (self.backoff_multiplier ** attempt_index),
           self.max_wait_seconds)
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | No retryable/non-retryable exception distinction — permanent failures (FileNotFoundError, etc.) are retried the full max_attempts times. |
