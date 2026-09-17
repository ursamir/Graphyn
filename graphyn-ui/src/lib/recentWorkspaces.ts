/**
 * Recently-opened workspaces, most recent first.
 *
 * Deliberately separate from the store's `activeProject`. That value answers
 * "which workspace is open right now", and the path↔store sync clears it the
 * moment you land on `/workspaces` so the sidebar can say NO PROJECT OPEN —
 * which means it is not, and cannot be, a memory of what you were working on.
 * Before this list existed, visiting the workspaces console erased the app's
 * only record of your last workspace, so "resume where I left off" and the
 * header's "Back to X" chip both silently stopped working after one visit.
 */

const KEY = 'graphyn.recentWorkspaces'
const MAX = 5

export function readRecentWorkspaces(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]') as unknown
    return Array.isArray(parsed) ? parsed.map(String).filter(Boolean).slice(0, MAX) : []
  } catch {
    return []
  }
}

export function noteRecentWorkspace(name: string) {
  const trimmed = name.trim()
  if (!trimmed) return
  try {
    const next = [trimmed, ...readRecentWorkspaces().filter((n) => n !== trimmed)].slice(0, MAX)
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    /* ignore quota / private mode */
  }
}

/** Drop a workspace that no longer exists (renamed or deleted). */
export function forgetRecentWorkspace(name: string) {
  try {
    localStorage.setItem(KEY, JSON.stringify(readRecentWorkspaces().filter((n) => n !== name)))
  } catch {
    /* ignore */
  }
}
