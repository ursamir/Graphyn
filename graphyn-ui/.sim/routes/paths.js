"use strict";Object.defineProperty(exports, "__esModule", {value: true}); function _optionalChain(ops) { let lastAccessLHS = undefined; let value = ops[0]; let i = 1; while (i < ops.length) { const op = ops[i]; const fn = ops[i + 1]; i += 2; if ((op === 'optionalAccess' || op === 'optionalCall') && value == null) { return undefined; } if (op === 'access' || op === 'optionalAccess') { lastAccessLHS = value; value = fn(value); } else if (op === 'call' || op === 'optionalCall') { value = fn((...args) => value.call(lastAccessLHS, ...args)); lastAccessLHS = undefined; } } return value; }/**
 * Typed path builders for Graphyn console (UI_NORTH_STAR §4.3).
 * Prefer these over ad-hoc string URLs or hash fragments.
 */



function enc(segment) {
  return encodeURIComponent(segment)
}

function withSearch(path, params) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') qs.set(k, v)
  }
  const s = qs.toString()
  return s ? `${path}?${s}` : path
}

 const paths = {
  workspaces: () => '/workspaces',

  workspace: (id) => `/workspaces/${enc(id)}`,

  editor: (id, pipeline, env) => {
    const base = `/workspaces/${enc(id)}/editor`
    if (!pipeline) return base
    const withPipe = `${base}/pipelines/${enc(pipeline)}`
    return env ? `${withPipe}/${enc(env)}` : withPipe
  },

  runs: (id) => `/workspaces/${enc(id)}/runs`,

  run: (id, runId) => `/workspaces/${enc(id)}/runs/${enc(runId)}`,

  runPanel: (id, runId, panel) =>
    `/workspaces/${enc(id)}/runs/${enc(runId)}/${panel}`,

  runsLive: (id) => `/workspaces/${enc(id)}/runs/live`,

  runsCompare: (id, runIds) => {
    const base = `/workspaces/${enc(id)}/runs/compare`
    if (!_optionalChain([runIds, 'optionalAccess', _ => _.length])) return base
    return `${base}?ids=${runIds.map(enc).join(',')}`
  },

  models: (id) => `/workspaces/${enc(id)}/models`,

  model: (id, name) => `/workspaces/${enc(id)}/models/${enc(name)}`,

  datasets: (id) => `/workspaces/${enc(id)}/datasets`,

  ship: (id) => `/workspaces/${enc(id)}/ship`,

  shipDevices: (id) => `/workspaces/${enc(id)}/ship/devices`,

  templates: () => '/templates',

  agentInbox: () => '/agent/inbox',

  proposal: (pid) => `/agent/inbox/${enc(pid)}`,

  libraryDatasets: () => '/library/datasets',

  libraryPlugins: () => '/library/plugins',

  libraryArtifacts: (q) =>
    withSearch('/library/artifacts', { artifactId: _optionalChain([q, 'optionalAccess', _2 => _2.artifactId]) }),

  libraryModels: () => '/library/models',

  deployShip: () => '/deploy/ship',

  deployWorkers: () => '/deploy/workers',

  deployQueue: () => '/deploy/workers/queue',

  adminSecrets: () => '/admin/secrets',

  adminOps: () => '/admin/ops',

  adminAudit: () => '/admin/ops/audit',

  adminAccess: () => '/admin/access',

  settings: () => '/settings',

  login: (returnTo) => withSearch('/login', { returnTo }),

  notFound: () => '/404',
} ; exports.paths = paths
