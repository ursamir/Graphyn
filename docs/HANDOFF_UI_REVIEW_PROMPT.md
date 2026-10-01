# Handoff prompt — Graphyn UI review & fix (continue from 2026-10-01)

Copy everything below the line into a new agent session started in
`/home/meritech/Desktop/newAudio3`.

---

You are continuing a deep **UI review-and-fix loop** on Graphyn (typed DAG pipeline
platform; React/Vite console in `graphyn-ui/`, FastAPI in `app/`). Read `AGENTS.md`
first and follow its hard rules (venv-only Python, never edit `plugins/`, plugin
source is `PluginPackage/`, 7-field module docstrings, update `docs/` +
`.kiro/steering/frontend-*.md` after changes).

## Scope (intentional)

Commit `4326ba1 "F1"` deliberately reduced the plugin set to the **14 plugins that
Example 06 (Speech commands E2E) needs**, so the UI can be hardened against one
complete audio use case before re-expanding:

- Audio: `dataset_ingest, audio_conditioner, segmenter, audio_quality_gate,
  augmentation_pipeline, audio_exporter, feature_frontend`
- Common: `dataset_builder, trainer, evaluator, edge_optimizer,
  realtime_inference, deployment_packager, python_code`

Do **not** restore removed plugins. Templates that need other plugins are expected to
show "Needs plugins / Missing node types" warnings — that is correct behavior.

Test suite consequence: ~205 failed / 425 errors (`GRAPHYN_SKIP_PLUGIN_LOAD=1`) and
~207 failed / 425 errors (full) are **pre-existing**, all "node type not registered"
from F1. Your bar is **no new failures**: record failing test ids before editing,
diff after.

## Environment

- Live app = docker containers: `graphyn-ui` → http://localhost:5173 (nginx serving a
  prebuilt bundle), `graphyn-api` → http://localhost:8001. They only reflect source
  changes after a rebuild. UI-only rebuild (fast, safe):
  `docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui`.
  API rebuild/restart can take 15+ min and plugin copies in the container's
  `./plugins` must be reinstalled/upgraded to pick up `PluginPackage/` changes —
  **ask the user before rebuilding the API**; the user often rebuilds themselves.
- The API requires a bearer token. In the browser it's already in localStorage of the
  :5173 origin (`graphyn_api_token`); for curl use `GRAPHYN_API_TOKEN` from the repo
  env. Never print the token.
- Browser automation caveat: the Chrome window is often in the background
  (`document.hidden === true`). Then screenshots time out and real CDP clicks/keys may
  not register. Check `document.visibilityState` first; if hidden, drive the UI via
  `javascript_tool` (DOM clicks, dispatched events, `innerText` reads) and only trust
  screenshots when visible. React Flow nodes need real pointer events.
- UI validation: `cd graphyn-ui && npx tsc --noEmit -p tsconfig.app.json && npm run lint`.
  `npm run build` / repo vitest config fail on root-owned `node_modules/.vite-temp`
  (environmental; fix with `sudo chown -R meritech graphyn-ui/node_modules` — ask the
  user). Workarounds: `npx vite build --configLoader runner --outDir <scratch>`;
  vitest via the cached binary
  `~/.npm/_npx/69c381f8ad94b576/node_modules/.bin/vitest run --config <scratch>.mjs`
  where the .mjs config has no imports (a copy existed at
  `/tmp/claude-1000/.../scratchpad/vitest-a3.config.mjs`; recreate if gone:
  `export default { test: { include: ['src/**/*.test.{ts,tsx}'], environment: 'node' } }`).
  Baseline at handoff: tsc clean, lint 0 errors, vitest 17 files / 84 tests pass.
- Backend: `venv/bin/pytest unit_test/ -q -p no:cacheprovider` (≈1 min) with and
  without `GRAPHYN_SKIP_PLUGIN_LOAD=1`.

## State at handoff

- ~148 uncommitted changes on branch `test/example-06-plugins` (three review/fix rounds:
  UI shell, Editor/Runs, backend, Example 06 plugins). **Do not commit unless the user
  asks.** Do not stash/checkout/reset.
- Containers were last rebuilt **before** round 3, so these are implemented in source
  but NOT yet verified live — verify them first after the user rebuilds:
  - `usePolling` first tick runs even in hidden tabs (Worker fleet / Runs → Live no
    longer stuck on "Loading…").
  - Invalid workspace URL → "Workspace not found" view; never persisted to
    `graphyn.activeProject` / recents; fallback to last valid workspace; recents pruned.
  - Editor: unsaved-changes tracking (Unsaved chip, beforeunload, `lib/navigationGuard.ts`
    guard on sidebar/palette/switch, confirm before canvas replace), undo/redo (50 steps),
    schema validation (min/max/exclusive*/multipleOf/integer/enum/length/pattern; blocks
    Run/Save), `ui.visible_if` / `depends_on` conditional fields, log dedupe
    (`already_reported` terminal error skipped), "skipped (not run)" status.
  - Runs: node list from run graph/`node_order` in execution order; "Ask agent to fix"
    (confirm, real error extraction, no auto-navigation, proposal `kind`/`context`);
    Compare includes node-config params; outputs natural order + fair caps; ingest
    inputs excluded (`inputs_by_node`).
  - Ops: orphan schedules badge/reason, Run now/Enable hidden, `next_run_at` null when
    disabled. Ship empty-state copy. Not Found titles. Command palette dedupe/paths.
    Template titles from source metadata; "Needs plugins" mapping. Isolated plugin
    categories from plugin `NodeMetadata`. `config_schema` passes through all bounds +
    `ui` table (`app/core/nodes/plugin_ui.py`).
  - Example 06: `docs/EXAMPLE_06_COVERAGE.md` documents every node/field, live run ids
    (workspace `e06-verify-1`), fixes (exporter `group_by_source` leakage fix, INT8
    calibration spread, trainer `learning_rate=null` = keep model_builder's, many
    plugin config fixes), and app fixes (cache rescope, `publish_latest_if_produced`,
    outputs prioritization, projectStamp no longer rewrites explicit artifact paths,
    speech-command raw-clip fallback now opt-in via `GRAPHYN_INGEST_EXAMPLE_FALLBACK=1`,
    gate `output_count` = primary port).
- Test data on the live API you may clean up **only with user approval**: workspaces
  `ui-review`, `e06-verify-1`; a stub proposal "Explain / propose fix for failed run
  dc0b784a…"; orphan schedule `hourly` (project `samir-test`, now disabled).

## Known open items (start here)

1. **Test isolation hang**: some test files hang when run together but pass alone —
   e.g. `unit_test/core/test_runtime_fixes_modes.py` + `unit_test/api/test_ui_review_backend_fixes.py`,
   and `test_example06_app_fixes.py` + `test_backend_review_round2.py` + example06 plugin
   tests in one command. Likely leaked threads / `threading.Thread.start` patch
   (`unit_test/conftest.py` `patch_threads` autouse fixture; several tests override it
   locally) or an un-closed event loop/executor. Find and fix.
2. **Live re-verification** of everything in "State at handoff" after rebuild.
3. **Example 06 end-to-end in the browser** (not just API): Templates → stamp
   ex-06 into a fresh workspace → run each preprocess phase (CLI graphs under
   `examples/06_speech_commands_e2e/`; the Builder template `ex-06-speech-commands-e2e`
   is the Phase-2 `pipeline_train_ml` graph) → train (≈29 min CPU; 50 epochs) → infer.
   Check every inspector field renders with correct defaults/bounds/visible_if, invalid
   values block Run, run outputs show model.tflite/metrics.json, Models/Ship flows work
   with the trained run (register → staging/prod approval → Ship package wizard), and
   Lineage/Compare/Artifacts are coherent.
4. Remaining UX gaps noted but not done: INT8 accuracy instability (prefer float16 in
   docs/UI hints); SNR estimator rates white noise ~24 dB; silence segmentation can split
   one keyword; speaker ids not parsed for fairness; `deployment_packager` and
   `python_code` were not audited.

## Method (what worked)

Loop: review live → list concrete findings with evidence (URL, DOM text, API response,
file:line) → split fixes by **disjoint file ownership** across parallel subagents
(e.g. A = `features/builder/**` + `features/runs/**`; B = rest of `graphyn-ui/src`;
C = `app/**`; D = `PluginPackage/**`) with explicit "don't touch" lists and shared
contracts → validate (tsc/lint/vitest, pytest both modes vs baseline) → rebuild → re-verify
live. Read source to confirm root causes before claiming a bug; distinguish environment
artifacts (hidden tab, stale container) from product bugs. Report findings ranked by
severity, and state clearly what was verified live vs only in source.
