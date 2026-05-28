# Known Issues

> **Single source of truth:** `docs/MASTER_ISSUE_REGISTRY.md`  
> This file lists only currently open issues for quick reference.  
> For full history, fix details, and resolved issues see the registry.

All confirmed bugs found during the 104-file review pass (May 2026) have been fixed. The codebase is in a clean, production-quality state.

---

## Open — Fix Immediately (before next deployment)

No open issues in this tier.

---

## Open — Fix This Sprint

No open issues in this tier.

---

## Open — Fix When Touching the File

No open issues in this tier.

---

## Open — Deferred (Architectural Work Required)

### SCALE-3 — `run-async` status tracking uses `meta.json` polling

**File:** `app/api/routers/pipelines.py` → `GET /api/v1/runs/{run_id}/status`  
**Severity:** Low (functional, but suboptimal under high concurrency)  
**Detail:** The `run-async` endpoint starts execution in a background thread. Status is read from `meta.json` on disk, which is written atomically by `RunManager`. This is correct and safe for single-worker deployments. Under high concurrency with many simultaneous async runs, repeated `meta.json` reads may become a bottleneck. The proper fix is a lightweight in-memory status cache keyed on `run_id`, invalidated when `deregister_active_run` is called. This requires coordinating `run_control.py` and the status router, which is non-trivial to do safely without introducing race conditions.  
**Workaround:** Use `GET /api/v1/runs/{run_id}/status` polling at ≥500ms intervals. The endpoint is fast (single file read) and correct.

---

## How to Report

1. Add the issue to `docs/MASTER_ISSUE_REGISTRY.md` in the correct priority section and update the Quick Reference table.
2. Add a row to the matching priority tier in this file.
3. Reference the source file and line number where the issue lives.
4. Include a workaround if one exists.
