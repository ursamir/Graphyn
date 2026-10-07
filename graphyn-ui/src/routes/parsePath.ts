/**
 * Parse pathname → view / workspace / run / panel for path↔store sync.
 */

import type { AppView } from '../store/appStore'
import type { RunPanel } from './paths'

/** `decodeURIComponent` that returns the raw segment on malformed `%` escapes instead of throwing. */
export function safeDecode(seg: string): string {
  try {
    return decodeURIComponent(seg)
  } catch {
    return seg
  }
}

export type ParsedPath = {
  view: AppView
  workspaceId?: string
  runId?: string
  panel?: RunPanel
  modelName?: string
  /** `/workspaces/:id/editor/pipelines/:name[/:env]` — saved pipeline to open. */
  editorPipeline?: string
  editorEnv?: string
  proposalId?: string
  runsTab?: 'history' | 'live' | 'compare'
  shipTab?: 'package' | 'devices'
  compareIds?: string[]
  /**
   * Legacy `/library/artifacts?artifactId=` — App resolves via GET /artifacts/{id}
   * then replaces onto Runs → Lineage (or outputs when `legacyArtifactsOutputs`).
   */
  resolveArtifactId?: string
  /** When set with resolveArtifactId, land on Run outputs instead of Lineage. */
  legacyArtifactsOutputs?: boolean
  /**
   * Set when the requested pathname is an alias for a route that has its own
   * canonical spelling — `/` and any unmatched path both render the workspaces
   * picker, so `/`, `/workspaces` and `/nonsense` were three URLs for one page
   * and whichever one you arrived on stayed in the address bar forever. App
   * replaces the URL with this on sync.
   */
  canonical?: string
  /**
   * The pathname matched no route. App renders a "Page not found" view (with a
   * link to the closest real route) instead of silently redirecting to Home.
   */
  notFound?: boolean
}

const PANEL_SET = new Set<RunPanel>(['logs', 'outputs', 'lineage', 'details', 'checkpoints'])

/** Map panel path segment → FocusRunPanel store value (artifacts for outputs). */
export function panelToFocus(panel?: RunPanel): 'logs' | 'artifacts' | 'lineage' | 'debug' | 'checkpoints' | null {
  if (!panel) return null
  if (panel === 'outputs') return 'artifacts'
  // Legacy /details (old Summary) → Overview (lineage panel).
  if (panel === 'details') return 'lineage'
  return panel
}

export function parsePathname(pathname: string, search = ''): ParsedPath {
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  const qs = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)

  if (parts.length === 0) {
    return { view: 'projects', canonical: '/workspaces' }
  }

  const [a, b, c, d, e] = parts

  if (a === 'login' || a === 'settings') {
    return { view: 'projects' }
  }
  if (a === '404') return { view: 'projects', notFound: true }

  if (a === 'workspaces') {
    if (!b) return { view: 'projects' }
    const W = safeDecode(b)
    if (!c) return { view: 'projects', workspaceId: W }
    if (c === 'editor') {
      if (d === 'pipelines' && e) {
        return {
          view: 'builder',
          workspaceId: W,
          editorPipeline: safeDecode(e),
          editorEnv: parts[5] ? safeDecode(parts[5]) : undefined,
        }
      }
      return { view: 'builder', workspaceId: W }
    }
    if (c === 'runs') {
      if (d === 'live') return { view: 'runs', workspaceId: W, runsTab: 'live' }
      if (d === 'compare') {
        const ids = (qs.get('ids') || '')
          .split(',')
          .map((x) => safeDecode(x.trim()))
          .filter(Boolean)
        return { view: 'experiments', workspaceId: W, runsTab: 'compare', compareIds: ids }
      }
      if (d) {
        const runId = safeDecode(d)
        const panel = e && PANEL_SET.has(e as RunPanel) ? (e as RunPanel) : undefined
        return { view: 'runs', workspaceId: W, runId, panel, runsTab: 'history' }
      }
      return { view: 'runs', workspaceId: W, runsTab: 'history' }
    }
    if (c === 'models') {
      return {
        view: 'models' as AppView,
        workspaceId: W,
        modelName: d ? safeDecode(d) : undefined,
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
    // `/workspaces/:id/templates`, `/workspaces/:id/plugins`, `/workspaces/:id/builder`, …
    // used to silently land on Home. Redirect aliases; 404 anything else.
    const wsAlias = resolveRouteAlias(pathname, W)
    if (wsAlias) return aliasTo(wsAlias, search)
    return { view: 'projects', workspaceId: W, notFound: true }
  }

  if (a === 'templates') return { view: 'templates' }
  if (a === 'agent' && b === 'inbox') {
    return { view: 'proposals', proposalId: c ? safeDecode(c) : undefined }
  }
  if (a === 'library') {
    // Datasets library catalog (shared Inputs/Outputs) may remain as secondary CTA.
    // Models stay workspace-strip only — global URL lands on picker.
    if (b === 'datasets') return { view: 'data' }
    if (b === 'models') {
      return { view: 'projects', canonical: '/workspaces' }
    }
    if (b === 'plugins') return { view: 'plugins' }
    if (b === 'artifacts') {
      // Library Artifacts removed — redirect to Runs (resolve artifact id in App).
      const runId = (qs.get('run_id') || qs.get('runId') || '').trim() || undefined
      const artifactId =
        (qs.get('artifactId') || qs.get('artifact_id') || '').trim() || undefined
      let W: string | undefined
      try {
        W = localStorage.getItem('graphyn.activeProject')?.trim() || undefined
      } catch {
        W = undefined
      }
      if (runId && W) {
        return {
          view: 'runs',
          workspaceId: W,
          runId,
          panel: 'outputs',
          canonical: `/workspaces/${encodeURIComponent(W)}/runs/${encodeURIComponent(runId)}/outputs`,
        }
      }
      if (artifactId) {
        // No canonical yet — App must resolve the id first. A premature
        // replace to /runs?artifactId= drops the /library/artifacts path and
        // never triggers resolve (workspace /runs ignores that query).
        return {
          view: W ? 'runs' : 'projects',
          workspaceId: W,
          resolveArtifactId: artifactId,
          legacyArtifactsOutputs: true,
        }
      }
      return {
        view: W ? 'runs' : 'projects',
        workspaceId: W,
        canonical: W ? `/workspaces/${encodeURIComponent(W)}/runs` : '/workspaces',
      }
    }
  }
  if (a === 'deploy') {
    if (b === 'ship') {
      return { view: 'projects', canonical: '/workspaces' }
    }
    if (b === 'workers') return { view: 'workers' }
  }
  if (a === 'admin') {
    // Legacy /admin/secrets bookmarks → Credentials (sole secret/connection UI)
    if (b === 'secrets') return { view: 'credentials', canonical: '/admin/credentials' }
    if (b === 'credentials') return { view: 'credentials' }
    if (b === 'ops') return { view: 'system' }
    if (b === 'access') return { view: 'access' as AppView }
  }

  // Short / legacy spellings (`/plugins`, `/ops`, `/runs`, …) → their real route.
  const alias = resolveRouteAlias(pathname, rememberedWorkspace())
  if (alias) return aliasTo(alias, search)

  return { view: 'projects', notFound: true }
}

/** Parse `target` and mark it as the canonical URL to replace the alias with. */
function aliasTo(target: string, search: string): ParsedPath {
  const parsed = parsePathname(target, search)
  // A redirect target must itself be a real route — never loop or chain.
  if (parsed.notFound) return { view: 'projects', notFound: true }
  return { ...parsed, canonical: parsed.canonical ?? target }
}

/** Last active workspace (localStorage) — scopes `/runs`, `/editor`, … aliases. */
function rememberedWorkspace(): string | null {
  try {
    return globalThis.localStorage?.getItem('graphyn.activeProject')?.trim() || null
  } catch {
    return null
  }
}

/** Global pages: alias word → canonical path. */
const GLOBAL_ALIAS: Record<string, string> = {
  plugins: '/library/plugins',
  plugin: '/library/plugins',
  library: '/library/plugins',
  packs: '/library/plugins',
  templates: '/templates',
  template: '/templates',
  ops: '/admin/ops',
  system: '/admin/ops',
  admin: '/admin/ops',
  maintenance: '/admin/ops',
  credentials: '/admin/credentials',
  secrets: '/admin/credentials',
  access: '/admin/access',
  workers: '/deploy/workers',
  worker: '/deploy/workers',
  fleet: '/deploy/workers',
  deploy: '/deploy/workers',
  inbox: '/agent/inbox',
  proposals: '/agent/inbox',
  agent: '/agent/inbox',
}

/** Workspace pages: alias word → segment under `/workspaces/:id` ('' = Home). */
const WORKSPACE_ALIAS: Record<string, string> = {
  home: '',
  overview: '',
  editor: 'editor',
  builder: 'editor',
  canvas: 'editor',
  runs: 'runs',
  run: 'runs',
  history: 'runs',
  compare: 'runs/compare',
  experiments: 'runs/compare',
  models: 'models',
  model: 'models',
  ship: 'ship',
  edge: 'ship',
  devices: 'ship/devices',
  datasets: 'datasets',
  dataset: 'datasets',
  data: 'datasets',
}

/** Workspace segments with a global fallback when no workspace is known. */
const WORKSPACE_SEGMENT_NO_WS: Record<string, string> = {
  datasets: '/library/datasets',
}

/** `/workspaces/:id/<seg>` segments that are already real routes (never aliased). */
const REAL_WORKSPACE_SEGMENTS = new Set(['editor', 'runs', 'models', 'datasets', 'ship', 'agent'])

/**
 * Redirect target for a short / legacy / mis-scoped URL, or null when the
 * path is either a real route or truly unknown (→ 404).
 *
 * - `/plugins` → `/library/plugins`, `/ops` → `/admin/ops`, `/templates/…`,
 *   `/credentials`, `/workers`, `/inbox`, `/library` → Plugins, `/admin` → Ops …
 * - Workspace pages (`/runs`, `/editor`, `/models`, `/ship`, `/datasets`,
 *   `/home`, `/compare`) → `/workspaces/<workspaceId>/…`, keeping any tail
 *   (`/runs/abc/logs` → `/workspaces/W/runs/abc/logs`). Without a workspace →
 *   `/workspaces` (picker); `/datasets` → `/library/datasets`.
 * - `/workspaces/:id/<global page>` (templates, plugins, ops, …) → the global page;
 *   `/workspaces/:id/<alias>` (builder, data, edge, compare, home) → the real segment.
 * - `/library/templates` → `/templates`, `/admin/system` → `/admin/ops`,
 *   `/admin/workers` → `/deploy/workers`.
 *
 * Pure apart from its arguments — `workspaceId` is the active workspace.
 */
export function resolveRouteAlias(pathname: string, workspaceId?: string | null): string | null {
  const raw = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  if (raw.length === 0) return null
  const parts = raw.map((p) => p.toLowerCase())
  const W = workspaceId?.trim() || null
  const wsBase = (id: string) => `/workspaces/${encodeURIComponent(id)}`

  if (parts[0] === 'workspaces') {
    if (raw.length < 3) return null
    const id = safeDecode(raw[1])
    const seg = parts[2]
    if (REAL_WORKSPACE_SEGMENTS.has(seg)) return null
    if (seg in WORKSPACE_ALIAS) {
      const target = WORKSPACE_ALIAS[seg]
      const tail = raw.slice(3).join('/')
      const base = target ? `${wsBase(id)}/${target}` : wsBase(id)
      return tail && target && !target.includes('/') ? `${base}/${tail}` : base
    }
    if (seg in GLOBAL_ALIAS) return GLOBAL_ALIAS[seg]
    return null
  }

  // Two-segment legacy spellings under real prefixes.
  if (parts[0] === 'library' && parts[1] === 'templates') return '/templates'
  if (parts[0] === 'library' && parts[1] === 'plugin') return '/library/plugins'
  if (parts[0] === 'admin' && (parts[1] === 'system' || parts[1] === 'maintenance')) return '/admin/ops'
  if (parts[0] === 'admin' && (parts[1] === 'workers' || parts[1] === 'fleet')) return '/deploy/workers'
  if (parts[0] === 'admin' && parts[1] === 'inbox') return '/agent/inbox'
  if (parts[0] === 'deploy' && parts[1] === 'fleet') return '/deploy/workers'

  const head = parts[0]
  if (head in WORKSPACE_ALIAS) {
    const target = WORKSPACE_ALIAS[head]
    if (!W) return WORKSPACE_SEGMENT_NO_WS[target] ?? '/workspaces'
    const base = target ? `${wsBase(W)}/${target}` : wsBase(W)
    const tail = raw.slice(1).join('/')
    // Keep a tail only for single-segment targets (`/runs/<id>/logs`), never `/compare/x`.
    return tail && target && !target.includes('/') ? `${base}/${tail}` : base
  }
  // Only a bare global word redirects (`/plugins`), plus a short tail on the
  // pages that own sub-routes (`/inbox/<proposal>`) — `/plugins/foo/bar` is a 404.
  if (head in GLOBAL_ALIAS) {
    if (raw.length === 1) return GLOBAL_ALIAS[head]
    if ((head === 'inbox' || head === 'proposals') && raw.length === 2) {
      return `/agent/inbox/${raw[1]}`
    }
    return null
  }
  if (head === 'projects' || head === 'workspace') return W ? wsBase(W) : '/workspaces'
  return null
}

/** Global routes that need no workspace, keyed by the words people type. */
const GLOBAL_ROUTE_ALIASES: Array<{ words: string[]; path: string; label: string }> = [
  { words: ['plugins', 'plugin', 'packs', 'nodes'], path: '/library/plugins', label: 'Plugins' },
  { words: ['datasets', 'dataset', 'data', 'inputs', 'outputs'], path: '/library/datasets', label: 'Datasets library' },
  { words: ['credentials', 'credential', 'secrets', 'secret', 'connections'], path: '/admin/credentials', label: 'Credentials' },
  { words: ['ops', 'system', 'schedules', 'schedule', 'webhooks', 'audit', 'health'], path: '/admin/ops', label: 'Ops' },
  { words: ['access', 'users', 'rbac', 'roles'], path: '/admin/access', label: 'Access' },
  { words: ['workers', 'worker', 'fleet', 'queue'], path: '/deploy/workers', label: 'Worker fleet' },
  { words: ['templates', 'template', 'marketplace', 'examples'], path: '/templates', label: 'Templates' },
  { words: ['inbox', 'proposals', 'proposal', 'agent'], path: '/agent/inbox', label: 'Agent inbox' },
  { words: ['projects', 'project', 'workspace', 'home'], path: '/workspaces', label: 'Workspaces' },
]

/** Workspace-scoped routes (need an open workspace). */
const WORKSPACE_ROUTE_ALIASES: Array<{ words: string[]; seg: string; label: string }> = [
  { words: ['editor', 'builder', 'canvas', 'graph'], seg: 'editor', label: 'Editor' },
  { words: ['runs', 'run', 'history', 'live', 'trace', 'lineage', 'artifacts', 'outputs'], seg: 'runs', label: 'Runs' },
  { words: ['compare', 'experiments'], seg: 'runs/compare', label: 'Compare runs' },
  { words: ['models', 'model'], seg: 'models', label: 'Models' },
  { words: ['ship', 'edge', 'deploy', 'devices'], seg: 'ship', label: 'Ship' },
]

/**
 * Best guess at the real route a mistyped / legacy URL meant — `/plugins` →
 * `/library/plugins`, `/credentials` → `/admin/credentials`. Workspace routes
 * resolve only when `workspaceId` is known. Returns null when nothing fits.
 */
export function suggestRouteFor(
  pathname: string,
  workspaceId?: string | null,
): { path: string; label: string } | null {
  const words = pathname
    .toLowerCase()
    .split('/')
    .map((w) => w.trim())
    .filter(Boolean)
  // Last segment first ("/library/foo/plugins" → plugins), then earlier ones.
  for (const word of [...words].reverse()) {
    const ws = WORKSPACE_ROUTE_ALIASES.find((r) => r.words.includes(word))
    if (ws && workspaceId) {
      return { path: `/workspaces/${encodeURIComponent(workspaceId)}/${ws.seg}`, label: ws.label }
    }
    const g = GLOBAL_ROUTE_ALIASES.find((r) => r.words.includes(word))
    if (g) return { path: g.path, label: g.label }
  }
  return null
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
