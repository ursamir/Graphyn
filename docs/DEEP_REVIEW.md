# Graphyn — Deep Project Review

**Reviewed commit:** `b178b39` (branch `cursor/usecase-plugins-workflows`) · **Date:** 2026-09-16
**Scope:** `app/` (40k LOC) · `graphyn-ui/src/` (16k) · `PluginPackage/` (23k) · `unit_test/` (1684 tests) · `docs/` · `examples/` · build & deploy

**How to use this document.** Findings are ordered by fix wave (P0 → P3), not by subsystem. Each entry names the files and lines to open, what is wrong, and the fix. Work top-down: P0 items unblock the ability to verify anything else. Every claim here was reproduced against the source; claims that did not survive re-checking were dropped and are listed in [Appendix B](#appendix-b--checked-and-found-sound) so they are not re-investigated.

---

## 1. Verdict

The architecture is genuinely good and the engineering discipline is real in places — zero module-level import cycles, a clean platform/domain separation that actually holds, correct cross-process CAS on the distributed job claim, working path jails, a sound secret store. This is not a prototype wearing a framework.

The problem is that **the correctness layer is not backed by a working verification loop**, and defects have accumulated behind it. 141 of 1684 tests are broken. CI exists but executes 23 of them. The result is a system where the parts that are *checked* are solid and the parts that are *not checked* have silently rotted — and the rot is concentrated in the highest-value claims the product makes: conditional branching, caching, resume, distributed execution, and artifact lineage.

Three things are individually serious enough to block a release:

1. **The pickle allowlist is not an allowlist.** `builtins` is allowlisted wholesale, so `builtins.eval` passes the filter — remote code execution on the control plane from any plugin worker or blob-store entry.
2. **Conditional branching does not work.** A false condition skips one node but not its descendants, which then execute on `None`. Example 27 posts a GitHub comment on both branches.
3. **The cache returns wrong data.** Two independent defects: keys collide across entirely different datasets, and `save()` silently drops ports so a cache hit returns a truncated output dict.

None of these are exotic. All three are invisible precisely because the tests that would catch them are among the 141 that do not run.

**Biggest risk to shipping:** the failure mode of this codebase is *silent wrong results*, not crashes. A skipped node runs, a cache hit returns another corpus's data, a failed event-driven run is stamped `completed`, a Mode B job executes twice. Users will not see errors; they will see plausible output that is wrong.

---

## 2. Measured baseline

Facts, not estimates — commands run against the working tree.

| Check | Result |
|---|---|
| `pytest unit_test/ -q` | **92 failed, 1541 passed, 2 skipped, 49 errors** (141 broken / 1684) in 54s |
| Reproducibility | Byte-identical across runs; also reproduces in a pristine `pip install -e ".[dev]"` venv — a repo defect, not a local venv artifact |
| `import app`, `app.api.main`, `app.mcp.server`, CLI `--help` | all exit 0 |
| `scripts/check_deps.py` | exit 0, but prints `EXTRA in requirements.txt: faster-whisper` and exits 0 anyway |
| `scripts/_import_smoke.py` | exit 1 in repo venv (project never `pip install -e`'d there); exit 0 in a clean venv |
| `tsc --noEmit` (both configs) | exit 0 |
| `vite build` | exit 0 (1979 modules, 690.68 kB JS) |
| `npm run build` | exit 1 — `TS5033 EACCES`, `node_modules/.tmp` and `dist/` owned by root |
| `npx oxlint` | 0 errors, 9 warnings |
| Python lint / types | **none configured or installed** — no ruff, flake8, mypy, pylint; no `pyproject.toml`, `setup.cfg`, `mypy.ini` |
| CI | `.github/workflows/ci.yml` exists, runs `scripts/ci_smoke.sh` → **23 of 1684 tests**, with `GRAPHYN_SKIP_PLUGIN_LOAD=1` |

**Test failures cluster into two root causes (~100 of 141):**

| Count | Root cause |
|---|---|
| ~60 | `NodeNotFoundError: Node type '<x>' is not registered` — `PluginManager.install()` early-returns without registering node types (P0-2) |
| ~21 | `RuntimeError: Isolated node '<x>' must not run in-process` |
| 18 | `ValueError: Unknown node type 'audio_conditioner'` |
| 2 | `PluginIndexError` from a **live network call to example.com** in unit tests |

> **Note:** the suite regressed during this review. Commits `0f19cf0` and `b178b39` landed mid-audit and moved failures from 57 → 92. `.github/workflows/ci.yml` was also added mid-audit. Re-measure before starting.

---

## 3. Cross-cutting themes

Five root causes explain most of the findings. Fixing these structurally is worth more than fixing entries one at a time.

**T1 — `None` is overloaded to mean "not produced".** The runtime has no distinct signal for an unproduced port, so a skipped branch is indistinguishable from a node that legitimately returned `None`. This single ambiguity produces P1-1, P1-2 and P1-3. *Fix:* introduce an explicit unproduced-port signal (omit the key from the output dict) and a `skipped: set[str]` propagated transitively.

**T2 — Two execution paths that were never kept in sync.** The sequential loop is the reference implementation; the parallel executor, the event-driven loop and `DistributedBackend` each re-implement a subset and silently drop the rest — filters, `input_overrides`, resume state, `wait_if_paused`, run finalization, cache, checkpoint. *Fix:* extract the per-node decision (skip / resume / override / pause / cancel) into one shared helper all four paths call, and make dropped parameters raise rather than be ignored.

**T3 — Defensive `except` that converts corruption into silent empty state.** ~200 `except Exception` blocks in `app/`, ~77 followed by `pass`. The damaging pattern is not the catch but the *write-back*: a corrupt index is read as `[]`, then persisted as `[]`, destroying data permanently. *Fix:* quarantine-then-rebuild on parse failure; never persist a recovered-as-empty collection.

**T4 — No verification loop.** No Python linter, no type checker, CI covering 1.4% of tests, tests making live network calls. Nothing mechanically prevents any of the above from recurring. *Fix:* P0-4.

**T5 — Docs assert counts and behaviour nobody checks.** Node counts, route lists, nav structure and env vars are hand-maintained and have drifted. *Fix:* generate the counts and route tables from code in CI.

---

## 4. P0 — Blockers

*Nothing else can be validated until these land.*

### P0-1 · `RestrictedUnpickler` allowlists all of `builtins` → control-plane RCE
**`app/core/plugins/isolated_executor.py:57-90`** · also reached via `distributed/transfer.py:81-90`, `distributed/backend.py:449`

`_ALLOWED_PICKLE_MODULES` contains the bare string `"builtins"`, and `find_class` returns `super().find_class(module, name)` for *any* name in an allowlisted module. `builtins` exports `eval`, `exec`, `getattr`, `__import__`. A pickle whose `__reduce__` returns `(eval, ("...",))` passes the filter — verified by execution.

Untrusted inputs that reach it: an isolated plugin worker's `outputs.pkl` (third-party code in its own venv), and content-addressed blobs fetched for `result.output_refs` — which any caller can write via `POST /api/v1/artifacts/blob?key=…` (`api/routers/workers.py:203-225`). This defeats exactly the control `docs/TRUST_MODEL.md` §5 relies on.

**Fix:** replace the module-level entry with a name-level allowlist:
```python
_ALLOWED_BUILTINS = frozenset({"bool","bytearray","bytes","complex","dict","float",
                               "frozenset","int","list","set","str","tuple","object","NoneType"})
# in find_class, before delegating:
if module == "builtins" and name not in _ALLOWED_BUILTINS:
    raise pickle.UnpicklingError(f"Refusing builtins.{name}")
```
Apply the same name-level narrowing to `collections`, `copyreg`, `pathlib`, `numpy.core.multiarray`. Add a regression test asserting `pickle.dumps((eval, ("1",)))` raises. **Effort: S**

### P0-2 · `PluginManager.install()` returns early without registering node types
**`app/core/plugins/manager.py:204-211`** (also `:152`, `:300`)

When the plugin is already in the store and `upgrade` is not set, `install()` returns the existing record *before* calling the loader — so zero node types are registered into `self._registry`. This is the single largest cause of the red suite (~60 failures) and it also breaks the documented SDK/REST contract: `docs` says `PluginAlreadyInstalledError` is raised (manager.py:144-145, :176-179), the code returns success, and `POST /api/v1/plugins` reports `"installed"` while the registry stays empty.

**Fix:** before `return existing`, call `self._loader.load(Path(existing.install_path))` so node types register, mirroring Step 7 at `manager.py:300`. Then honour the documented contract — raise `PluginAlreadyInstalledError(name, existing.version)` so the API's 409 path works again. **Effort: S**

### P0-3 · Test fixture destroys the global `NodeRegistry` singleton and never restores it
**`unit_test/core/nodes/test_initialize_registry.py:47,52,165,180`**

`_reset_nodes_package()` clears `registry._classes`, `_metadata`, `_plugin_ui_fields` and `nodes_pkg._initialized` with no teardown, so every test that runs afterwards in the same process sees an empty registry. Deleting this one file alone drops failures 57 → 23.

**Fix:** convert to a `yield` fixture that snapshots all four attributes on entry and restores them in teardown. **Effort: S**

### P0-4 · CI exists but gates 23 of 1684 tests, so the red suite is invisible
**`.github/workflows/ci.yml`** → **`scripts/ci_smoke.sh:14,16,21`**

`ci_smoke.sh` sets `GRAPHYN_SKIP_PLUGIN_LOAD=1` globally, then runs seven named files plus two plugin-smoke files. It exits 0 today while 141 tests are broken — structurally incapable of catching any of them. CI also pins Python 3.11 while development is on 3.12.

**Fix:** run the full suite — `pytest unit_test/ -q` — and set `GRAPHYN_SKIP_PLUGIN_LOAD=1` only for the isolation tests that require it. Add `ruff` and `mypy` (even in non-blocking report mode initially) since neither exists. Align the CI Python version with the dev version. Land P0-2/P0-3 first so the gate can start green. **Effort: M**

### P0-5 · Unit tests make live outbound network calls
**`unit_test/core/plugins/test_index.py:54,80,92`** · **`unit_test/plugins/audio/test_audio_classifier.py:96`**, **`test_audio_event_detector.py:72`**

A real TCP connect to `example.com` and an 18 MB download from `tfhub.dev` (301s on a cold cache). The `test_index.py` patches target `httpx.get` but `index.py:248` uses `httpx.stream`, so the mock never applies. The YAMNet-backed tests are also non-deterministic — same test passes one run, fails the next.

**Fix:** repoint the patches to `app.core.plugins.index.httpx.stream` with a context-manager mock; mock `tensorflow_hub.load` in the audio tests so they assert the node's own contract rather than model behaviour. **Effort: S**

---

## 5. P1 — Silent wrong results and data loss

### P1-1 · Condition-false skip is not transitive — descendants execute on `None`
**`app/core/orchestrator.py:448-469`, `:411-446`** · repro: `examples/12_conditional_branching/pipeline.graph.json`

A node skipped for `condition_false` is recorded, but nothing marks its *descendants*. They are scheduled normally and receive `None` for the unproduced input, because `None` is indistinguishable from a real `None` output (theme T1).

**Fix:** maintain `skipped: set[str]` alongside `node_outputs`. During input assembly, treat an edge whose `src_id` is in that set exactly like a false condition, and propagate the skip transitively. **Effort: M**

### P1-2 · `if_switch`'s false branch still runs — example 27 posts a GitHub comment either way
**`app/core/orchestrator.py:448-477`** · `PluginPackage/Common/if_switch/nodes.py:110-116` · `examples/27_github_triage/pipeline.graph.json`

Same root cause as P1-1, with an externally visible side effect: the triage example POSTs to GitHub on both branches.

**Fix:** have branch-style nodes *omit* unselected keys from their output dict, and treat `src_port not in node_outputs[src_id]` as unproduced. **Effort: M**

### P1-3 · Parallel executor evaluates edge conditions but never skips the node
**`app/core/executor.py:216-245`** vs `orchestrator.py:448-469`

`_run_node` computes the condition and then runs the node anyway, passing `None`.

**Fix:** extract the skip decision from `orchestrator.py:450-469` into a shared helper called by both `_run_node` and the sequential loop; on skip set `node_outputs[node_id] = {}`, emit `logger.node_skip(...)`, return early. **Effort: S**

### P1-4 · `--parallel` silently ignores `--include-nodes`, `--exclude-nodes`, `--input-overrides` and `--resume`
**`app/core/orchestrator.py:286,311,354,406,464,742`** · `app/core/executor.py:73,154`

`active_nodes`, `completed_nodes` and `input_overrides` are consumed **only** in the sequential loop. `ParallelExecutor.run_wave` and `_run_node` have no such parameters and iterate the full unfiltered wave. The finalizer still writes `{"partial_execution": true, "included_nodes": [...]}` into `meta.json`, so the journal asserts a partial execution that never happened.

Concretely: `graphyn run --parallel --exclude-nodes train` retrains the model, overwrites exported artifacts and burns GPU time — then reports success.

**Fix:** thread all three into `run_wave`/`_run_node` and apply the same passthrough wiring the sequential path uses at `orchestrator.py:360-373`. **Until that lands, raise `ValueError` when `parallel=True` is combined with any of them** rather than producing wrong results. **Effort: M**

### P1-5 · Cache key collides across completely different datasets
**`app/core/pipeline_cache.py:145-150, 180-190, 110-114`**

`input_hash()` calls `json.dumps([item.model_dump(mode="json") ...])`; a `FeatureArray` holds a numpy array on an `Any` field, so pydantic raises, the bare `except Exception: pass` swallows it, and the function returns `""`. The comment claims the empty hash "is effectively random, which forces a cache miss" — the opposite is true: `""` is constant, so `compute_key()` reduces to `sha256(node_type + config)` with the input data contributing **nothing**. Verified: two `FeatureArray` lists with different shapes, labels and source paths produced the identical key `be1f1295…`.

`DatasetBuilderNode` is `cacheable=True` with a `list[FeatureArray]` input and `use_cache` defaults to `True` — so run 2 over corpus B silently trains on corpus A's dataset.

**Fix:** in `input_hash()`, add a branch for Pydantic models carrying arrays — fold `arr.shape`, `arr.dtype.str` and `sha256(arr.tobytes())` into the digest. Separately make the last-resort path at `:190` return `uuid4().hex` instead of `""` so an unhashable input genuinely forces a miss. **Effort: M**

### P1-6 · `PipelineCache.save()` discards every JSON-only port when any port is registry-serializable
**`app/core/pipeline_cache.py:355-398, 400-432`** · `app/core/orchestrator.py:490-492`

The early `return` at `:398` means mixed-type nodes write only the manifest, never `outputs.json`. A subsequent cache hit returns a truncated output dict — downstream nodes receive fewer ports than the node actually produced.

**Fix:** delete the `return` at `:398` so both files are written, and change `load()` to merge both sources instead of short-circuiting on `outputs.json` at `:238-249`. **Effort: M**

### P1-7 · Cache key omits node seed and node version
**`app/core/pipeline_cache.py:110-120`** · `app/core/planner.py:230`

Changing a seed or upgrading a plugin returns the old cached output.

**Fix:** hash `graph_obj.get_node(node_id).seed` and `NodeMetadata.version` into `key()`. **Effort: S**

### P1-8 · Cross-run checkpoint lookup is keyed by `node_id` alone
**`app/core/checkpoint.py:178-201, 204-254, 256-304`**

Two unrelated pipelines that share a node id resume from each other's checkpoints.

**Fix:** key the index by graph identity too — `<runs_dir>/checkpoints/<graph_hash>/node_<node_id>/latest_run`. **Effort: M**

### P1-9 · `_write_checkpoint` drops non-list ports; resume treats the partial checkpoint as complete
**`app/core/checkpoint.py:110-128`** · `app/core/orchestrator.py:272-287, 361-364`

**Fix:** record `"all_ports": sorted(outputs.keys())` in the manifest and have `_load_checkpoint_outputs` return `None` when the checkpointed set ≠ all ports, forcing re-execution. **Effort: S**

### P1-10 · Event-driven run that failed or was cancelled is stamped `completed` and notified as success
**`app/core/orchestrator.py:655-660, 606-607, 709-718`**

**Fix:** track terminal state where `mark_failed` and the cancel-break occur, and at `:710` skip `save_metadata` or pass an explicit `status`. **Effort: S**

### P1-11 · Worker never renews its lease while executing → jobs longer than 60s run twice
**`app/cli/main.py:1544-1558, 1600-1634, 1423-1432`** · `app/core/distributed/queue.py:38, 418-424`

The worker loop is strictly serial: heartbeat → claim → **blocking** `_execute_job`. No heartbeat is sent for the entire execution. `renew_leases_for_worker` is reachable only from the heartbeat endpoint. With `DEFAULT_LEASE_TTL_S = 60`, every `claim()` runs `_reclaim_in_snapshot`, which flips the expired job back to `pending` and bumps `lease_generation`.

Two workers, a 90s node: A claims at t=0; at t≈60 B reclaims and re-executes identically; A's `complete` at t=70 is rejected 409 and discarded. Both perform the node's external side effects. The docs claim heartbeats continue during execution (`DISTRIBUTED_EXECUTION.md:239,365`) — they do not.

**Fix:** start a daemon heartbeat thread in `cmd_worker_start` before the claim loop and keep it running through `_execute_job`. Additionally have `GET /jobs/{job_id}` renew the lease when the caller is `job.claimed_by`, so the existing 2 Hz cancel-watch doubles as a keep-alive. **Effort: M**

### P1-12 · Reclaimed jobs have no attempt cap — a job that always outlives its lease loops forever
**`app/core/distributed/queue.py:383-408`** · `app/core/distributed/models.py:73-97`

`NodeJob` has no `attempts` field and nothing ever refuses to requeue. A 10-minute node with a 60s TTL is redispatched every minute until the fleet is saturated; an OOM-killing job walks the fleet indefinitely.

**Fix:** add `attempts` / `max_attempts` to `NodeJob`; increment in `_reclaim_in_snapshot` and write a terminal `failed` `JobResult` when exceeded. **Effort: M**

### P1-13 · `DistributedBackend` never finalizes the run journal
**`app/core/distributed/backend.py:177, 270-283, 467-503`** · `app/core/run_journal.py:70-75`

Mode B runs stay `"running"` forever with no `graph.json`, no logs, no artifacts, no `node_stats`. It also silently discards 8 execution parameters on the remote path — including `resume_run_id` and `checkpoint` — and never calls `register_active_run`, so **`POST /runs/{id}/cancel` cannot reach a Mode B run at all**.

**Fix:** mirror the local orchestrator's journal contract in `_execute_with_jobs` — `save_graph_ir` before the wave loop, append `node_stats` per completed job, `register_active_run`/`deregister_active_run`, poll `is_cancelled()`, and finalize status. Raise `NotImplementedError` naming any unsupported parameter instead of dropping it. **Effort: L**

### P1-14 · A corrupt index is read as empty, then **written back** — permanent lineage loss
**`app/core/artifact_store.py:225-246`** · **`app/core/provenance.py:157-193`**

`_load_by_run()` catches a parse failure, warns, returns `[]`; `_append_by_run()` then persists that empty list with one id appended. Every previously registered artifact for that run becomes unreachable through `ArtifactStore.list(run_id=…)` and `find_by_run()`. The per-artifact records survive on disk but nothing can enumerate them.

**Fix:** rename the damaged file to `<name>.json.corrupt.<ts>` before returning `[]`, and rebuild by scanning per-artifact records rather than starting empty. Surface the condition in the trace `warnings`. **Effort: M**

### P1-15 · A cache hit skips artifact and provenance registration
**`app/core/orchestrator.py:528-556`** · **`app/core/executor.py:306-333`**

Both paths gate the whole provenance block on `if not cache_hit:`. Caching is on by default, so on every re-run the cached nodes register nothing, and downstream nodes get `input_artifact_ids=[]`. This directly breaks the README's Accountability pillar ("trace any artifact back to run, graph, and worker").

**Fix:** move the block out of the `if not cache_hit:` guard in both files — `ArtifactStore.register()` already dedupes by content hash. **Effort: S**

### P1-16 · Artifact dedup overwrites the original's provenance record
**`app/core/artifact_store.py:499-523`** · `app/core/run_journal.py:349-377`

Last-writer-wins on a content-hash collision destroys the first artifact's lineage.

**Fix:** make provenance additive — return a `deduplicated: bool` from `register()` and skip the `provenance.record()` overwrite. **Effort: M**

### P1-17 · `ArtifactStore` indexes do read-modify-write with no lock
**`app/core/artifact_store.py:165-170, 189-217, 237-247`**

API, CLI and worker all mutate `index.json` and `by_run/*.json` concurrently with no `flock`. Lost updates.

**Fix:** apply the `schedules.py` `fcntl.flock` pattern around the whole load→mutate→save sequence. **Effort: M**

### P1-18 · `wait_if_paused()` is only called in the sequential loop
**`app/core/orchestrator.py:388`** vs `:303-345`, `:602-675`

Pause is a silent no-op in parallel and event-driven modes.

**Fix:** call `run.wait_if_paused()` in the parallel wave loop next to the existing `is_cancelled` check at `:305`, and at the top of each event iteration. **Effort: S**

### P1-19 · `ArtifactStore`/`ProvenanceStore` have no retention; run deletion orphans records
**`app/core/run_cleanup.py:402-427`** · `app/core/artifact_store.py:705-807`

**Fix:** in `delete_run` and the `to_delete` loop, also remove that run's artifact and provenance state. **Effort: M**

### P1-20 · `normalizeExecStatus('succeeded')` returns `'idle'`
**`graphyn-ui/src/features/builder/GraphynNode.tsx:403-413`**

The branch list checks `'success' | 'complete' | 'completed' | 'ok'` but **not** `'succeeded'`, the canonical backend value — so it falls through to `return 'idle'`. Successful nodes never render as succeeded on the Builder canvas, and the four call sites in `BuilderView.tsx` that gate on status misbehave. *(Verified directly.)*

**Fix:** add `'succeeded'` to the first branch. **Effort: S**

### P1-21 · UI navigation loop → `RangeError`
**`graphyn-ui/src/store/appStore.ts:204-222`** · `App.tsx:414-441` · `routes/parsePath.ts:108-112`

`openRun`/`openExperiments` plus a synthetic `popstate` re-enter App's path sync indefinitely.

**Fix:** make store navigation idempotent — build the target path and only call `navigatePath` when it differs from the current `pathname + search`. **Effort: S**

### P1-22 · Builder canvas→IR serializer drops edge conditions, node labels, event triggers and graph parameters
**`graphyn-ui/src/types/graph.ts:121-148`** · `BuilderView.tsx:570-577, 920-938`

Opening a conditional graph in the Builder and saving it **silently strips the conditions** — turning P1-1's broken branching into an unconditional graph on disk.

**Fix:** carry `condition` through React edge `data`, and `label`/`event_trigger`/`capability_metadata` through `GraphynNodeData`; keep loaded `parameters` in a ref and re-emit on save. **Effort: M**

### P1-23 · Builder's Cancel only aborts the HTTP stream; the run keeps executing
**`graphyn-ui/src/features/builder/BuilderView.tsx:625-634, 306, 668-669`**

The stream is also never aborted on unmount, so a stale stream can overwrite the next run's outcome.

**Fix:** `POST /runs/{id}/cancel` before aborting the reader; add an unmount cleanup that aborts, and only apply results when `abortRef.current === controller`. **Effort: S**

### P1-24 · `node_stats` is written only at terminal success
**`app/core/orchestrator.py:566-571, 741-747`** · `app/api/routers/runs.py:327-348`

Run progress is `null` for the entire life of every run, and a **failed** run loses all `node_stats` — after which `/trace` reports every node of that run as `completed`.

**Fix:** write `node_stats` incrementally via `run._write_meta_field` after each append, write `num_nodes` once at start, and have `mark_failed` persist partial stats with the failing node marked `failed`. **Effort: M**

### P1-25 · `POST /api/v1/data/merge` writes outside the dataset jail
**`app/api/routers/data.py:336-359`**

`project_root = output_root / body.target_project` is built with no validation; `project.json` is written at `:341` and `mkdir(parents=True)` runs at `:359` — both **before** the `_safe_child` jail check at `:357`. `Path.__truediv__` does not normalise `..`. Verified end-to-end against the live app: a directory was created and `project.json` written outside the jail while the endpoint returned 400.

**Fix:** resolve `project_root = _safe_child(output_root, body.target_project)` at the top of the function, before any `exists()`, `write_text()` or `mkdir()`. **Effort: S**

### P1-26 · `PluginInstaller` bypasses the documented fail-closed remote-source policy
**`app/core/plugins/installer.py:196-208`** · `app/core/config.py:355-364`

`_check_allowed_source` short-circuits on an empty allowlist (`if not allowed: return`), so it never reaches the fail-closed branch inside `plugin_source_is_allowed`. Verified: with `GRAPHYN_AUTH_REQUIRED=1`, `plugin_source_is_allowed('https://evil.example.com/p.zip')` → `False`, while `_check_allowed_source(...)` returns without raising. A production deployment that sets `GRAPHYN_AUTH_REQUIRED=1` but no allowlist — the documented-safe configuration — installs and imports plugin code from **any** origin.

**Fix:** delete the short-circuit and delegate unconditionally to `plugin_source_is_allowed`, raising `PluginInstallError` on `False`. **Effort: S**

### P1-27 · MCP `replay_run` has no `run_id` sanitization → path traversal
**`app/mcp/handlers/provenance.py:97-112, 193, 195-210`**

`run_dir = _runs_dir() / run_id` loads and **executes** a `graph.json` from anywhere on disk.

**Fix:** reuse the existing `_validate_safe_id` / `_safe_run_dir` guards from `app/mcp/handlers/artifacts.py`. **Effort: S**

### P1-28 · `graphyn validate --graph` fails on 7 of 10 shipped templates
**`app/cli/main.py:483, 628`** · `app/core/ir/models.py:39-49`

`copy.deepcopy(dict(node.config))` deep-copies a shallow copy of a frozen config and raises.

**Fix:** use `copy.deepcopy(_deep_unfreeze(node.config))`, promoting `_deep_unfreeze` to a public `thaw_config()` helper. **Effort: S**

---

## 6. P2 — Hardening

| # | Finding | Location | Fix |
|---|---|---|---|
| P2-1 | `WebhookService._send` resolves DNS **twice** (`_is_private_host` then `gethostbyname` at `:208`), so the validated IP is not the connected IP — the rebinding window the docstring claims to close is open. Rewriting the URL to `https://<ip>/` also breaks TLS verification for every HTTPS webhook (a `Host` header does not set SNI). | `app/core/webhook.py:175-232` | POST the original URL; get rebinding protection from the transport, not URL rewriting. Delete `webhook.py::_is_private_host` and reuse `app.core.egress` helpers (which correctly use `getaddrinfo` and check every address). |
| P2-2 | `POST /api/v1/ingest/url` downloads arbitrary URLs with no egress validation | `app/api/routers/ingest.py` | Route through `validate_http_egress_url` |
| P2-3 | Plugin download and index fetch validate redirect hops only *after* httpx issued the request | `app/core/plugins/installer.py`, `index.py` | Validate each hop before issuing it |
| P2-4 | Static-mount auth raises `HTTPException` inside ASGI middleware → unauthenticated `/files` returns **500, not 401** | `app/api/main.py:248-254, 275-281` | Catch and return `JSONResponse(status_code=exc.status_code, ...)` |
| P2-5 | `PUT /system/webhooks` returns 500 for every invalid URL (uncaught `ValueError`), hiding the SSRF-block reason | `app/api/routers/system.py:158-174` | Map to 422, as `post_schedule` already does |
| P2-6 | Both upload handlers buffer the entire body in RAM then write synchronously on the event loop | `app/api/routers/data.py:172-208`, `workers.py:203-226` | Cap via `content-length` → 413; stream in 1 MB chunks; declare `def` not `async def` |
| P2-7 | Run endpoints spawn an **unbounded** daemon thread per request, each allocating its own 32-worker pool | `app/api/routers/pipelines.py:373, 457` | Submit to one bounded module-level `ThreadPoolExecutor` (pattern already at `mcp/handlers/execution.py:29`) |
| P2-8 | `GET /plugins` spawns one Python interpreter **per dependency per isolated plugin** (~40-60 subprocesses, 2-3s); UI polls it every 2s during install | `app/api/routers/plugins.py:148-162`, `plugins/dependencies.py:412-451` | Memoize `_installed_version` on `(python, dist)`, invalidated by site-packages mtime; batch all requirements into one subprocess |
| P2-9 | `GET /runs?project=` parses **every** run's `graph.json` from disk; UI polls every 3s | `app/api/routers/runs.py:185-207`, `run_project.py:107-160` | Write the project name into `meta.json` at run creation; backfill once |
| P2-10 | `DiskStateStore` substitutes an empty queue for an unreadable `jobs.json`, then persists the erasure | `app/core/distributed/store.py:228-248` | Add `fail_closed=True` for mutations; re-raise on anything but `FileNotFoundError` |
| P2-11 | Blob writes non-atomic; rewrites skipped when the path exists; reads never verify the sha256 the key encodes | `app/core/distributed/transfer.py:93-123` | temp+fsync+`os.replace`; verify content hash on read |
| P2-12 | Jobs the backend gave up on are never cancelled — workers keep executing for a dead run | `app/core/distributed/backend.py:430-444` | Cancel all enqueued job ids for the run in a `try/except` around the wave loop |
| P2-13 | A job pinned to a worker that dies before claiming stays pending forever | `app/core/distributed/backend.py:388-398`, `queue.py:373` | Extend `_reclaim_in_snapshot` to release pins on `pending` jobs whose worker is stale |
| P2-14 | NDJSON stream uses a blocking `queue.put` for its sentinel — a disconnected client can hang the execution thread forever | `app/api/routers/pipelines.py:349, 363-371` | `put_nowait` guarded by `except queue.Full` |
| P2-15 | `/system/readiness` reports `ready` after registry init **hard-fails** — the flag is set in a `finally` | `app/core/nodes/__init__.py:73-75, 176-195` | Track `_init_error`; return `_ready_event.is_set() and _init_error is None`; surface the error in the probe body |
| P2-16 | `GET /artifacts` has no pagination and scans the whole store per call | `app/api/routers/artifacts.py:49-63` | Add `limit`/`offset` |
| P2-17 | Metrics keyed by raw URL path → `_BY_ROUTE` grows unbounded | `app/api/observability.py:22-36` | Key on `request.scope['route'].path` |
| P2-18 | Schedule ticker runs per-process with only a thread lock → N API workers fire every schedule N times | `app/api/main.py:316-330`, `core/schedules.py` | Move into a lifespan handler; gate on a cross-process lease |
| P2-19 | `POST /system/cleanup` irreversibly deletes runs and artifacts with **no audit event**, while trivial mutations are audited | `app/api/routers/system.py:106-135` | `record_audit(...)` after `cleanup_workspace` |
| P2-20 | Flattened inline-table defaults in `plugin.toml` break two shipped nodes with Builder defaults | `PluginPackage/Audio/augmentation_pipeline/plugin.toml:27`, `audio_exporter/plugin.toml:23` | Re-serialise as proper TOML inline tables |
| P2-21 | `http_request` `plugin.toml` `default = {}` silently discards the connected payload and disables the body field | `PluginPackage/Common/http_request/plugin.toml:26` | Remove the `default`; let the Pydantic `None` default stand |
| P2-22 | Isolated plugins claim runtime ownership of node types they did not register, hijacking another plugin's execution | `app/core/plugins/runtime_registry.py` | Register only types the plugin actually declared |
| P2-23 | Isolated node stubs downgrade required config fields to optional — host validation passes, worker dies | `app/core/plugins/isolated_schema.py` | Preserve `required` in the generated stub |
| P2-24 | Upgrading bundled plugin source never takes effect — stale code loads silently after `git pull` | `app/core/plugins/manager.py:648-656` | Compare record version against `PluginPackage/*/plugin.toml`; force `upgrade=True` on drift |
| P2-25 | One unparseable row in `registry.json` permanently disables that plugin; no version stamp | `app/core/plugins/store.py:75-81` | Add `schema_version`; quarantine bad rows instead of dropping the plugin |
| P2-26 | With a custom `GRAPHYN_PROJECT_DIR`, `workspace/...` paths are created one level too deep and data lands outside the project dir | `app/core/write_paths.py:78-84` | Prefer `root / Path(*parts[1:])` for `workspace`-prefixed inputs |
| P2-27 | Run detail panel never refreshes when the run finishes — logs/outputs/artifacts frozen at open time | `graphyn-ui/src/features/runs/RunsView.tsx:320-380` | Refetch once on transition to a terminal status |
| P2-28 | Live run tab **fabricates** node status — labels the last completed node "Current" and paints every node green mid-run | `graphyn-ui/src/features/runs/RunsView.tsx` | Render only backend-supplied status |
| P2-29 | Plugin install reports success while the background install is still running or already failed | `graphyn-ui/src/features/plugins/PluginsView.tsx` | Report only on terminal status |
| P2-30 | One failing endpoint blanks the entire Ops page, discarding data that loaded fine | `graphyn-ui/src/features/system/SystemView.tsx` | Per-panel error boundaries |
| P2-31 | Run log panel renders up to 10,000 unvirtualised rows, two regexes per row per render | `graphyn-ui/src/features/runs/RunsView.tsx` | Virtualise; precompute |
| P2-32 | Artifact blob download reads the whole file into memory then discards it | `app/api/routers/artifacts.py` | Stream |
| P2-33 | Graph validation depth differs per interface — REST and MCP report `valid` for graphs that cannot execute | `app/cli/main.py:406-700`, `api/routers/pipelines.py:261-271`, `mcp/handlers/graph.py:394-412` | Extract the CLI's steps 3-7 into `app/core/validation.py::validate_graph_ir(graph, registry)`; call from all three |
| P2-34 | MCP exposes `accept_proposal` alongside `propose_graph`, so an agent can self-approve graphs its own tool description says a human must approve | `app/mcp/tool_registry.py:158` | Gate behind an explicit human-approval capability |
| P2-35 | `graph_hash` computed every run but never written to `meta.json` → run-scoped traces report `graph.hash = null` | `app/core/run_journal.py:159-169` | `self._write_meta_field("graph_hash", self._graph_hash)` |
| P2-36 | Trace reads `duration_ms`/`cache_hit`/`status` from `node_stats`, but executors write only `duration_s` → every node shows a null duration | `app/core/trace.py:270-279`, `executor.py:345-351` | Write all three keys at the source; convert in `trace.py` |
| P2-37 | Run-scoped `/trace` attributes each input artifact to the node that **consumed** it, not the one that produced it | `app/core/trace.py:300-315` | Resolve each input id's own provenance record |
| P2-38 | `node_start`/`node_end`/`node_error` carry no `node_id`; `node_index` is topological but the Builder matches it against canvas array position | `app/core/logger.py:117-158` | Add `node_id` to the events; match on it |
| P2-39 | Event-driven mode runs nodes synchronously on the event loop, starving other sources and delaying cancel | `app/core/orchestrator.py:602-675` | Offload to the executor |
| P2-40 | Webhook URL — credential-equivalent for Slack/Discord/Teams — is written to WARNING logs on every delivery failure | `app/core/webhook.py:236-240` | Log scheme+host only |
| P2-41 | `graphyn migrate` and the whole YAML path bypass `legacy_aliases.py`, so legacy node types are never translated | `app/core/ir/migrate.py:72` | Round-trip through the alias layer |
| P2-42 | On-disk state has no enforced version stamp: `schema_version` is written but never read; plugin registry/index have none | `app/core/artifact_store.py:144`, `provenance.py:64` | One `STATE_SCHEMA_VERSION`, checked on load |
| P2-43 | `verify_templates.py`'s node-type check is **dead code** — it probes `NodeRegistry` attributes that do not exist | `scripts/verify_templates.py:38-52` | Use `{m.node_type for m in reg.list_nodes()}`; fail loudly |
| P2-44 | `scripts/e2e_audio_pass_runner.py` cannot run — hardcoded `/workspace/Graphyn` root and token path crash at import | `scripts/e2e_audio_pass_runner.py:13-18` | Derive `ROOT` from `__file__`; read the token from env |
| P2-45 | No documented setup step creates the `workspace/datasets/input/<pack>/<label>` tree all 53 example graphs ingest from; `examples/19` ingests a filename no setup path produces while the matrix claims COMPLETED | `examples/README.md`, `scripts/heal_e2e_local_data.py:116-119` | Add the heal script to Quick Start; fix the glob |
| P2-46 | `GETTING_STARTED`'s first run command cannot work on a fresh clone — every dataset it can ingest is gitignored | `docs/GETTING_STARTED.md:69`, `.gitignore:18` | Add a seed step; make the `FileNotFoundError` actionable |
| P2-47 | `heal_e2e_local_data.py` rewrites version-controlled `examples/templates/*.graph.json` in place | `scripts/heal_e2e_local_data.py:126-129` | Only touch the disposable `workspace/configs/templates` copy |
| P2-48 | `faster-whisper` is required by a test but declared in no installable target — and `check_deps.py` exits 0 anyway | `requirements.txt:37`, `setup.py:22`, `scripts/check_deps.py:127` | Declare it in an extra; make the EXTRA case non-zero exit |
| P2-49 | `docker-compose` bind-mounts `./plugins` but never sets `GRAPHYN_PLUGINS_DIR` — the mount is inert | `docker-compose.yml:29,36` | Set the env var, or drop the mount |
| P2-50 | `create_event_source` rejects `'queue'` while its own docstring advertises it | `app/core/events.py:238-265` | Pick one contract |

---

## 7. P3 — Cleanup

| # | Finding | Location |
|---|---|---|
| P3-1 | `docs/KNOWN_ISSUES.md` records **no entry** for the red suite (92 failures + 49 errors) | `docs/KNOWN_ISSUES.md` |
| P3-2 | `API_REFERENCE.md` documents 102 of 165 routes — the entire Secrets router and all run-control verbs are missing | `docs/API_REFERENCE.md` |
| P3-3 | `SDK_AND_CLI.md` lists 5 of 11 commands; never documents `graphyn secrets` or `runs pause/resume/cancel` | `docs/SDK_AND_CLI.md:186-193` |
| P3-4 | `NODE_CATALOGUE.md` / `PLUGIN_GUIDE.md` publish wrong node counts and contradict `NODES.md` / `ARCHITECTURE.md` on `model_builder` | `docs/NODE_CATALOGUE.md:3,34` |
| P3-5 | Three top-level docs describe a console "Observe" nav group that does not exist | `docs/GETTING_STARTED.md:79`, `docs/README.md:40` |
| P3-6 | `IA_PROJECT_FIRST.md` contradicts the shipped nav (Plugins is in Library, not Admin) | `docs/IA_PROJECT_FIRST.md:16,31` |
| P3-7 | **AGENTS.md Hard Rule 8 mandates updating `.kiro/steering/`, which is gitignored, untracked and contains one file** — every contributor starts with no steering | `AGENTS.md:46`, `.gitignore` |
| P3-8 | `DISTRIBUTED_EXECUTION.md` lists `GRAPHYN_ARTIFACT_STORE` as a runtime env var; no code reads it | `docs/DISTRIBUTED_EXECUTION.md` |
| P3-9 | Example READMEs document output locations the graphs no longer write to | `examples/05_.../README.md:53`, `examples/24_captions/README.md:7` |
| P3-10 | `examples/README.md` advertises 28 examples for 30 directories; feature map omits example 29 | `examples/README.md` |
| P3-11 | Seven shipped examples bypass `get_backend()` and call `run_pipeline_ir` directly — violating Hard Rule 4 | `examples/{09,12,15,16,17,18,20}/*.py` |
| P3-12 | `PluginPackage/WakeWord` — **6506 lines that cannot be imported** (`..models.feature_extractor`, `..resources` do not exist); `PluginPackage/Video` is empty | `PluginPackage/WakeWord/__init__.py:3-19` |
| P3-13 | `orchestrator.run_pipeline_ir_async` is a single **648-line** function — 78% of its 831-line module | `app/core/orchestrator.py:130-777` |
| P3-14 | `app/cli/main.py` is a **2160-line** god module hosting the entire distributed worker daemon | `app/cli/main.py` |
| P3-15 | `app/core/pipeline.py` is a re-export shim with zero importers, and the sole caller of `run_pipeline_from_yaml` | `app/core/pipeline.py` |
| P3-16 | Six functions across `app/core` have zero callers repo-wide, incl. one whose docstring claims live back-compat callers; `orchestrator._resolve_capability` is a dead alias | `app/core/orchestrator.py:100-109` |
| P3-17 | Workers never report `active_jobs`/busy, so least-loaded placement degenerates to alphabetical `worker_id` | `app/cli/main.py:1546-1550` |
| P3-18 | `jobs.json` is never pruned, and is fully re-serialized + fsynced under a global exclusive lock on every queue op | `app/core/distributed/store.py:250-275` |
| P3-19 | Three mutually incompatible error-envelope shapes across routers; `/pipelines/validate` omits `detail` entirely | `app/api/routers/pipelines.py:283-316` |
| P3-20 | `Pipeline.to_yaml()` drops all edges — a branched pipeline reloads as a linear chain | `app/core/sdk.py` |
| P3-21 | `graphyn validate` with neither `--graph` nor `--config` crashes with an unhandled `TypeError` traceback | `app/cli/main.py` |
| P3-22 | 19 of 24 CLI subcommands have zero test coverage, including every state-mutating one | `unit_test/cli/` |
| P3-23 | `pause_run`/`resume_run`/`cancel_run` MCP schemas omit `_meta.auth_token` — a schema-driven client cannot authenticate | `app/mcp/handlers/run_control.py` |
| P3-24 | `Pipeline` explicit-edge index guard misses negative indices, silently wiring a different node | `app/core/sdk.py` |
| P3-25 | Distributed per-node completion log dropped by a swallowed `TypeError` (`PipelineLogger.info` takes no kwargs) | `app/core/distributed/backend.py` |
| P3-26 | `TraceView` re-traces a lineage input with the previously selected `run_id`, pinning an artifact to a run that did not produce it | `graphyn-ui/src/features/trace/TraceView.tsx:622-631` |
| P3-27 | `_enrich_run_summary` re-reads and re-parses the same `graph.json` up to twice per run per listing | `app/api/routers/runs.py` |
| P3-28 | `csv_table`'s "config.path is required" guard is unreachable — `Path("")` stringifies to `"."` | `PluginPackage/Common/csv_table/nodes.py` |
| P3-29 | Manifest `min_python` is never validated; a specifier-style value crashes `PluginLoader` with `InvalidVersion` | `app/core/plugins/loader.py` |
| P3-30 | `dataset_versioner` default writes outside `workspace/datasets/output`, where the Data browser cannot see it | `PluginPackage/Common/dataset_versioner/plugin.toml` |
| P3-31 | Repo `venv/` has never had the project installed, so `_import_smoke.py` and the `graphyn` console script are both broken locally | run `venv/bin/pip install -e ".[dev]"` |
| P3-32 | `npm run build` fails with EACCES — `node_modules/.tmp`, `.vite-temp`, `dist/` owned by root | `chown -R` or delete + `npm ci` |
| P3-33 | `sync_example_templates` docstrings claim to import all example graphs; it imports one canonical graph per folder | `scripts/sync_example_templates.py` |
| P3-34 | `test_schedules` calls `_execute_pipeline` with a stale 2-arg signature, so the scheduler tick test never fires | `unit_test/core/test_schedules.py:80` |
| P3-35 | E2E runner resolves 20 of 30 templates from gitignored `workspace/configs/templates` that documented steps never populate | `scripts/e2e_all_templates_runner.py:29` |

---

## 8. Suggested sequence

1. **Make the suite green and the gate real** — P0-2, P0-3, P0-5, then P0-4. Without this, no fix below can be verified, and the 141 failures are actively hiding regressions.
2. **Close the RCE** — P0-1. Independent of everything else; land it immediately.
3. **Fix the `None`-as-unproduced ambiguity once** (theme T1) — P1-1, P1-2, P1-3, P1-22 together. Doing these separately will produce three incompatible partial fixes.
4. **Fix the cache** — P1-5, P1-6, P1-7. Consider disabling the cache by default until these land; it currently returns wrong data silently.
5. **Unify the execution paths** (theme T2) — P1-4, P1-18, P1-13. Extract the shared per-node decision helper first.
6. **Restore accountability** — P1-14, P1-15, P1-16, P1-24, P2-35, P2-36. The README's central pillar is currently not delivered.
7. **Mode B durability** — P1-11, P1-12, P2-10..P2-13. Treat Mode B as beta until done.
8. P2, then P3.

---

## Appendix A — Deliberately out of scope

Not assessed: runtime performance under real load, model/ML output quality, licensing, the `.hypothesis` corpus, and third-party plugin ecosystems beyond the shipped `PluginPackage`.

## Appendix B — Checked and found sound

Recorded so these are not re-investigated. Each was actively probed and survived.

**Security controls that hold:** the path jails (`_safe_child`, `_run_dir`, `transfer._safe_path`, `run_outputs.resolve_download_path`); the egress IP blocklist (decimal, hex and IPv4-mapped-IPv6 bypasses all correctly blocked when tested); the secret store; archive-extraction guards in `PluginInstaller._extract_archive_bytes` and `dataset_ingest`'s tar filter (zip-slip blocked). `torch.load` ACE does not apply — installed torch 2.12 defaults `weights_only=True`. `git+ext::` injection is blocked by git's own `protocol.ext.allow=never` default. Redirect-based egress bypass in the HTTP nodes does not apply — httpx top-level helpers default `follow_redirects=False`. Extensionless secret files fail the `/outputs/file` suffix allowlist. The `python_code` node's AST escapes are explicitly documented as not a sandbox.

**Distributed primitives that are correct:** the pending→claimed transition is genuinely CAS-safe across processes (`DiskStateStore` holds an exclusive `flock` across the whole read-modify-write; Redis uses a distributed lock with a `WATCH`/`MULTI` fallback), and `complete` is properly fenced by `worker_id == claimed_by` plus a `lease_generation` check. The claim race and lost-update problems tracked as DIST-001/002/003 are genuinely fixed.

**Architecture:** zero module-level import cycles in `app/`. No `app/core/**` module imports `app.domain` — the platform/domain rule holds. Repo hygiene is clean: `workspace/`, `.env`, `dist/` and `venv/` are all gitignored **and** untracked; no secrets are committed.

**Runtime resource handling:** run-scoped `ThreadPoolExecutor` with `try/finally` shutdown; bounded 10k-entry log deque; `ArtifactStore`'s `by_run`/`by_name` secondary indexes already replaced the older O(N) scans; `list_runs`' mtime sort is a deliberate, documented O(N)-stat / O(page)-read tradeoff.

**Frontend build:** `tsc --noEmit` passes on both configs; `oxlint` reports 0 errors.

---

*Method: ground-truth baseline (real test/build/lint execution) → 14 parallel subsystem audits → per-finding adversarial re-verification against source, with non-reproducing claims dropped → manual spot-check of the highest-severity claims. 149 findings survived; several dozen were discarded during verification.*
