/**
 * Map legacy hash routes (`#/...`) to HTML5 History paths (UI_NORTH_STAR §4.3.4).
 */

import { paths } from './paths'

export type LegacyHashContext = {
  /** Active / last workspace id when the hash does not carry one. */
  activeProject?: string | null
}

/**
 * Parse `window.location.hash` (or any `#/...` string) into a path target.
 * Returns `null` when the hash is empty or not a legacy app route.
 */
export function resolveLegacyHash(
  hash: string,
  ctx: LegacyHashContext = {},
): string | null {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash
  if (!raw || raw === '/') return null

  // Only treat `#/...` app routes; ignore in-page anchors without `/`.
  const normalized = raw.startsWith('/') ? raw : `/${raw}`
  if (!normalized.startsWith('/')) return null

  let pathname: string
  let search = ''
  const qIdx = normalized.indexOf('?')
  if (qIdx >= 0) {
    pathname = normalized.slice(0, qIdx)
    search = normalized.slice(qIdx + 1)
  } else {
    pathname = normalized
  }

  const params = new URLSearchParams(search)
  const segments = pathname.replace(/^\/+|\/+$/g, '').split('/').filter(Boolean)
  const view = segments[0] ?? ''
  const rest = segments.slice(1)
  const W = ctx.activeProject?.trim() || params.get('project')?.trim() || null

  const needWorkspace = (fn: (id: string) => string, fallback: string) =>
    W ? fn(W) : fallback

  switch (view) {
    case 'projects': {
      const project = params.get('project')?.trim()
      return project ? paths.workspace(project) : paths.workspaces()
    }

    case 'builder':
      return needWorkspace((id) => paths.editor(id), paths.workspaces())

    case 'runs': {
      if (params.get('tab') === 'compare') {
        return needWorkspace((id) => paths.runsCompare(id), paths.workspaces())
      }
      const runId = rest[0]
      if (runId) {
        return needWorkspace((id) => paths.run(id, runId), `${paths.workspaces()}?run=${encodeURIComponent(runId)}`)
      }
      return needWorkspace((id) => paths.runs(id), paths.workspaces())
    }

    case 'experiments':
      return needWorkspace((id) => paths.runsCompare(id), paths.workspaces())

    case 'trace': {
      const runId = params.get('run_id')?.trim()
      const artifactId = params.get('artifact_id')?.trim()
      if (runId) {
        return needWorkspace(
          (id) => paths.runPanel(id, runId, 'lineage'),
          `${paths.workspaces()}?run=${encodeURIComponent(runId)}&panel=lineage`,
        )
      }
      if (artifactId) {
        return paths.libraryArtifacts({ artifactId })
      }
      return needWorkspace((id) => paths.runs(id), paths.workspaces())
    }

    case 'data':
      return W ? paths.datasets(W) : paths.libraryDatasets()

    case 'artifacts':
      return paths.libraryArtifacts(
        params.get('artifactId') || params.get('artifact_id')
          ? { artifactId: (params.get('artifactId') || params.get('artifact_id'))! }
          : undefined,
      )

    case 'templates':
      return paths.templates()

    case 'proposals': {
      const pid = rest[0] || params.get('id')?.trim()
      return pid ? paths.proposal(pid) : paths.agentInbox()
    }

    case 'edge':
      return W ? paths.ship(W) : paths.deployShip()

    case 'workers':
      return paths.deployWorkers()

    case 'secrets':
      return paths.adminSecrets()

    case 'system':
      return paths.adminOps()

    case 'plugins':
      return paths.libraryPlugins()

    case 'models':
      return needWorkspace((id) => paths.models(id), paths.libraryModels())

    case 'access':
      return paths.adminAccess()

    case 'settings':
      return paths.settings()

    case 'login':
      return paths.login(params.get('returnTo') ?? undefined)

    default:
      return null
  }
}
