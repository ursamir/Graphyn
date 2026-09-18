# Workspace IDE chrome

Brief contract for the Graphyn console shell (think **VS Code / Cursor**: folder open vs empty window).

## Modes

### Workspace open

**When:** pathname is `/workspaces/:id…` **and** `activeProject` is set from that path.

**Activity strip (primary):**

Home · Editor · Runs · **Models** · **Ship** · **Datasets**

**Library & admin (collapsed secondary):**

Templates · Agent inbox · Artifacts · Plugins · Workers · Secrets · Ops · Access

- Clicking Models / Ship / Datasets uses `pathForView` / `go` with `workspaceId` so URLs stay `/workspaces/:id/models|ship|datasets`.
- Those surfaces **scope data** to the open workspace (Models: filter by project run ids; Ship: prefer workspace ship path + recent successful runs; Datasets: workspace datasets path + “Workspace datasets” copy).
- **Artifacts** is **not** on the strip — it stays under Library & admin (may still default-filter inside ArtifactsView).

### Global (no workspace)

**Projects** · Build (Templates, Agent inbox) · Library (Datasets, Plugins, Models browse, Artifacts) · Deploy (Ship, Workers) · Admin (Secrets, Ops, Access)

Models / Ship / Datasets appear in Library / Deploy groups and use global paths (`/library/models`, `/deploy/ship`, `/library/datasets`).

## Header

Calm distinction: subtle tint/border when **In workspace**; chip shows workspace name with **Switch** to leave. Global mode shows a quiet **Global** label / open-workspace affordance.

## Routing notes

- Legacy `#/…` cold loads go through `HashRedirect` → `navigatePath` (Zustand + synthetic `popstate`), not React Router `navigate` alone.
- Standalone Devices with a workspace redirects into Ship → Devices (`/workspaces/:id/ship/devices`).

## Related

- `docs/UI_NORTH_STAR.md` §4.2
- `docs/IA_PROJECT_FIRST.md` — Workspace vs global chrome contract
- `docs/UI_LINKAGE.md`
