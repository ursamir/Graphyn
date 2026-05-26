# Functional Review — app/core/logger.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/logger.py
FUNCTION:    PipelineLogger._emit
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Append a log entry to the deque, write to Python logging, and put on the
streaming queue.

WHAT IT ACTUALLY DOES:
Calls `self.queue.put(entry)` without a timeout. If the queue is a bounded
`Queue` (created with `maxsize > 0`) and the consumer is slow or dead, `put()`
blocks indefinitely. This blocks the pipeline execution thread.

THE BUG / RISK:
`PipelineLogger.__init__` accepts any `Queue` object. If the caller passes a
bounded queue (e.g. `Queue(maxsize=100)`) and the consumer stops reading,
`self.queue.put(entry)` blocks. Every subsequent log call blocks. The pipeline
hangs.

EVIDENCE:
```python
if self.queue:
    self.queue.put(entry)   # ← blocks if queue is full and consumer is dead
```
No timeout, no `put_nowait`, no try/except.

REPRODUCTION SCENARIO:
API streaming endpoint creates `PipelineLogger(queue=Queue(maxsize=100))`.
Client disconnects. Consumer stops reading. After 100 log entries, `put()`
blocks. Pipeline execution hangs indefinitely.

IMPACT:
Pipeline hang — execution never completes. The run stays in "running" state
forever. No data corruption.

FIX DIRECTION:
Use `put_nowait` with a try/except, or `put` with a timeout:
```python
if self.queue:
    try:
        self.queue.put_nowait(entry)
    except Exception:
        pass  # queue full or closed — drop the entry
```

--------------------------------------------------------------------
FILE:        app/core/logger.py
FUNCTION:    PipelineLogger._emit_structured
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Append a typed event to logs, put it on the queue, and write a DEBUG-level
line to the Python logging system.

WHAT IT ACTUALLY DOES:
Same queue issue as `_emit` — calls `self.queue.put(entry)` without a
timeout. Additionally, `_emit_structured` is called from ALL structured
event methods (`node_start`, `node_end`, `wave_start`, `wave_end`, etc.),
which are called on the hot path of every node execution. A blocked queue
blocks the entire pipeline.

THE BUG / RISK:
Same as `_emit` — blocked queue blocks pipeline. More severe because
`_emit_structured` is called more frequently than `_emit`.

EVIDENCE:
```python
def _emit_structured(self, entry: dict):
    self.logs.append(entry)
    event_type = entry.get("type", "event")
    _log.debug("structured_event type=%s %s", event_type, entry)
    if self.queue:
        self.queue.put(entry)   # ← blocks if queue is full
```

REPRODUCTION SCENARIO:
Same as `_emit` — bounded queue with dead consumer.

IMPACT:
Pipeline hang on every node execution event. More severe than `_emit` since
`_emit_structured` is called for every `node_start`, `node_end`, `wave_start`,
`wave_end` event.

FIX DIRECTION:
Same as `_emit` — use `put_nowait` with try/except.

--------------------------------------------------------------------
FILE:        app/core/logger.py
FUNCTION:    PipelineLogger.node_end
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Emit a `node_end` event with `output_count` representing the number of
output samples.

WHAT IT ACTUALLY DOES:
The plain-text log message uses `output_count` as "samples":
```python
count_str = f" → {output_count} samples" if output_count else ""
```
But `output_count` is documented as "output_count: int = 0" with no
constraint on what it counts. Callers may pass the number of output ports,
the number of output items, or the number of audio samples. The unit is
ambiguous.

THE BUG / RISK:
Misleading log output. If a caller passes `output_count=3` meaning "3 output
ports", the log says "→ 3 samples" which is incorrect.

EVIDENCE:
```python
def node_end(self, node_type, index, duration, output_count: int = 0):
    count_str = f" → {output_count} samples" if output_count else ""
```
No docstring clarifying what `output_count` counts.

REPRODUCTION SCENARIO:
A node with 3 output ports calls `node_end(..., output_count=3)`. Log says
"→ 3 samples" but the node produced 3 ports, not 3 samples.

IMPACT:
Misleading log output. No functional bug.

FIX DIRECTION:
Rename parameter to `output_sample_count` and add a docstring clarifying
it counts audio samples, not ports.

--------------------------------------------------------------------
FILE:        app/core/logger.py
FUNCTION:    PipelineLogger.summary
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Emit a plain-text completion line and a structured `pipeline_summary` event.

WHAT IT ACTUALLY DOES:
Emits a `pipeline_summary` event via `_emit_structured`. Also calls
`self.info(...)` which calls `_emit` which appends to `self.logs` AND puts
on the queue. Then `_emit_structured` also appends to `self.logs` AND puts
on the queue. So the queue receives TWO entries for one `summary()` call:
one plain-text INFO entry and one structured `pipeline_summary` event.

THE BUG / RISK:
Queue consumers receive two events per `summary()` call. If the consumer
deduplicates by event type, the plain-text INFO entry is unexpected. If the
consumer counts events, the count is off by one.

EVIDENCE:
```python
def summary(self) -> None:
    total = time.time() - self.start_time
    self.info(f"Pipeline completed in {total:.3f}s")   # ← puts INFO entry on queue
    self._emit_structured({                              # ← puts pipeline_summary on queue
        "type": "pipeline_summary",
        ...
    })
```

REPRODUCTION SCENARIO:
Streaming API consumer receives both a plain `{"level": "INFO", "message":
"Pipeline completed in 1.234s"}` entry and a `{"type": "pipeline_summary",
"duration_s": 1.234}` entry. Consumer expecting only structured events is
confused by the plain-text entry.

IMPACT:
Duplicate queue entries for `summary()`. Minor consumer confusion.

FIX DIRECTION:
Remove the `self.info(...)` call from `summary()` since the structured event
already contains the duration. Or document that `summary()` emits two entries.

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
| Top Risk | `_emit` and `_emit_structured` call `queue.put()` without a timeout — a bounded queue with a dead consumer blocks the pipeline execution thread indefinitely on every log call. |
