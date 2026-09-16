/**
 * Typed path builders for Graphyn console (UI_NORTH_STAR §4.3).
 * Prefer these over ad-hoc string URLs or hash fragments.
 */

export type RunPanel = 'logs' | 'outputs' | 'lineage' | 'details' | 'checkpoints'

function enc(segment: string): string {
  return encodeURIComponent(segment)
}

function withSearch(path: string, params: Record<string, string | undefined>): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') qs.set(k, v)
  }
  const s = qs.toString()
  return s ? `${path}?${s}` : path
}

export const paths = {
  workspaces: () => '/workspaces',

  workspace: (id: string) => `/workspaces/${enc(id)}`,

  editor: (id: string, pipeline?: string, env?: string) => {
    const base = `/workspaces/${enc(id)}/editor`
    if (!pipeline) return base
    const withPipe = `${base}/pipelines/${enc(pipeline)}`
    return env ? `${withPipe}/${enc(env)}` : withPipe
  },

  runs: (id: string) => `/workspaces/${enc(id)}/runs`,

  run: (id: string, runId: string) => `/workspaces/${enc(id)}/runs/${enc(runId)}`,

  runPanel: (id: string, runId: string, panel: RunPanel) =>
    `/workspaces/${enc(id)}/runs/${enc(runId)}/${panel}`,

  runsLive: (id: string) => `/workspaces/${enc(id)}/runs/live`,

  runsCompare: (id: string, runIds?: string[]) => {
    const base = `/workspaces/${enc(id)}/runs/compare`
    if (!runIds?.length) return base
    return `${base}?ids=${runIds.map(enc).join(',')}`
  },

  models: (id: string) => `/workspaces/${enc(id)}/models`,

  model: (id: string, name: string) => `/workspaces/${enc(id)}/models/${enc(name)}`,

  datasets: (id: string) => `/workspaces/${enc(id)}/datasets`,

  ship: (id: string) => `/workspaces/${enc(id)}/ship`,

  shipDevices: (id: string) => `/workspaces/${enc(id)}/ship/devices`,

  templates: () => '/templates',

  agentInbox: () => '/agent/inbox',

  proposal: (pid: string) => `/agent/inbox/${enc(pid)}`,

  libraryDatasets: () => '/library/datasets',

  libraryPlugins: () => '/library/plugins',

  libraryArtifacts: (q?: { artifactId?: string }) =>
    withSearch('/library/artifacts', { artifactId: q?.artifactId }),

  libraryModels: () => '/library/models',

  deployShip: () => '/deploy/ship',

  deployShipDevices: () => '/deploy/ship/devices',

  deployWorkers: () => '/deploy/workers',

  deployQueue: () => '/deploy/workers/queue',

  adminSecrets: () => '/admin/secrets',

  adminOps: () => '/admin/ops',

  adminAudit: () => '/admin/ops/audit',

  adminAccess: () => '/admin/access',

  settings: () => '/settings',

  login: (returnTo?: string) => withSearch('/login', { returnTo }),

  notFound: () => '/404',
} as const
