# F19 progress notes (resume here)

Updated: 2026-10-08 19:35 IST. Tip is `e195355` (F20.17; F20 DONE). My last commit is F19.34 `9f97d5c`.

## Phase 2 (requested 19:25 IST): nothing committed yet
- [ ] DIST-ORPHAN-1. On startup and every 30 s, a sweep marks runs orphaned when they have no live owner.
  - Ownership stamp: boot_id plus a heartbeat file.
  - Jobs from orphaned runs are cancelled. The run is marked failed with `orphaned_by_restart`, plus an audit event and the reason shown in the UI.
  - Queue reclaim respects node idempotency and the IR retry policy.
- [ ] SEG-DIAR-1. ECAPA (speechbrain `spkrec-ecapa-voxceleb` is cached on the host at ~/.cache/huggingface) by default, with MFCC as the fallback.
- [ ] F20_REQUESTS that fall in F19 paths: #12 model_path scoping, #10 materializer, #4 isolated_schema lambda, #5 memmap, #6 dict helper, #13 CLI validate venvs, #11 UI catalog, #9 guardrail policies, #3 torch CPU index, #8 espeak-ng, #2 allowlist.
- [ ] Wait until no runs are `running`, then run build_stack.sh. Live re-verify SSRF, SoD, ship signing, edge, check-connection, VAL-REQ-CONFIG, orphan restart, realtime, speaker_turn and actor attribution.
- [ ] Full suite, npm test, tsc, vite build, final log check. Update FIXES_F19.md, KNOWN_ISSUES and ER.

Helpers on Server-99 (recreated): /tmp/f19/commit.sh, /tmp/f19/env.sh (fnm node 22), /tmp/f19/live_lib.py.

---
## Phase 2 wrap-up (WRAP UP requested by the parent at 19:43 IST, no rebuild or restart done)

### DONE (committed on test/example-06-plugins; nothing pushed)
- bdfe8a7 F19.35: when a Mode B lease is lost, the job is requeued only if the node is idempotent and its IR retry policy allows another attempt (`max_attempts = retry.max_attempts - 1`). Otherwise it fails clearly. This covers the durable path, the in-memory path (now through the snapshot) and worker re-register. NodeMetadata.idempotent defaults to True; send_email and http_webhook are False; http_request uses `idempotent_for(config)`, so only GET/HEAD/OPTIONS are retried. Test: unit_test/f19/test_f19_lease_idempotency.py (10 pass). 664 related tests pass.
- d945d16 F19.36: DIST-ORPHAN-1. New app/core/runs/orphans.py.
  - Each RunManager writes an owner stamp into meta and keeps `<run>/.owner.json` heartbeated every 10s.
  - The main.py lifespan sweeper runs once at startup, then every 30s (GRAPHYN_ORPHAN_SWEEP_S; skipped under pytest or GRAPHYN_SKIP_ORPHAN_SWEEP).
  - An owner counts as dead when the pid is gone or reused (different proc start time), the heartbeat is stale (60s), or a legacy run without a stamp predates the process.
  - A dead owner's run becomes failed with `error_type`/`reason` `orphaned_by_restart`, gets a journal error event, a prove seal and audit `run.orphaned`. Its pending/claimed jobs are cancelled (new `queue.active_job_ids_for_run`) and expired leases are reclaimed. If a cancel had been requested, the run becomes cancelled instead.
  - Test: unit_test/f19/test_f19_orphaned_runs.py (8 pass, Mode A and Mode B). unit_test/f19 total: 148 pass, 1 skip. 510 RunManager/meta-related tests pass.
- 22ffcac F19.37: the UI shows "Orphaned by restart: …" in the run banner and run list (runRecord.ts failureView label, runNodes.ts errorType). runOrphan.test.ts plus the runs tests pass (51).

### IN PROGRESS (see the IN-PROGRESS status line appended below)
- F20 req #12 (model_path run-scoping): patch /tmp/f19/up/p38.py (box copy: /workspace/f19/p/p38.py) plus unit_test/f19/test_f19_model_path_inputs.py. An existing `model_path` file that no sink in the graph produces is left in place.
- F20 req #10 (materializer cleanup): patch p39.py drops the rag/vision/mcu/yolo/ship branches and the mcp_tool_call `stub` setdefault.
- Not yet written (design notes only):
  - #4: isolated_schema `_eval_field_default`. Evaluate `default_factory=lambda: <literal>` from the lambda body instead of `[]`.
  - #5: memmap. In recast_plugin_types, return `np.asarray(obj)` for numpy.memmap before pickling (worker.py:90 and isolated_executor:809).
  - #6: payload helper for pydantic models arriving as dicts.
  - #13, #11, #9, #3, #8, #2, #7.

### NOT STARTED
- SEG-DIAR-1 (ECAPA default with MFCC fallback).
- Rebuild api/ui/worker via scripts/build_stack.sh with GRAPHYN_GIT_SHA. Only when no runs are `running`.
- Live re-verifies on the final image:
  - SSRF loopback/metadata (note the timestamps)
  - SoD 403 / different-actor success
  - ship signing / verify / tamper / runtime_format_mismatch
  - edge_optimizer tflm, deployment_packager arduino/zephyr/cmsis_pack
  - check-connection, VAL-REQ-CONFIG 422
  - orphan: restart graphyn-api during a Mode B run (recreate /tmp/f19/modeb.json from run 4cd4d501's graph.json, bump ff fmax past 7990) and expect `orphaned_by_restart` plus audit `run.orphaned`
  - realtime_inference, segmenter speaker_turn
  - actor attribution
- Full backend suite (nohup + log), npm test, tsc, vite build.
- Final clean-log check for api and worker.
- Doc updates:
  - FIXES_F19.md: rebuild with /workspace/f19/stage/mkfixes.py and add F19.35–37.
  - KNOWN_ISSUES: DIST-ORPHAN-1 is fixed in code but not yet live.
  - ENTERPRISE_READINESS.
- Delete /tmp/gb99 and /tmp/f19 at the very end. /tmp/f19 holds the helpers, so it is kept for now.
- NOTE: the running image is still the phase-1 image (46df6b1). F19.35–37 are NOT live until the rebuild.
- IN-PROGRESS status (#12/#10): DONE: F19.38 committed (dbdf542 ): #12 and #10
- tip: dbdf542 F19.38: run-scoping leaves an existing model_path input in place (F20 req #12); materializer drops removed-pack branches and the mcp stub (F20 req #10)
