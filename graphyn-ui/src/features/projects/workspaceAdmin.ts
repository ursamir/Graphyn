/**
 * Pure helpers for the Home "Workspace" fold and the Workspaces list:
 * archived filtering, display names, and the delete / clone scope text.
 *
 * Scope text mirrors the backend: ProjectManager.delete removes the workspace
 * folder (workspace/datasets/output/<id>) and disables its schedules;
 * ProjectManager.clone copies draft pipelines + settings only.
 */

export interface WorkspaceLike {
  name: string
  status?: unknown
  display_name?: unknown
}

export function isArchivedWorkspace(p: { status?: unknown } | null | undefined): boolean {
  return String(p?.status ?? '').trim().toLowerCase() === 'archived'
}

/** Workspaces list: archived ones are hidden unless `showArchived`. */
export function partitionArchived<T extends { status?: unknown }>(
  items: readonly T[],
  showArchived: boolean,
): { visible: T[]; archivedCount: number } {
  const archivedCount = items.filter(isArchivedWorkspace).length
  return {
    visible: showArchived ? [...items] : items.filter((p) => !isArchivedWorkspace(p)),
    archivedCount,
  }
}

/** Display name when set (and not just the id), else the workspace id. */
export function workspaceTitle(p: WorkspaceLike): string {
  const dn = typeof p.display_name === 'string' ? p.display_name.trim() : ''
  return dn || p.name
}

/** True when the title differs from the id, so the id should be shown muted. */
export function showsWorkspaceId(p: WorkspaceLike): boolean {
  return workspaceTitle(p) !== p.name
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

export interface DeleteScopeInput {
  pipelines: number
  datasetVersions: number
  schedules: number
  linkedInputs: number
}

/** What "Delete workspace" removes and keeps, as short display lines. */
export function deleteWorkspaceSummary(c: DeleteScopeInput): { removed: string[]; kept: string[] } {
  const removed = [
    `${plural(c.pipelines, 'pipeline')} (drafts and published versions)`,
    `${plural(c.datasetVersions, 'dataset output version')}`,
    'Description, datasets-in-use list, snapshots and spec/taxonomy/contract files',
  ]
  if (c.schedules > 0) {
    removed.push(`${plural(c.schedules, 'schedule')} disabled (kept, marked orphaned)`)
  }
  const kept = [
    'Run history and run outputs (artifacts)',
    'Registered models and Ship packages',
    'Audit log',
    c.linkedInputs > 0
      ? `Shared dataset folders (${plural(c.linkedInputs, 'folder')} in use: unlinked, not deleted)`
      : 'Shared dataset folders',
  ]
  return { removed, kept }
}

export const CLONE_SCOPE_TEXT =
  'Copies draft pipelines and settings (description, datasets in use). ' +
  'Not copied: runs, models, pipeline version history or dataset outputs.'
