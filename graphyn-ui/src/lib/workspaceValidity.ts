/**
 * Workspace existence — the single gate before a workspace id from the URL or
 * localStorage becomes the *active* / *recent* workspace.
 *
 * `/workspaces/does-not-exist` used to render a full dashboard and persist
 * `does-not-exist` as active + recent. App now validates every id with
 * `GET /projects/{name}` (authoritative 200/404) before persisting it, and the
 * store's persistence consults `isWorkspaceKnownValid` so an unvalidated id
 * is never written to localStorage.
 */
import { ApiError, apiJson } from '../api/client'
import { fetchAllPages } from '../api/unwrapList'
import { sharedFetch } from './sharedFetch'

const valid = new Set<string>()
const missing = new Set<string>()

export function markWorkspaceValid(name: string) {
  const n = name.trim()
  if (!n) return
  valid.add(n)
  missing.delete(n)
}

export function markWorkspaceMissing(name: string) {
  const n = name.trim()
  if (!n) return
  missing.add(n)
  valid.delete(n)
}

/** Forget a cached verdict (e.g. after creating / deleting / renaming). */
export function forgetWorkspaceVerdict(name: string) {
  valid.delete(name.trim())
  missing.delete(name.trim())
}

export function isWorkspaceKnownValid(name: string | null | undefined): boolean {
  return Boolean(name && valid.has(name.trim()))
}

export function isWorkspaceKnownMissing(name: string | null | undefined): boolean {
  return Boolean(name && missing.has(name.trim()))
}

/**
 * true = exists, false = 404. Throws on network / auth errors (unknown) so
 * callers can keep the current state instead of dropping a real workspace.
 */
export async function checkWorkspaceExists(name: string, opts: { fresh?: boolean } = {}): Promise<boolean> {
  const n = name.trim()
  if (!n) return false
  if (!opts.fresh && valid.has(n)) return true
  if (!opts.fresh && missing.has(n)) return false
  const ok = await sharedFetch<boolean>(
    `workspace-exists:${n}`,
    async () => {
      try {
        await apiJson<unknown>(`/projects/${encodeURIComponent(n)}`)
        return true
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 400)) return false
        throw err
      }
    },
    { maxAgeMs: 10_000, fresh: opts.fresh },
  )
  if (ok) markWorkspaceValid(n)
  else markWorkspaceMissing(n)
  return ok
}

/** Every workspace name (all pages of GET /projects); marks each as valid. */
export async function listWorkspaceNames(opts: { fresh?: boolean } = {}): Promise<string[]> {
  const rows = await sharedFetch<Array<{ name?: string } | string>>(
    'projects:all-names',
    () =>
      fetchAllPages<{ name?: string } | string>((offset, limit) =>
        apiJson('/projects', { query: { limit, offset } }),
      ),
    { maxAgeMs: 15_000, fresh: opts.fresh },
  )
  const names = rows
    .map((p) => (typeof p === 'string' ? p : String(p?.name ?? '')))
    .map((n) => n.trim())
    .filter(Boolean)
  for (const n of names) markWorkspaceValid(n)
  return names
}

/** Pure: recents that still exist, order preserved. */
export function pruneRecentNames(recents: readonly string[], known: Iterable<string>): string[] {
  const k = new Set(known)
  return recents.filter((n) => k.has(n))
}

/**
 * Pure: most recent workspace that still exists, skipping `exclude` (the
 * invalid one being dropped). `known` null = list unavailable → no fallback.
 */
export function pickFallbackWorkspace(
  recents: readonly string[],
  known: Iterable<string> | null,
  exclude?: string | null,
): string | null {
  if (!known) return null
  const k = new Set(known)
  for (const n of recents) {
    if (n && n !== exclude && k.has(n)) return n
  }
  return null
}
