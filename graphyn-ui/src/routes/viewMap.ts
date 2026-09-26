/**
 * Map AppView ids → path builders (path-era navigation).
 */

import type { AppView } from '../store/appStore'
import { paths, type RunPanel } from './paths'

export type ViewPathContext = {
  workspaceId?: string | null
  runId?: string | null
  /** For `trace` → lineage panel under a run. */
  panel?: RunPanel
  /** Prefer workspace datasets when a workspace is open. */
  preferWorkspaceDatasets?: boolean
}

/**
 * Resolve an AppView (+ optional entity context) to a History API path.
 * Returns `null` when the view needs a workspace id that is missing
 * (caller should fall back to `/workspaces` or keep current view).
 */
export function pathForView(view: AppView, ctx: ViewPathContext = {}): string | null {
  const W = ctx.workspaceId?.trim() || null

  switch (view) {
    case 'projects':
      return W ? paths.workspace(W) : paths.workspaces()

    case 'builder':
      return W ? paths.editor(W) : null

    case 'runs':
      if (!W) return null
      if (ctx.runId) return paths.run(W, ctx.runId)
      return paths.runs(W)

    case 'data':
      // Workspace-strip only in the rail. Secondary /library/datasets catalog is
      // opened via explicit "Browse shared library" CTA, not go('data').
      if (!W) return null
      return paths.datasets(W)

    case 'plugins':
      return paths.libraryPlugins()

    case 'templates':
      return paths.templates()

    case 'proposals':
      return paths.agentInbox()

    case 'edge':
      return W ? paths.ship(W) : null

    case 'devices':
      return W ? paths.shipDevices(W) : null

    case 'workers':
      return paths.deployWorkers()

    case 'secrets':
      return paths.adminSecrets()
    case 'credentials':
      return paths.adminCredentials()

    case 'system':
      return paths.adminOps()

    case 'artifacts':
      return paths.libraryArtifacts()

    case 'experiments':
      return W ? paths.runsCompare(W) : null

    case 'models':
      return W ? paths.models(W) : null

    case 'access':
      return paths.adminAccess()

    default:
      return null
  }
}

/** Static hints for nav labels — path pattern without ids. */
export const VIEW_PATH_HINT: Record<AppView, string> = {
  projects: '/workspaces',
  builder: '/workspaces/:id/editor',
  runs: '/workspaces/:id/runs',
  artifacts: '/library/artifacts',
  plugins: '/library/plugins',
  templates: '/templates',
  data: '/workspaces/:id/datasets',
  system: '/admin/ops',
  secrets: '/admin/secrets',
  credentials: '/admin/credentials',
  workers: '/deploy/workers',
  edge: '/workspaces/:id/ship',
  experiments: '/workspaces/:id/runs/compare',
  proposals: '/agent/inbox',
  models: '/workspaces/:id/models',
  access: '/admin/access',
  devices: '/workspaces/:id/ship/devices',
}
