# Group Review Index — 9: SDK & CLI

**Files reviewed:** 2
**Total findings:** 17 (CRITICAL: 0 | HIGH: 5 | MEDIUM: 7 | LOW: 5)
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| sdk.md | HIGH | 3 | _execute() leaves _last_run_id stale after a failed run, causing pause/resume/cancel to silently target the wrong run |
| main.md | HIGH | 2 | cmd_run seed-override path bypasses RunManager entirely, making seeded runs invisible to the run journal and artifact store |

---

## Priority Findings (CRITICAL and HIGH only)

**[HIGH] sdk.py — Pipeline._execute — Stale _last_run_id after failed run**
After get_backend().execute() raises, self._last_run_id is not updated. Subsequent calls to
pause()/resume()/cancel() silently target the previous successful run instead of the failed one.

**[HIGH] sdk.py — Pipeline._build_ir — No bounds check on explicit edge indices**
When edges=[(src_idx, port, dst_idx, port)] is provided, out-of-range indices raise a confusing
IndexError with no indication of which edge is invalid. Should raise a clear ValueError.

**[HIGH] main.py — main — No KeyboardInterrupt handling**
Ctrl+C during any long-running subcommand (especially cmd_run) produces a raw Python traceback
instead of a clean "Interrupted." message. The run journal may be left with status "running"
permanently.

**[HIGH] main.py — cmd_run — Seed-override path bypasses RunManager**
When --seed is provided, cmd_run calls get_backend().execute() directly without creating a
RunManager. The run is not persisted to the run journal, artifacts are not stored, and the run
is invisible to `graphyn runs list` and `graphyn artifacts list`.

**[HIGH] main.py — cmd_artifacts_replay — No partial run ID matching**
cmd_artifacts_replay does not support partial run ID prefix matching (unlike cmd_runs_logs).
A partial run ID produces a misleading "graph.json not found" error instead of "run not found".

---

## Most Dangerous File

main.md — The seed-override path in cmd_run silently bypasses the entire observability layer
(RunManager, artifact store, run journal), making seeded runs completely invisible to the
platform. Combined with the missing KeyboardInterrupt handler, the CLI has two HIGH-severity
correctness gaps that affect every user who uses --seed or presses Ctrl+C.
