# Group Review Index — 11: MCP

**Files reviewed:** 10
**Total findings:** 28 (CRITICAL: 2 | HIGH: 5 | MEDIUM: 13 | LOW: 8)
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| server.md | MEDIUM | 1 | `json.dumps(result)` is outside the exception handler — non-serialisable handler return causes unhandled protocol-level error |
| auth.md | MEDIUM | 0 | Timing side-channel in token comparison — use `hmac.compare_digest` instead of `!=` |
| tool_registry.md | LOW | 1 | Silent duplicate tool registration — `_register()` overwrites without warning, breaking test isolation |
| execution.md | CRITICAL | 2 | Discarded Future from `_PIPELINE_EXECUTOR.submit()` — background execution exceptions silently swallowed; run stays "running" forever if orchestrator crashes |
| run_control.md | HIGH | 1 | `cancel_run` returns `{"status": "cancelled"}` but run is still executing — cancel signal only sent, `mark_cancelled()` happens asynchronously |
| discovery.md | LOW | 0 | `_serialize_node_metadata` calls `get_config_schema` once per node — O(n) Pydantic schema generation on every unfiltered `list_nodes` call |
| artifacts.md | MEDIUM | 2 | `str.replace("node_", "")` strips all occurrences — node IDs containing "node_" are silently mangled in checkpoints list |
| provenance.md | CRITICAL | 2 | Discarded Future from `_REPLAY_EXECUTOR.submit()` — background replay exceptions silently swallowed; run stays "running" forever |
| graph.md | MEDIUM | 1 | `edges=[]` treated as "no edges" rather than "auto-chain" — produces silently disconnected graph that passes validation |
| optimization.md | MEDIUM | 2 | `resolve_capability` never raises (returns defaults for unknown types) — dead `except` branch means unknown nodes silently get wrong default capabilities |

---

## Priority Findings (CRITICAL and HIGH only)

**[CRITICAL] execution.md — execute_pipeline_handler — Discarded Future: background execution exceptions silently swallowed; run stays in "running" status forever if orchestrator crashes before calling `mark_failed`.**

**[CRITICAL] provenance.md — replay_run_handler — Discarded Future: background replay exceptions silently swallowed; run stays in "running" status forever if orchestrator crashes before calling `mark_failed`.**

**[HIGH] execution.md — execute_pipeline_handler — Error contract mismatch: IR validation failure returns `{"valid": False, "errors": [...]}` instead of the standard `{"error": True, "error_type": "ir_validation_error", ...}` — callers checking `result.get("error")` silently miss this failure.**

**[HIGH] execution.md — execute_pipeline_handler — State bug: if `_PIPELINE_EXECUTOR.submit()` raises during shutdown, `RunManager` is orphaned with permanent "running" status.**

**[HIGH] run_control.md — handle_cancel_run / handle_pause_run / handle_resume_run — Contract mismatch: `cancel_run` returns `{"status": "cancelled"}` but the run is still executing; `mark_cancelled()` is called asynchronously by the orchestrator's finally block.**

**[HIGH] run_control.md — handle_pause_run / handle_resume_run / handle_cancel_run — Unhandled `OSError` from `_write_meta_field` propagates to server's generic handler with undocumented error type.**

**[HIGH] graph.md — generate_graph_handler — `edges=[]` (empty list) is treated as "no edges" rather than "auto-chain" — produces a silently disconnected graph that passes validation but has no data flow.**

**[HIGH] server.md — handle_call_tool — `json.dumps(result)` is outside the `except` block — non-serialisable handler return value causes an unhandled protocol-level error instead of a structured tool error.**

---

## Most Dangerous File

**execution.md** — The discarded `Future` from `_PIPELINE_EXECUTOR.submit()` means any unhandled exception in the background execution thread is silently swallowed, leaving the run in permanent "running" status with no way for the caller to detect the failure. The same pattern is repeated in `provenance.md` for replay runs, making both the primary execution and replay paths affected by this class of bug.
