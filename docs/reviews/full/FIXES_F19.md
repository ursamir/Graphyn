# F19 — fixes for docs/reviews/full/SUMMARY.md

Branch `test/example-06-plugins` (not pushed). Author Samir Kumar Mishra (set via env). F-09 is owned by F20 (pack restores) and is out of scope here.

## Commits

| SHA | Title |
|---|---|
| `2a9d6a0` | F19.1: fix Mode B ArtifactRef materialize root (F-01) + unbound-name audit |
| `2e29807` | F19.2: project pipeline DELETE no longer 500s (F-04) |
| `88d4c63` | F19.3: run outputs listing regressions (F-12) |
| `710b2b6` | F19.4: stale isolation test + send_email jargon (F-07) |
| `d171e47` | F19.5: SSRF-safe egress by default (F-02) |
| `80e6a42` | F19.6: canonical inter-node payload contract (F-06) + llm_chat/structured_llm honesty (F-10/F-23), object_store put (F-11), csv_table symlink reads (F-19), python_code exceptions (F-24), merge/if_switch UX (F-25) |
| `d391d33` | F19.7: separation of duties on prod promotion (F-08) + shared-token actor attribution (F-20) |
| `16609f4` | F19.8: vitest as a pinned devDependency; npm test runs the local binary (F-13) |
| `a2e3b76` | F19.9: experiments compare reads per-path metrics (F-15) |
| `bd3d832` | F19.10: build provenance — build_stack.sh records git sha; runs flag missing commit (F-16) |
| `2337827` | F19.11: segmenter speaker_turn = real offline diarization (MFCC+pitch embeddings, agglomerative clustering) (F-17) — note: this commit also swept in F20's already-staged marketplace deletions (acknowledged in F20.7) |
| `39c619e` | F19.12: realtime_inference offers only audio-capable backends; vision options rejected with routing hint (F-18) |
| `07d9b19` | F19.13: real TFLM/Arduino/Zephyr/CMSIS-Pack edge outputs; drop stub backends (F-05) |
| `b486730` | F19.14: ship packages Ed25519-signed by default, runtime/format validated from content, prod needs a valid signature (F-14) |
| `f8cf084` | F19.15: graphyn --help no longer boots the plugin manager; prune registry records of removed packs; drop never-typed route builders; mypy except-name fixes (F-25) |
| `34e3a8e` | F19.17: /deploy/workers/queue deep link selects the Queue tab (URL tracks tab); Orgs panel surfaces members/users/usage/billing load errors (F18 carried) |
| `4e01dde` | F19.16: nodes declare run-critical config (send_email to, http url, csv path); validation warns VAL-REQ-CONFIG and execution refuses up front instead of a certain-to-fail run (F-25) |
| `232daf5` | F19.18: readiness worker_count counts live workers only (matches GET /workers); stale registrations reported as stale_worker_count (F-03) |
| `c937fbc` | F19.19: port types survive the catalog (list[AudioSample] no longer collapses to builtins.list), fixed-shape Common producers declare their real types, GET /nodes/check-connection + builder refuses incompatible wires; all plugin.toml declare runtime (F-22) |
| `8060afa` | F19.20: doc counts generated from what ships (scripts/sync_doc_counts.py: plugin.toml inventory + MCP tool registry, --check fails on drift); README/AGENTS/PLUGIN_GUIDE/NODES/ARCHITECTURE corrected (F-21) |
| `23f0182` | F19.21: F18 carried — OpenAPI response models for queue/slot/worker/job/org-quota endpoints (checked against live payloads); RT-CANCEL-003 consistent 409 run_cancelled for complete, blob upload and artifact commit after cancel |
| `2c55cfe` | F19.22: F18 carried UI — ink-400/500 meet WCAG AA 4.5:1 on light surfaces (contrast test incl. no muted text on dark ink); queue reasons and quota fields shown as human labels, no F18 jargon |
| `c7bc93d` | F19.23: serialise plugin venv create/install/remove with a cross-process flock — Mode B control + worker share the venvs dir and raced on a drifted venv (worker lost edge_optimizer live); gc skips .locks (F-03) |
| `ef51ced` | F19.24: non-finite floats never 500 the API — SafeJSONResponse is the app default (NaN/Inf → null), run journal writes strict JSON, evaluator omits an undefined ROC AUC instead of NaN (GET /runs 500 found live) |
| `211db0a` | F19.25: plugin venvs self-heal — a failed create leaves no half-built venv, a venv without pip is rebuilt, and remove() keeps a venv another container rebuilt after our boot (Mode B shared venvs; worker lost edge_optimizer live) |
| `3dac2d3` | F19.26: Mode B claim payload — worker_slots moves beside job (F18 nested it inside the strict NodeJob, so every remote job failed extra_forbidden; found live run 80159e9d); worker drops unknown job keys; ClaimResponse schema updated (F-03) |
| `337a358` | F19.27: distributed state store — separate queue/workers locks; one shared lock deadlocked the API live (queue mutator consults the worker registry while a heartbeat holds the registry lock and waits for the store) — all sync endpoints and worker claim/heartbeat hung (F-03) |
| `349813d` | F19.28: a requested cancel of a remote (Mode B) job logs INFO CANCELLED instead of ERROR FAILED — real node failures still log ERROR (clean container logs) |
| `ad2e344` | F19.29: F19 worker-route tests pin GRAPHYN_MTLS_ENABLED=0 (suite-order mTLS env leak made claim/blob calls 403 in the full run) |
| `4260958` | F19.30: clean container logs — mcp_tool_call works without the optional MCP SDK (only the stdio server needs it; live 'No module named mcp'), python_code sees csv_table results as rows (live "'tuple' object has no attribute 'get'"), a 409 completion is logged as an expected drop, isolated plugin failures log one WARNING line (traceback stays in the run journal) |
| `6779482` | F19.31: test_worker_join restores os.environ (worker join's GRAPHYN_MTLS_* leaked into later Mode B CLI tests when run out of alphabetical order) |
| `4053714` | F19.32: a node failing only for missing credentials (NeedsCredentialsError, incl. chained / isolated) logs WARNING 'FAILED (needs credentials)' instead of ERROR — operator setup state, not a platform fault; the run still fails with the full message |
| `afd7b44` | F19.33: ENTERPRISE_READINESS F19 section (Mode B re-verified live on Server-99 with run ids, live-only defects fixed, SoD/attribution, honest limits) + changelog rows; KNOWN_ISSUES DIST-ORPHAN-1 and SEG-DIAR-1 |
| `9f97d5c` | F19.34: prune suite tests that targeted removed packs (F-07) — pack-first MCP tests use shipped Audio/trainer and the current KWS template id; marketplace pack filter uses Agents (Vision/RAG are not shipped on this branch) |


## Per-finding status

| Finding | Sev | Status | Commits | Tests / live evidence |
|---|---|---|---|---|
| F-01 Mode B ArtifactRef root unbound | P0 | Fixed | F19.1 | unit tests; live Mode B runs 253a84b3, 9067c850, 2561e0bc, c3af9b75 (artifacts handed both ways) |
| F-02 SSRF open by default | P0 | Fixed (default `restricted`) | F19.5 | live: run 1fee1a03 (127.0.0.1:8001 blocked), 12fedb78 (169.254.169.254 always denied) |
| F-03 Mode B not operational | P1 | Fixed + live-verified | F19.18, F19.23–F19.28, F19.30 | readiness ready/distributed/worker_count 1; worker `s99-ml` 9 node types; runs above, queue `used_slots 1 busy`; RT-CANCEL 5f3f54db |
| F-04 pipeline DELETE 500 | P1 | Fixed | F19.2 | unit; live delete of review-del-test |
| F-05 stub backends report success | P1 | Fixed (stubs dropped, real TFLM/Arduino/Zephyr/CMSIS outputs) | F19.13 | unit tests; not re-run on the rebuilt stack |
| F-06 payload contract | P1 | Fixed | F19.6, F19.30 | unit; live csv→python_code acb011aa, chain 2f1fb28d |
| F-07 suite red | P1 | Fixed | F19.4, F19.29, F19.31, F19.34 | full suite numbers below (removed-pack tests re-pointed in F19.34) |
| F-08 no SoD on prod promotion | P1 | Fixed | F19.7 | unit (`403 separation_of_duties`, audited `sod_waived`); not re-run live after rebuild |
| F-09 template catalog | P1 | **F20** (out of F19 scope) | — | — |
| F-10 llm_chat `local` echo | P1 | Fixed (honest provider; ollama local LLM) | F19.6 | live 694fa734 (ollama tinyllama, is_llm true) |
| F-11 object_store put no-op | P1 | Fixed | F19.6 | live 31e556d6 |
| F-12 run outputs listing | P2 | Fixed | F19.3 | unit |
| F-13 UI npm test broken | P2 | Fixed | F19.8 | npm test numbers below |
| F-14 unsigned ship packages | P2 | Fixed (Ed25519 by default, content-validated) | F19.14 | unit; not re-run live after rebuild |
| F-15 compare shows no metrics | P2 | Fixed | F19.9 | live compare metric_keys test_accuracy, roc_auc |
| F-16 no build provenance | P2 | Fixed | F19.10 | BUILD_INFO git_sha + run meta git_commit = image sha |
| F-17 speaker_turn placeholder | P2 | Fixed (offline diarization; limits in KNOWN_ISSUES SEG-DIAR-1) | F19.11 | live a5bc4c40 |
| F-18 realtime ultralytics/auto for audio | P2 | Fixed | F19.12 | unit |
| F-19 csv_table symlinked datasets | P2 | Fixed | F19.6 | live 160ae3e8 |
| F-20 weak actor attribution | P2 | Fixed (shared token → `GRAPHYN_API_TOKEN_ACTOR`, flagged unverified; named tokens/OIDC attribute individuals) | F19.7 | unit |
| F-21 docs count drift | P2 | Fixed (generated, `--check`) | F19.20 | sync_doc_counts --check exit 0 |
| F-22 manifests/typing | P3 | Fixed | F19.19 | live check-connection compatible false/true |
| F-23 structured_llm fake extraction | P3 | Fixed (honest rule-based) | F19.6 | unit |
| F-24 python_code exceptions | P3 | Fixed | F19.6 | live 50251e72 |
| F-25 UX/honesty nits | P3 | Fixed | F19.6, F19.15, F19.16 | live send_email without `to` → 422 VAL-REQ-CONFIG |
| F18 carried | — | Fixed | F19.17, F19.21, F19.22 | OpenAPI ClaimResponse live; RT-CANCEL-003 live; contrast test |
| Live-only defects (logs) | — | Fixed | F19.23–F19.32 | final clean-log check below (0 / 0) |




## Test numbers

**Final run: backend suite at tip `46df6b1`** (nohup, `/tmp/f19/full5.log` + junitxml):
- 3481 passed, 4 failed, 39 skipped (170.6 s).
- The 4 failures targeted removed packs (Vision `yolo_train`, `mcu_flash_ota`, the old `tpl-audio-kws-smart-home` id, and the `RAG` pack filter).
- F19.34 (`9f97d5c`) re-pointed those 4 tests at shipped packs: 8/8 passed in those two files. That makes the expected full-suite result **3485 passed, 0 failed, 39 skipped**. The whole suite was not re-run after this test-only commit.

**UI at the same tip:**

| Check | Result |
|---|---|
| `tsc -p tsconfig.app.json --noEmit` | exit 0 |
| `npm test` | 70 files / 548 tests passed |
| `vite build` | exit 0 |

**Earlier run at `4053714`:** 3486 passed, 14 failed, 39 skipped. 10 of those failures were F20's in-progress example06 deletions; they are gone now that F20.14 is committed.

`sync_doc_counts --check` exits 0.

## Live Mode B (image `6779482`, the F19.31 tip; re-checked on the final image afterwards)

| Run | Result | Notes |
|---|---|---|
| `9067c850` | succeeded 173.9 s | Mode B handoff: ff / tr / eo on `s99-ml`; verify pass; meta git_commit set |
| `2561e0bc` | succeeded 30.8 s | Queue showed `s99-ml used_slots 1, status busy` (F18 slots) |
| `c3af9b75` | succeeded 36.6 s | Same; fmax bust |
| `5f3f54db` | cancelled 22.1 s | RT-CANCEL-003: worker terminated the process group; completion dropped with `"result for … dropped: … 409 (run_cancelled)"`; API logged INFO CANCELLED |
| Earlier (image `3dac2d3`) | `253a84b3` succeeded 67.8 s | Full local↔worker handoff + sealed verify |

### Final image `newaudio3-graphyn-api:46df6b1f30b6`

Built by `scripts/build_stack.sh` at about 19:17 IST, after F20.16. BUILD_INFO git_sha is `46df6b1` in both api and worker. The UI image was rebuilt from cache and the container was unchanged.

- readiness: ready / distributed / worker_count 1 / stale 0 / node_type_count 76. Worker registry ready with 9 node types.
- Mode B `4cd4d501` **succeeded** in 51.0 s.
  - ff, tr and eo ran on `s99-ml` (jobs 3589a8f4, 10ab0cf3, 68255e25); the queue showed `used_slots 1, busy`.
  - verify passes; meta git_commit is 46df6b1.
- csv→python_code `c0702384` succeeded.
- mcp_tool_call `6de416b6` logged a WARNING for needs-credentials.
- `GET /runs?limit=60` returns 200 (60 runs). OpenAPI `/jobs/claim` → ClaimResponse.
- Final clean-log check (19:24 IST, `docker logs --since 20m`, back to the restart at about 19:19 IST):
  - graphyn-api: **0** lines matching `ERROR|Traceback| 500 `.
  - graphyn-worker: **0** lines matching `ERROR|Traceback|failed`.
  - The WARNINGs are only mcp needs-credentials, artifact_pack host-path scrubbing (Mode B) and a pipeline_cache non-serializable port.

### Image `newaudio3-graphyn-api:4053714b3de9`

- readiness: ready / distributed / worker_count 1 / stale 0 / node_type_count 76. Worker `s99-ml` registers 9 node types.
- Mode B `3338d56a` **succeeded** in 69.2 s.
  - ff, tr and eo ran on `s99-ml` (jobs 0e4786c8, d73d1734, f4b9d7c2); the queue showed `used_slots 1, busy`.
  - verify passes; meta git_commit is 4053714.
- csv→python_code `422b6c3a` succeeded.
- mcp_tool_call `105ff487` now gets past the import. It then fails only because no `graphyn_mcp` credential is configured, which is logged as WARNING `FAILED (needs credentials)`.
- Final log check (19:08 IST): `docker logs --since 20m`, which reaches back to the container restart at about 19:04 IST.
  - graphyn-api: 0 lines matching `ERROR|Traceback| 500 `.
  - graphyn-worker: 0 lines matching `ERROR|Traceback|failed`.
  - The only WARNINGs are the mcp needs-credentials line and artifact_pack "host path(s) not transferable … cleared". The latter is expected Mode B metadata scrubbing.

Live after F19.30 (python_code rows): run `acb011aa` (old csv→python_code template source) **succeeded**.

## What was created on the live stack

- Project `review-full-2026-10-08` Mode B artifacts under `workspace/artifacts/review-full-2026-10-08/…`
- Cancelled orphan run `35d43e94` (DIST-ORPHAN-1)
- SSRF probe runs `1fee1a03`, `12fedb78`
- Many F20 marketplace template review runs (csv transform, wakeword, asr, etc.)

## Not fully live-reverified after the final rebuild

- SoD 403 / `sod_waived` (covered by F19.7 unit tests)
- Ship signing / verify (F19.14 unit)
- Arduino / Zephyr / CMSIS-Pack edge targets (F19.13 unit)
- Console screenshots / WCAG live UI (F19.22 unit + vitest)

- SSRF was not re-probed on the final image. Doing so would deliberately write an ERROR line, and the egress code is unchanged since F19.5. Evidence is runs `1fee1a03` / `12fedb78` on image 349813d.
- check-connection and VAL-REQ-CONFIG evidence comes from image 349813d. The final-image probe used wrong request shapes, so it is not counted.

## Notes

- The API ERROR at 19:09 IST (raised by the user at 19:12) came from F20's wakeword-detect template smoke, run `0559ad55`: `wakeword_infer` found no model at `workspace/models/wakeword/...`. F20.15 / F20.16 fixed the template hand-off path. It was not an F19 code path, and it falls outside the final log window.
- F20 run `ce9abbd6` was active when the final rebuild recreated api/worker at about 19:19 IST.

- **F19.11** accidentally included F20's already-staged marketplace deletions; acknowledged in F20.7.
- Earlier in the session the box docker builder was pruned (`docker builder prune --filter until=168h`, reclaiming ~1.18 GB; a possible second prune with `until=48h` may also have run). Not part of the F19 deliverable; disclosed here as requested.
- F20 path list was never edited, staged or deleted by F19.
- FaceRecognition and the six non-Graphyn containers were not touched. SMTP stayed dry-run; no paid LLM calls; no real outbound sends.
