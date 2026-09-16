/**
 * Path-only navigation helpers. Never write `#/...` hashes.
 */

import { useAppStore, type AppView } from '../store/appStore'
import { navigatePath } from './parsePath'
import { paths } from './paths'
import { pathForView, type ViewPathContext } from './viewMap'

/** Navigate to an AppView via typed path builders + store view. */
export function goView(view: AppView, ctx: ViewPathContext = {}, replace = false) {
  const store = useAppStore.getState()
  const workspaceId = ctx.workspaceId ?? store.activeProject
  const path = pathForView(view, { ...ctx, workspaceId }) ?? paths.workspaces()
  navigatePath(path, replace)
  store.setView(view)
}

/** Build pathname + search; replace history when different (no hash). */
export function replacePathSearch(
  params: Record<string, string | undefined | null>,
  pathname?: string,
) {
  const path = pathname ?? window.location.pathname
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v != null && String(v).trim() !== '') qs.set(k, String(v).trim())
  }
  const s = qs.toString()
  const next = s ? `${path}?${s}` : path
  const cur = `${window.location.pathname}${window.location.search}`
  if (cur !== next) navigatePath(next, true)
}

/** Read current location.search as URLSearchParams. */
export function readSearchParams(): URLSearchParams {
  return new URLSearchParams(window.location.search)
}

/** Subscribe to History API path changes (replaces hashchange listeners). */
export function onPathChange(handler: () => void): () => void {
  window.addEventListener('popstate', handler)
  return () => window.removeEventListener('popstate', handler)
}
