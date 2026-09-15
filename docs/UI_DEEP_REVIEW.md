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

### P2 (shipped)

1. **Header chip** — When `activeProject` is set, fetches the project's recent runs (same `GET /runs?project=` Overview uses) and prefers that latest run for the outcome chip + Last-run menu; falls back to Editor-driven `lastRunId` when scoped by `lastRunProject`.
2. **btn-primary density** — Plugins / Data / Experiments: secondary actions demoted to `btn-secondary` / `btn-quiet`; one clear primary per panel where practical.
3. **Artifacts empty CTAs** — Single primary (Open Run or Clear filters); removed dual Open Run + From template stacks.
4. **Linkage bridges** — Run detail quiet links (Editor / Lineage / Files / Compare / Promote); Overview → Editor / Data / Files; Data ↔ workspace CTAs; Trace banner; Edge Open source run; Proposals → Editor; Command palette Overview / Data / Browse run files; Editor Open Overview; Templates friendly toast.
5. **Friendliness** — Runs empty/filter copy + project chips; Compare empty “Select two runs from History”; calmer Mode A placement copy.

### Remaining gaps (honest)

- Trace standalone view still exists alongside Run → Lineage panel (by design for artifact-id deep links).
- Some Plugins / Data manage panels still use tab-style `btn-primary` for the active tab (intentional selected-state, not competing CTAs).
- Header chip prefers API latest; very fresh Editor runs may lag one poll until `/runs` refresh (effect also depends on `lastRunId` / `isRunning`).


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

### P2 files touched

- `graphyn-ui/src/App.tsx`
- `graphyn-ui/src/components/CommandPalette.tsx`
- `graphyn-ui/src/features/runs/RunsView.tsx`
- `graphyn-ui/src/features/artifacts/ArtifactsView.tsx`
- `graphyn-ui/src/features/plugins/PluginsView.tsx`
- `graphyn-ui/src/features/data/DataView.tsx`
- `graphyn-ui/src/features/experiments/ExperimentsView.tsx`
- `graphyn-ui/src/features/projects/ProjectsView.tsx`
- `graphyn-ui/src/features/builder/BuilderView.tsx`
- `graphyn-ui/src/features/trace/TraceView.tsx`
- `graphyn-ui/src/features/edge/EdgeWizardView.tsx`
- `graphyn-ui/src/features/proposals/ProposalsView.tsx`
- `graphyn-ui/src/features/templates/TemplatesView.tsx`
- `docs/UI_DEEP_REVIEW.md`
- `docs/UI_LINKAGE.md`
