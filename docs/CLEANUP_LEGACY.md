# Legacy cleanup — Workspace-only chrome & path routing

Record of what was removed in the deep-clean (UI: Workspace-only chrome, drop hash legacy and duplicate Switch).

## Removed files

- `graphyn-ui/src/routes/HashRedirect.tsx`
- `graphyn-ui/src/routes/legacyHash.test.ts`
- `graphyn-ui/src/routes/legacyHash.ts`

## Removed / changed behavior

- **Dual Switch chrome:** header workspace chip + Switch when `workspaceOpen` removed. Sidebar strip keeps the single Switch.
- **Hash routing stack:** no `hashchange` listeners or `#/` write paths. Cold boot with `#/` → clear hash and `replace` to `/workspaces` (no legacy map).
- **Redundant `?project=`:** on `/workspaces/:id/datasets`, workspace id is read from the path only; search no longer mirrors `project` (and strips duplicate `?project=`).
- **Dead global Models/Ship builders:** `paths.libraryModels`, `paths.deployShip`, `paths.deployShipDevices` throw if called. Prefer `paths.models` / `paths.ship` / `paths.shipDevices` with a workspace id.
- **User-facing copy:** “Project(s)” / “Open a project” / “No project open” → **Workspace** wording. Internal ids (`view: 'projects'`, `activeProject`, API `project=`) unchanged.
- **Datasets library:** `/library/datasets` kept only as secondary “Browse shared library” catalog from workspace Datasets — not a Models/Ship global, not primary nav.

## Kept (intentionally)

- API `/projects` routes and `project` query/body fields (non-breaking).
- Internal store view id `projects` and `activeProject`.
- Home nav label **Home**; picker page title **Workspaces**.
- Backend `active` → `in-progress` status alias (still used for legacy clients).
