# Group Review Index — 2: Node Base

**Files reviewed:** 8
**Total findings:** 18 (CRITICAL: 0 | HIGH: 3 | MEDIUM: 10 | LOW: 5)
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| base.md | HIGH | 3 | `process_stream` silently yields a coroutine object when a subclass overrides `process` as `async def` |
| ports.md | MEDIUM | 1 | `Annotated`/`Literal` types pass the data_type validator and cause incorrect compatibility checks downstream |
| config.md | LOW | 0 | None |
| retry.md | MEDIUM | 0 | No retryable/non-retryable exception distinction — permanent failures are retried the full max_attempts times |
| metadata.md | LOW | 1 | Version regex accepts trailing-separator strings like "1.0.0-" which may break downstream version parsers |
| observers.md | MEDIUM | 1 | `LoggingObserver.on_node_error` uses `format_exc()` which returns wrong traceback when called outside an active except block |
| compat.md | HIGH | 3 | `are_compatible` silently rejects valid connections between parameterized generic types and their plain base types |
| errors.md | MEDIUM | 0 | `ResumeError` re-export violates `Must NOT` contract and risks cascade import failure across the entire node system |

---

## Priority Findings (CRITICAL and HIGH only)

`[HIGH] base.md — Node.process_stream — Silently yields a coroutine object instead of a result dict when a subclass overrides process as async def; no exception raised, downstream nodes receive wrong data.`

`[HIGH] base.md — Node.on_start / on_end / on_error — Uses _current_run_id (never set) instead of _run_id; all observer calls silently receive run_id="" making run correlation impossible.`

`[HIGH] base.md — _install_siso_wrapper / _siso_process — Double-wraps result as {"output": {"output": ...}} when a SISO node with _siso=True has multiple output ports and returns a partial dict.`

`[HIGH] compat.md — CompatibilityChecker.are_compatible — Silently rejects valid connections between parameterized generic types (e.g. tuple[str, int]) and their plain base types (e.g. tuple) due to missing generalization of Rule 3b beyond list.`

`[HIGH] compat.md — CompatibilityChecker.are_compatible — issubclass() TypeError is silently caught and returns False, masking valid connections in Python < 3.10 for parameterized types.`

`[HIGH] compat.md — _type_to_schema — Returns {"type": "object", "title": "Any"} for typing.Any instead of {} (no constraints), producing incorrect JSON Schema in API responses.`

---

## Most Dangerous File

`base.md` — Contains three independent silent failures including an async bug that silently yields coroutine objects to downstream nodes, and a run_id attribution bug that makes all observer/monitoring logs permanently broken for run correlation.
