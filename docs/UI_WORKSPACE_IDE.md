# Workspace IDE chrome

Brief contract for the Graphyn console shell (think **VS Code / Cursor**: folder open vs empty window).

## Stable rail (ALWAYS the same shape)

The left sidebar **does not morph** between global and workspace. Same DOM structure always:

1. **Workspace strip** (always visible)
2. **Build / Library / Deploy / Admin** groups (always visible, same titles and style)

Only **enabled vs disabled** (and active highlight) change when a project is open — never a different collapsed “Library & admin” chrome, mode pills that recolor the panel, or swapping Models/Ship/Datasets into global Library/Deploy.

### Workspace strip

| Item | Enabled when |
|------|----------------|
| **Home** (projects) | Always |
| **Editor**, **Runs**, **Models**, **Ship**, **Datasets** | `activeProject` set; otherwise disabled + title “Open a project first” |

Optional quiet header in the strip: `Workspace: {name}` + **Switch**, or “No project open” + **Open** — same padding/fonts as before.

### Groups below (global + workspace — identical)

- **Build:** Templates, Agent inbox
- **Library:** Plugins, **Artifacts only** (NO Models, NO Datasets)
- **Deploy:** Worker fleet only (NO Ship)
- **Admin:** Secrets, Ops, Access

## Data scoping

- With a workspace open, Models / Ship / Datasets use workspace paths and filter/scope to that project (`pathForView` + view logic from the IDE shell work).
- `pathForView('models'|'edge'|'data')` without a workspace id returns **`null`** → `go()` opens the projects picker (toast: open a workspace first).
- Legacy/global URLs `/library/models`, `/library/datasets`, `/deploy/ship` canonicalize to **`/workspaces`** (not primary nav destinations).
- HashRedirect → `navigatePath` remains the cold-load path for `#/…`.

## Header

Keep prior calm chrome (stable border/background). Prefer the workspace name chip + Switch when a workspace URL is open; avoid loud **In workspace** / **Global** pills that make the shell feel like two different apps.

## Related

- `docs/UI_NORTH_STAR.md` §4.2
- `docs/IA_PROJECT_FIRST.md` — Workspace vs global chrome contract
- `docs/UI_LINKAGE.md`
