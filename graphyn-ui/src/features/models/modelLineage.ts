/**
 * Models → lineage view model from `GET /models/{name}/lineage` (pure; tested).
 *
 * Contract: `{ name, description, stages: {<stage>: {stage, run_id, node_id,
 * path_id, artifact_path, format, model_hash, model_file_count, updated_at,
 * made_from: {run_id, sealed, record_hash, graph_hash, graph_name, seed,
 * datasets:[{node_id,key,label,path,content_hash,file_count,dataset_version}],
 * node:{node_id,node_type,label,plugin,plugin_version,code_hash}|null,
 * step_config:{…}|null, environment:{python,image,graphyn_version,git_commit}|null}|null}},
 * pending_prod, used_in:[{run_id, short, created_at, status, trigger, actor,
 * actor_verified, graph_name, project, archived, stage, match, package:{path,
 * node_id,sha256,content_hash}|null}], packages:[{package_id, project, status,
 * env, stage, run_id, created_at, sha256}] }`.
 *
 * Older APIs answer 404 → the page keeps its client-side fallback.
 */
import { humanNodeLabel } from '../../lib/format'

type Rec = Record<string, unknown>

function asRec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  if (typeof v === 'string') return v.trim()
  if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  return ''
}

function num(v: unknown): number | null {
  const n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** One stage vocabulary everywhere: staging → "Staging", prod → "Production", latest → "Latest". */
export function modelStageLabel(stage: unknown): string {
  const s = str(stage).toLowerCase()
  if (s === 'prod' || s === 'production') return 'Production'
  if (s === 'staging' || s === 'testing') return 'Staging'
  if (s === 'latest') return 'Latest'
  if (!s) return ''
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** "sha256:b30993f454cc…" → "b30993f4". */
export function shortHash(h: unknown, n = 8): string {
  const s = str(h).replace(/^sha256:/i, '')
  return s.length > n ? s.slice(0, n) : s
}

export type LineageDataset = {
  nodeId: string
  key: string
  label: string
  path: string
  hash: string
  fileCount: number | null
  datasetVersion: string
}

export type LineageStep = {
  nodeId: string
  nodeType: string
  label: string
  plugin: string
  pluginVersion: string
  codeHash: string
}

export type LineageMadeFrom = {
  runId: string
  sealed: boolean | null
  recordHash: string
  graphHash: string
  graphName: string
  seed: number | null
  datasets: LineageDataset[]
  step: LineageStep | null
  /** Scalar step settings (`key → formatted value`), natural key order. */
  settings: Array<{ key: string; value: string }>
  environment: Array<{ label: string; value: string }>
}

export type LineageStage = {
  stage: string
  label: string
  runId: string
  nodeId: string
  pathId: string
  artifactPath: string
  format: string
  modelHash: string
  modelFileCount: number | null
  updatedAt: string
  madeFrom: LineageMadeFrom | null
}

export type LineageUse = {
  runId: string
  short: string
  createdAt: string
  status: string
  trigger: string
  actor: string
  actorVerified: boolean | null
  graphName: string
  project: string
  archived: boolean
  stage: string
  stageLabel: string
  match: string
  packageSha: string
  packagePath: string
}

export type LineagePackage = {
  packageId: string
  project: string
  status: string
  env: string
  stage: string
  stageLabel: string
  runId: string
  createdAt: string
  sha256: string
}

export type ModelLineageView = {
  name: string
  description: string
  stages: LineageStage[]
  pendingProd: Rec | null
  usedIn: LineageUse[]
  packages: LineagePackage[]
}

const STAGE_ORDER = ['staging', 'prod', 'production', 'latest']

function settingValue(v: unknown): string | null {
  if (v == null) return null
  if (typeof v === 'string') return v.length > 80 ? `${v.slice(0, 77)}…` : v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v) && v.length <= 6 && v.every((x) => ['string', 'number', 'boolean'].includes(typeof x))) {
    return v.join(', ')
  }
  return null
}

/** Scalar step settings (objects / long lists skipped), sorted by key. */
export function stepSettings(cfg: unknown): Array<{ key: string; value: string }> {
  const r = asRec(cfg)
  if (!r) return []
  const out: Array<{ key: string; value: string }> = []
  for (const [key, v] of Object.entries(r)) {
    const value = settingValue(v)
    if (value != null && value !== '') out.push({ key, value })
  }
  return out.sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }))
}

function environmentRows(env: unknown): Array<{ label: string; value: string }> {
  const r = asRec(env)
  if (!r) return []
  const rows: Array<{ label: string; value: string }> = []
  const add = (label: string, v: unknown, short = false) => {
    const s = str(v)
    if (s) rows.push({ label, value: short ? shortHash(s, 10) : s })
  }
  add('Python', r.python)
  add('Graphyn', r.graphyn_version)
  add('Image', r.image)
  add('Git', r.git_commit, true)
  return rows
}

function parseMadeFrom(raw: unknown): LineageMadeFrom | null {
  const m = asRec(raw)
  if (!m) return null
  const datasets: LineageDataset[] = []
  for (const d of Array.isArray(m.datasets) ? m.datasets : []) {
    const o = asRec(d)
    if (!o) continue
    const path = str(o.path)
    datasets.push({
      nodeId: str(o.node_id),
      key: str(o.key),
      label: str(o.label) || path.split('/').filter(Boolean).pop() || str(o.node_id),
      path,
      hash: str(o.content_hash),
      fileCount: num(o.file_count),
      datasetVersion: str(o.dataset_version),
    })
  }
  const n = asRec(m.node)
  const step: LineageStep | null = n
    ? {
        nodeId: str(n.node_id),
        nodeType: str(n.node_type),
        label: str(n.label) || humanNodeLabel(str(n.node_type) || str(n.node_id)),
        plugin: str(n.plugin),
        pluginVersion: str(n.plugin_version),
        codeHash: str(n.code_hash),
      }
    : null
  return {
    runId: str(m.run_id),
    sealed: typeof m.sealed === 'boolean' ? m.sealed : null,
    recordHash: str(m.record_hash),
    graphHash: str(m.graph_hash),
    graphName: str(m.graph_name),
    seed: num(m.seed),
    datasets,
    step,
    settings: stepSettings(m.step_config),
    environment: environmentRows(m.environment),
  }
}

/** Parse the lineage payload; null when it is not an object. */
export function buildModelLineage(raw: unknown): ModelLineageView | null {
  const r = asRec(raw)
  if (!r) return null
  const stagesRec = asRec(r.stages) || {}
  const stages: LineageStage[] = []
  for (const [key, v] of Object.entries(stagesRec)) {
    const s = asRec(v)
    if (!s) continue
    const stage = str(s.stage) || key
    stages.push({
      stage,
      label: modelStageLabel(stage),
      runId: str(s.run_id),
      nodeId: str(s.node_id),
      pathId: str(s.path_id),
      artifactPath: str(s.artifact_path),
      format: str(s.format),
      modelHash: str(s.model_hash),
      modelFileCount: num(s.model_file_count),
      updatedAt: str(s.updated_at),
      madeFrom: parseMadeFrom(s.made_from),
    })
  }
  const rank = (s: string) => {
    const i = STAGE_ORDER.indexOf(s.toLowerCase())
    return i < 0 ? STAGE_ORDER.length : i
  }
  stages.sort((a, b) => rank(a.stage) - rank(b.stage))
  const usedIn: LineageUse[] = []
  for (const u of Array.isArray(r.used_in) ? r.used_in : []) {
    const o = asRec(u)
    const runId = o ? str(o.run_id) : ''
    if (!o || !runId) continue
    const pkg = asRec(o.package)
    usedIn.push({
      runId,
      short: str(o.short) || runId.slice(0, 8),
      createdAt: str(o.created_at),
      status: str(o.status),
      trigger: str(o.trigger),
      actor: str(o.actor),
      actorVerified: typeof o.actor_verified === 'boolean' ? o.actor_verified : null,
      graphName: str(o.graph_name),
      project: str(o.project),
      archived: o.archived === true,
      stage: str(o.stage),
      stageLabel: modelStageLabel(o.stage),
      match: str(o.match),
      packageSha: pkg ? str(pkg.sha256) || str(pkg.content_hash) : '',
      packagePath: pkg ? str(pkg.path) : '',
    })
  }
  usedIn.sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0))
  const packages: LineagePackage[] = []
  for (const p of Array.isArray(r.packages) ? r.packages : []) {
    const o = asRec(p)
    if (!o) continue
    packages.push({
      packageId: str(o.package_id),
      project: str(o.project),
      status: str(o.status),
      env: str(o.env),
      stage: str(o.stage),
      stageLabel: modelStageLabel(o.stage),
      runId: str(o.run_id),
      createdAt: str(o.created_at),
      sha256: str(o.sha256),
    })
  }
  return {
    name: str(r.name),
    description: str(r.description),
    stages,
    pendingProd: asRec(r.pending_prod),
    usedIn,
    packages,
  }
}

/** Lineage stage for a registry stage key ('prod' also matches 'production'). */
export function lineageStageFor(view: ModelLineageView | null, stage: string): LineageStage | null {
  if (!view) return null
  const want = modelStageLabel(stage)
  return view.stages.find((s) => s.label === want) ?? null
}

/** "speech-commands · 3f2a9c1b · 1,204 files · v3" — dataset one-liner. */
export function datasetLine(d: LineageDataset): string {
  const parts = [d.label]
  if (d.hash) parts.push(shortHash(d.hash))
  if (d.fileCount != null) parts.push(`${d.fileCount.toLocaleString('en-US')} file${d.fileCount === 1 ? '' : 's'}`)
  if (d.datasetVersion) parts.push(d.datasetVersion)
  return parts.join(' · ')
}

/** "Trainer · keras-trainer 1.4.2 · code 9ac1e2f0" — producing step one-liner. */
export function stepLine(s: LineageStep): string {
  const parts = [s.label]
  const plugin = [s.plugin, s.pluginVersion].filter(Boolean).join(' ')
  if (plugin) parts.push(plugin)
  if (s.codeHash) parts.push(`code ${shortHash(s.codeHash)}`)
  return parts.join(' · ')
}
