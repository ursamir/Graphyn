# Workspace IDE chrome

Brief contract for the Graphyn console shell (think **VS Code / Cursor**: folder open vs empty window).

## Product rule: Project = Workspace

One entity. **UI says Workspace** everywhere. API/query fields may stay `project`.

## Stable rail (ALWAYS the same shape)

The left sidebar **does not morph** between global and workspace. Same DOM structure always:

1. **Workspace strip** (always visible) — the **only** Switch
2. **Build / Library / Deploy / Admin** groups (always visible, same titles and style)

Only **enabled vs disabled** (and active highlight) change when a workspace is open — never a different collapsed “Library & admin” chrome, mode pills that recolor the panel, or swapping Models/Ship/Datasets into global Library/Deploy.

### Workspace strip

| Item | Enabled when |
|------|----------------|
| **Home** (workspaces picker / home) | Always |
| **Editor**, **Runs**, **Models**, **Ship**, **Datasets** | `activeProject` set; otherwise disabled + title “Open a workspace first” |

Quiet header in the strip: `Workspace: {name}` + **Switch**, or “No workspace open” + **Open** — same padding/fonts as before.

**One Switch only** — do not also show workspace name + Switch in the top header when the sidebar strip is visible. Header may show a single “Open workspace” / “Back to …” affordance on global pages with no URL workspace.

### Groups below (global + workspace — identical)

- **Build:** Templates, Agent inbox
- **Library:** Plugins, **Artifacts only** (NO Models, NO Datasets in the rail)
- **Deploy:** Worker fleet only (NO Ship)
- **Admin:** Secrets, Ops, Access

## Data scoping / URLs

- With a workspace open, Models / Ship / Datasets use `/workspaces/:id/...` paths. Path id is source of truth — **do not** mirror redundant `?project=` when the path already has `/workspaces/:id`.
- `pathForView('models'|'edge'|'data')` without a workspace id returns **`null`** → `go()` opens the Workspaces picker (toast: open a workspace first).
- Global Models/Ship URLs `/library/models`, `/deploy/ship` canonicalize to **`/workspaces`**.
- `/library/datasets` may remain as a **secondary shared library catalog** (CTA “Browse shared library” from workspace Datasets) — not Models/Ship, not a second Switch.
- **Hash routing removed** — no `HashRedirect` / `legacyHash` map. Cold boot with a leftover `#/` clears the hash and lands on `/workspaces` once.

## Header

Keep prior calm chrome (stable border/background). Prefer sidebar Workspace strip for Switch; avoid dual Switch and loud **In workspace** / **Global** pills.

## Related

- `docs/UI_NORTH_STAR.md` §4.2
- `docs/IA_PROJECT_FIRST.md` — Workspace vs global chrome contract
- `docs/UI_LINKAGE.md`
- `docs/CLEANUP_LEGACY.md` — what was removed
