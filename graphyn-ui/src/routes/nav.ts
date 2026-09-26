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

/**
 * Single-letter jump keys, shared by App.tsx's keydown handler and the
 * Keyboard shortcuts overlay (KeyboardHelp.tsx). This used to be a private
 * const in App.tsx with a second, hand-maintained copy of the same list (as
 * plain label strings) inside KeyboardHelp.tsx — the two silently drifted
 * apart and the overlay stopped mentioning Models or Access entirely once
 * those views gained nav entries. Keeping one map here means adding a view
 * only ever happens in one place.
 */
export const JUMP_KEYS: Record<string, AppView> = {
  b: 'builder',
  t: 'templates',
  p: 'proposals',
  r: 'runs',
  o: 'runs',
  e: 'runs',
  a: 'artifacts',
  d: 'data',
  j: 'projects',
  g: 'edge',
  w: 'workers',
  l: 'plugins',
  k: 'secrets',
  // credentials shares Admin group; no dedicated single-letter jump
  s: 'system',
  m: 'models',
  c: 'access',
}

/** Human label for a view's primary jump key, shown in the shortcuts overlay's
 * Navigation section (secondary Runs-panel keys — o/e — are listed separately). */
export const NAV_SHORTCUT_LABEL: Partial<Record<AppView, string>> = {
  projects: 'Home (workspace overview)',
  builder: 'Editor',
  runs: 'Runs (History)',
  data: 'Datasets',
  artifacts: 'Artifacts (cross-run registry)',
  templates: 'Templates',
  proposals: 'Agent inbox',
  plugins: 'Library · Plugins',
  edge: 'Ship',
  workers: 'Worker fleet',
  secrets: 'Secrets',
  credentials: 'Credentials',
  system: 'Ops',
  models: 'Models',
  access: 'Access',
}
