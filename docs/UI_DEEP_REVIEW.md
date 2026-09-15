# UI Deep Review (follow-up to Waves 1–4)

Date: 2026-09-15 · Tip before fixes: `94a6de4`

## Audit summary

See also `/tmp/deep_ui_audit.md` on Server-99 (copied below themes).

### P0 (fixed)

1. **Promote honesty** — Run detail shows Promote only when status is succeeded/completed; failed/cancelled get Open Editor + View logs recovery; in-flight runs hide promote.
2. **Compare nav** — Project strip Compare calls `openExperiments()` (Run → Compare tab) instead of `go('experiments')` dead-door.
3. **Store scope** — `openEdge` sets `activeProject`; `closeProject` / clear project clears stale `focusRunId`, `lastRunId`, `runOutcome`; `lastRunProject` scopes header chip + Last-run menu.
4. **Header chip** — Outcome chip and Last-run menu only show when `lastRunProject` matches the open workspace.
5. **Overview** — Activity first, then Continue pipelines, Schedules, Linked inputs; Spec Advanced save actions demoted to secondary; situation strip no longer duplicates Status.
6. **Command palette** — Leave workspace, Switch project, Files/Artifacts, Edge deploy; Tab focus trap.
7. **Edge wizard** — Single primary path (Use edge template); Trace → Lineage naming; fewer Open run/Trace triples on fail/success.

### P1 (fixed)

8. **Files affordance** — Quiet project-nav **Files** + Overview “Browse files” + palette workspace Files (no strip clutter of Artifacts as primary).
9. **Builder residue** — Template save description “Saved from Graphyn Editor”; NeedProjectPrompt copy uses Compare not Experiments.
10. **Files-tab Promote** — Gated to succeeded runs only.
11. **Cold copy** — Projects picker mentions Compare.

### Remaining gaps (honest)

- Trace standalone view still exists alongside Run → Lineage panel (by design for artifact-id deep links).
- Still many `btn-primary` in Plugins / Data / Experiments detail surfaces (P2).
- Header chip does not yet fetch “project’s latest run” from API — it only scopes the Editor-driven `lastRunId`/`runOutcome` by `lastRunProject`.
- Artifacts empty-state CTAs still stack Open Run + From template in some filter-empty cases (acceptable secondary surface).
- Mode A Workers / Editor placement already consistent; no further change this pass.

## Files touched

- `graphyn-ui/src/store/appStore.ts`
- `graphyn-ui/src/App.tsx`
- `graphyn-ui/src/components/CommandPalette.tsx`
- `graphyn-ui/src/components/ui.tsx`
- `graphyn-ui/src/features/runs/RunsView.tsx`
- `graphyn-ui/src/features/projects/ProjectsView.tsx`
- `graphyn-ui/src/features/edge/EdgeWizardView.tsx`
- `graphyn-ui/src/features/builder/BuilderView.tsx`
- `docs/UI_DEEP_REVIEW.md` (this file)
- `docs/UI_10X_AUDIT.md` (follow-up note)

