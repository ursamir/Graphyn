/**
 * Parse pathname → view / workspace / run / panel for path↔store sync.
 */

import type { AppView } from '../store/appStore'
import type { RunPanel } from './paths'

export type ParsedPath = {
  view: AppView
  workspaceId?: string
  runId?: string
  panel?: RunPanel
  modelName?: string
  proposalId?: string
  runsTab?: 'history' | 'live' | 'compare'
  shipTab?: 'package' | 'devices'
  compareIds?: string[]
  /**
   * Set when the requested pathname is an alias for a route that has its own
   * canonical spelling — `/` and any unmatched path both render the workspaces
   * picker, so `/`, `/workspaces` and `/nonsense` were three URLs for one page
   * and whichever one you arrived on stayed in the address bar forever. App
   * replaces the URL with this on sync.
   */
  canonical?: string
}

const PANEL_SET = new Set<RunPanel>(['logs', 'outputs', 'lineage', 'details', 'checkpoints'])

/** Map panel path segment → FocusRunPanel store value (artifacts for outputs). */
export function panelToFocus(panel?: RunPanel): 'logs' | 'artifacts' | 'lineage' | 'debug' | 'checkpoints' | null {
  if (!panel) return null
  if (panel === 'outputs') return 'artifacts'
  if (panel === 'details') return 'debug'
  return panel
}

export function parsePathname(pathname: string, search = ''): ParsedPath {
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  const qs = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)

  if (parts.length === 0) {
    return { view: 'projects', canonical: '/workspaces' }
  }

  const [a, b, c, d, e] = parts

  if (a === 'login' || a === 'settings' || a === '404') {
    return { view: 'projects' }
  }

  if (a === 'workspaces') {
    if (!b) return { view: 'projects' }
    const W = decodeURIComponent(b)
    if (!c) return { view: 'projects', workspaceId: W }
    if (c === 'editor') return { view: 'builder', workspaceId: W }
    if (c === 'runs') {
      if (d === 'live') return { view: 'runs', workspaceId: W, runsTab: 'live' }
      if (d === 'compare') {
        const ids = (qs.get('ids') || '')
          .split(',')
          .map((x) => decodeURIComponent(x.trim()))
          .filter(Boolean)
        return { view: 'experiments', workspaceId: W, runsTab: 'compare', compareIds: ids }
      }
      if (d) {
        const runId = decodeURIComponent(d)
        const panel = e && PANEL_SET.has(e as RunPanel) ? (e as RunPanel) : undefined
        return { view: 'runs', workspaceId: W, runId, panel, runsTab: 'history' }
      }
      return { view: 'runs', workspaceId: W, runsTab: 'history' }
    }
    if (c === 'models') {
      return {
        view: 'models' as AppView,
        workspaceId: W,
        modelName: d ? decodeURIComponent(d) : undefined,
      }
    }
    if (c === 'datasets') return { view: 'data', workspaceId: W }
    if (c === 'ship') {
      return {
        view: 'edge',
        workspaceId: W,
        shipTab: d === 'devices' ? 'devices' : 'package',
      }
    }
    if (c === 'agent') return { view: 'builder', workspaceId: W }
    return { view: 'projects', workspaceId: W, canonical: `/workspaces/${b}` }
  }

  if (a === 'templates') return { view: 'templates' }
  if (a === 'agent' && b === 'inbox') {
    return { view: 'proposals', proposalId: c ? decodeURIComponent(c) : undefined }
  }
  if (a === 'library') {
    if (b === 'datasets') return { view: 'data' }
    if (b === 'plugins') return { view: 'plugins' }
    if (b === 'artifacts') return { view: 'artifacts' }
    if (b === 'models') return { view: 'models' as AppView }
  }
  if (a === 'deploy') {
    if (b === 'ship') {
      return {
        view: 'edge',
        shipTab: c === 'devices' ? 'devices' : 'package',
      }
    }
    if (b === 'workers') return { view: 'workers' }
  }
  if (a === 'admin') {
    if (b === 'secrets') return { view: 'secrets' }
    if (b === 'ops') return { view: 'system' }
    if (b === 'access') return { view: 'access' as AppView }
  }

  return { view: 'projects', canonical: '/workspaces' }
}

/** Drop legacy `#/…` fragments so path + hash hybrids never stick in the address bar. */
export function stripLegacyAppHash() {
  if (typeof window === 'undefined') return
  const { hash, pathname, search } = window.location
  if (!hash || !/^#\//.test(hash)) return
  window.history.replaceState(null, '', `${pathname}${search}`)
}

/**
 * History API navigation that notifies listeners (store + App sync). Path-only — never keeps hash.
 *
 * Idempotent: a no-op when `path` already matches the current location. Without
 * this, an `open*` store action (e.g. openRun) that calls navigatePath
 * unconditionally can loop forever — App's popstate-driven path sync reads the
 * new URL, calls the matching open* action again to reconcile store state,
 * which calls navigatePath again, dispatching another popstate, ad infinitum.
 * This really happened (`RangeError: Maximum call stack size exceeded` in
 * openRun, reproduced live). Stopping once the URL stops changing breaks the
 * cycle regardless of which action started it.
 */
export function navigatePath(path: string, replace = false) {
  const target = path.split('#')[0]
  if (typeof window !== 'undefined') {
    const current = `${window.location.pathname}${window.location.search}`
    if (current === target) return
  }
  if (replace) window.history.replaceState(null, '', target)
  else window.history.pushState(null, '', target)
  stripLegacyAppHash()
  window.dispatchEvent(new PopStateEvent('popstate'))
}
