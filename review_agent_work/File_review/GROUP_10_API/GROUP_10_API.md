# Group Review Index — 10: API

**Files reviewed:** 7  
**Total findings:** 22 (CRITICAL: 0 | HIGH: 6 | MEDIUM: 12 | LOW: 4)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| main.md | MEDIUM | 1 | Registry init failure at import time crashes the entire API server with no graceful degradation. |
| pipelines.md | HIGH | 2 | Bounded queue with blocking put() causes pipeline execution thread to hang indefinitely when the HTTP client is slow or disconnected. |
| runs.md | MEDIUM | 1 | get_run_status silently returns 100% progress when num_nodes is absent from meta.json, giving wrong progress data for in-progress runs. |
| artifacts.md | HIGH | 1 | Unbounded executor task queue allows memory exhaustion under concurrent replay requests, with no backpressure or 429 response to callers. |
| run_control.md | MEDIUM | 0 | Blocking threading.Lock acquisition inside async def handlers stalls the event loop under concurrent control requests. |
| nodes.md | MEDIUM | 0 | GET /nodes triggers O(n) schema generations per request with no caching guard in this layer, causing high CPU under load. |
| plugins.md | HIGH | 1 | Remote plugin install failures are silently swallowed — callers receive "installing" status and have no way to detect or retrieve the failure reason. |

---

## Priority Findings (CRITICAL and HIGH only)

**[HIGH] pipelines.md — run_pipeline_stream — Bounded queue with blocking `queue.put()` causes pipeline execution thread to hang indefinitely when the HTTP client is slow or disconnected.**

**[HIGH] pipelines.md — run_pipeline_stream — `json.dumps()` failure in the stream generator silently truncates the NDJSON stream with no error event sent to the client.**

**[HIGH] pipelines.md — run_pipeline_async — Async runs are never registered with `register_active_run()`, so pause/resume/cancel via the run-control API silently returns 404 for all valid async run IDs.**

**[HIGH] artifacts.md — replay_artifact — Unbounded `ThreadPoolExecutor` task queue allows memory exhaustion under concurrent replay requests; no backpressure or 429 returned to callers.**

**[HIGH] artifacts.md — replay_artifact / _do_replay — No `finally` block to deregister the run from the active registry; exceptions from `mark_failed()` are silently lost.**

**[HIGH] plugins.md — install_plugin (remote path) — Background install failures are only logged; no failure state is written to any store, so callers cannot distinguish "install failed" from "install still running" via the poll endpoint.**

---

## Most Dangerous File

**pipelines.md** — Two independent HIGH-severity bugs: a blocking `queue.put()` that hangs pipeline threads when clients disconnect, and missing `register_active_run()` that silently breaks all run-control operations for async runs.
