/**
 * Pure helpers for Runs → Run outputs / run detail chrome.
 * No React here so they can be unit-tested in the node vitest env.
 */
import { detectFileKind } from '../../lib/fileKind'
import { naturalCompare } from '../../lib/naturalSort'

export interface OutputFileLike {
  name: string
  path: string
  size: number
  kind: string
  node_id?: string | null
}

export type NodeTruncation = { shown: number; total: number }

export type NormalizedOutputs<F extends OutputFileLike = OutputFileLike> = {
  files: F[]
  /** True when the server capped the listing (whole run or some node). */
  truncated: boolean
  /** node_id → {shown, total} for nodes whose files were capped/summarized. */
  truncatedByNode: Record<string, NodeTruncation>
}

function toInt(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : null
}

/**
 * GET /runs/{id}/outputs is a bare list (legacy) or, with `?with_meta=1`,
 * `{items, truncated, max_items, truncated_by_node: {nid: {shown, total}}}`.
 * Also tolerates `files` / `outputs` and `total_by_node: {nid: total}`.
 */
export function normalizeOutputsResponse<F extends OutputFileLike = OutputFileLike>(raw: unknown): NormalizedOutputs<F> {
  if (Array.isArray(raw)) {
    const files = (raw as F[]).filter((f) => !isInternalRunFile(f.path, f.name))
    return { files, truncated: false, truncatedByNode: {} }
  }
  if (!raw || typeof raw !== 'object') return { files: [], truncated: false, truncatedByNode: {} }
  const o = raw as Record<string, unknown>
  const rawList = (Array.isArray(o.items) ? o.items : Array.isArray(o.files) ? o.files : Array.isArray(o.outputs) ? o.outputs : []) as F[]
  const list = rawList.filter((f) => !isInternalRunFile(f.path, f.name))
  const truncatedByNode: Record<string, NodeTruncation> = {}
  const tbn = o.truncated_by_node
  if (tbn && typeof tbn === 'object') {
    for (const [nid, v] of Object.entries(tbn as Record<string, unknown>)) {
      if (!nid || looksLikeOpaqueId(nid) || nid === 'run') continue
      if (!v || typeof v !== 'object') continue
      const total = toInt((v as Record<string, unknown>).total)
      const shown = toInt((v as Record<string, unknown>).shown)
      if (total == null) continue
      truncatedByNode[nid] = { shown: shown ?? list.filter((f) => f.node_id === nid).length, total }
    }
  }
  const totals = o.total_by_node
  if (totals && typeof totals === 'object') {
    for (const [nid, v] of Object.entries(totals as Record<string, unknown>)) {
      if (!nid || looksLikeOpaqueId(nid) || nid === 'run') continue
      const total = toInt(v)
      if (total == null || truncatedByNode[nid]) continue
      const shown = list.filter((f) => f.node_id === nid).length
      if (total > shown) truncatedByNode[nid] = { shown, total }
    }
  }
  const truncated = o.truncated === true || Object.keys(truncatedByNode).length > 0
  return { files: list, truncated, truncatedByNode }
}

/** Natural sort: 2.wav < 10.wav, nohash_2 < nohash_10 (hex-like ids kept intact — see lib/naturalSort). */
export { naturalCompare }

export function sortFilesNatural<F extends { name: string; path: string }>(files: F[]): F[] {
  return [...files].sort((x, y) => naturalCompare(x.name, y.name) || naturalCompare(x.path, y.path))
}

/** True for opaque run/artifact hex ids that must not appear as pipeline step titles. */
/** Plain-language title + hint for run-journal files (graph/meta/logs/prove…). */
export function runLevelFileCue(name: string): { title: string; hint: string } {
  const base = String(name || '')
    .replace(/\\/g, '/')
    .split('/')
    .pop()
    ?.trim() || String(name || '').trim()
  const n = base.toLowerCase()
  if (n === 'graph.json') {
    return { title: 'Pipeline graph', hint: 'How steps were wired for this run' }
  }
  if (n === 'meta.json') {
    return { title: 'Run summary', hint: 'Status, timing, and per-step stats' }
  }
  if (n === 'logs.json') {
    return { title: 'Event log', hint: 'Raw execution events (same story as Logs)' }
  }
  if (n === 'prove.json') {
    return { title: 'Reproducibility record', hint: 'Versions, hashes, and seed for replay' }
  }
  if (n === 'outputs_index.json') {
    return { title: 'Outputs index', hint: 'Internal inventory of written files' }
  }
  if (n === 'graph.logical.json') {
    return { title: 'Logical graph', hint: 'The graph before run-scoped output paths were stamped in' }
  }
  if (n === 'outputs_manifest.json') {
    return { title: 'Outputs manifest', hint: 'Every file the run wrote, with sizes and hashes' }
  }
  if (n === 'verify.json') {
    return { title: 'Verification record', hint: 'Hash-chain and replay check outcome' }
  }
  return { title: base || 'Run file', hint: 'Run journal file' }
}

export function looksLikeOpaqueId(id: string): boolean {
  const s = String(id || '').trim()
  if (!s) return false
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)) return true
  if (/^[0-9a-f]{16,}$/i.test(s)) return true
  return false
}

/** Internal run-cache files — never show as downloadable console outputs. */
export function isInternalRunFile(path: string, name?: string): boolean {
  const base = String(name || path.replace(/\\/g, '/').split('/').pop() || '')
    .trim()
    .toLowerCase()
  return base === 'outputs_index.json'
}

/**
 * Shorter path for the file-card subtitle: drop ``workspace/``, collapse
 * ``runs/<opaque-id>/…`` to the trailing relative path.
 */
export function shortOutputPath(path: string, opts?: { runId?: string | null }): string {
  let p = String(path || '').replace(/\\/g, '/').replace(/^workspace\//, '')
  if (!p) return path
  const runId = String(opts?.runId || '').trim()
  if (runId) {
    const needle = `runs/${runId}/`
    const i = p.toLowerCase().indexOf(needle.toLowerCase())
    if (i >= 0) {
      const rest = p.slice(i + needle.length)
      return rest || p
    }
  }
  const m = p.match(/(?:^|\/)runs\/([0-9a-f]{16,}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\/(.+)$/i)
  if (m?.[2]) return m[2]
  return p
}

/**
 * Group key for a downloadable file: graph node id, or ``run`` for journal /
 * run-dir files. Never returns a raw run id (that used to happen when
 * ``…/runs/<run_id>/outputs_index.json`` matched a loose ``/out`` regex).
 */
export function guessNodeFromPath(
  path: string,
  arts: Array<{ node_id?: string | null; node_type?: string | null; data_path?: string | null; path?: string | null }>,
  file?: { node_id?: string | null },
  opts?: { runId?: string | null },
): string {
  const runId = String(opts?.runId || '').trim()
  const fromApi = String(file?.node_id || '').trim()
  if (fromApi) {
    if (looksLikeOpaqueId(fromApi) || (runId && fromApi === runId)) return 'run'
    return fromApi
  }

  const posix = path.replace(/\\/g, '/')
  const lower = posix.toLowerCase()

  // workspace/runs/<run_id>/<file> → run-level journal (graph, meta, outputs_index, …)
  const journal = posix.match(/(?:^|\/)runs\/([^/]+)\/([^/]+)$/i)
  if (journal) {
    const rid = journal[1]
    if ((runId && rid === runId) || looksLikeOpaqueId(rid)) return 'run'
  }
  if (runId) {
    const needle = `/runs/${runId.toLowerCase()}/`
    if (lower.includes(needle) || lower.startsWith(`runs/${runId.toLowerCase()}/`)) {
      return 'run'
    }
  }

  for (const a of arts) {
    const dp = String(a.data_path || a.path || '').toLowerCase()
    if (dp && (lower.includes(dp) || dp.includes(lower) || lower.endsWith(dp.split('/').pop() || '___'))) {
      const nid = String(a.node_id || a.node_type || '').trim()
      if (!nid || looksLikeOpaqueId(nid)) continue
      return nid
    }
    const nid = String(a.node_id || '').trim()
    if (nid && !looksLikeOpaqueId(nid) && lower.includes(nid.toLowerCase())) return nid
  }

  // Path segments only — require a boundary after out|output|artifacts so
  // ``outputs_index.json`` does not match ``out``.
  const m =
    posix.match(/(?:^|\/)nodes?\/([^/]+)(?:\/|$)/i) ||
    posix.match(/\/([A-Za-z][A-Za-z0-9_-]*)\/(?:out|output|artifacts)(?:\/|$)/i)
  if (m?.[1] && !looksLikeOpaqueId(m[1])) return m[1]
  return 'run'
}

/**
 * Node ids in execution order. Sources in priority order:
 *  1. `node_stats[].node_index` (debug report / run summary)
 *  2. the run's embedded graph node order
 *  3. first appearance in journal events (`node_start`)
 */
export function executionOrderFromRun(input: {
  nodeStats?: Array<Record<string, unknown>> | null
  graphNodes?: Array<{ id?: unknown }> | null
  events?: Array<Record<string, unknown>> | null
}): string[] {
  const out: string[] = []
  const push = (id: unknown) => {
    const s = typeof id === 'string' ? id.trim() : ''
    if (s && !out.includes(s) && !looksLikeOpaqueId(s)) out.push(s)
  }
  const stats = Array.isArray(input.nodeStats) ? input.nodeStats : []
  const indexed = stats
    .map((n, i) => ({ id: n.node_id, idx: toInt(n.node_index) ?? 10_000 + i }))
    .sort((a, b) => a.idx - b.idx)
  for (const n of indexed) push(n.id)
  for (const n of Array.isArray(input.graphNodes) ? input.graphNodes : []) push(n?.id)
  for (const ev of Array.isArray(input.events) ? input.events : []) {
    if (ev && String(ev.type ?? '') === 'node_start') push(ev.node_id)
  }
  return out
}

/**
 * Group order for the "All" outputs view: execution order first (including
 * nodes with no files, so they can be shown as "no file outputs"), then any
 * remaining file groups in natural order, `run` (run-level) last.
 */
export function orderOutputGroups(executionOrder: string[], groupKeys: Iterable<string>): string[] {
  const keys = [...groupKeys].filter((k) => k === 'run' || !looksLikeOpaqueId(k))
  const order: string[] = []
  for (const id of executionOrder) if (id !== 'run' && !order.includes(id)) order.push(id)
  const rest = keys.filter((k) => k !== 'run' && !order.includes(k)).sort(naturalCompare)
  order.push(...rest)
  if (keys.includes('run')) order.push('run')
  return order
}

const MODEL_ARTIFACT_RE = /\b(model|weights|saved_model|keras|tflite|onnx|classifier|estimator)\b/i

function isModelFile(pathOrName: string, kind?: string): boolean {
  if (String(kind || '').toLowerCase() === 'model') return true
  return detectFileKind(pathOrName) === 'model'
}

function isModelArtifactType(artifactType: string): boolean {
  return MODEL_ARTIFACT_RE.test(String(artifactType || '').replace(/[_-]/g, ' '))
}

/**
 * Should Runs show "Promote"? Only when this run actually produced a
 * model artifact/file (or already registered one). A graph is a workflow —
 * trainers, metrics, or "checkpoint" path noise alone do not imply a model.
 */
const PACKAGE_NODE_RE = /(deployment_packager|packager|edge_deploy|ship_package)/i
const PACKAGE_ARTIFACT_RE = /(deployment[ _-]?package|edge[ _-]?package|ship[ _-]?package)/i
/** Untrained Model Builder output (`compiled_<hash>.keras`). */
const COMPILED_UNTRAINED_RE = /(^|\/)compiled_[0-9a-f]{6,}\.(keras|h5)$/i

/**
 * Ship / deploy package runs: their output is a deployment package (the
 * optimized model inside it is a by-product), so they never offer
 * "Register model". Detected from the graph's node types, package artifacts,
 * or the edge-deploy graph name.
 */
export function isPackageRun(input: {
  graphNodeTypes?: Array<string | null | undefined> | null
  artifacts?: Array<{ artifact_type?: string; node_type?: string }> | null
  graphName?: string | null
}): boolean {
  if ((input.graphNodeTypes ?? []).some((t) => PACKAGE_NODE_RE.test(String(t || '')))) return true
  for (const a of input.artifacts ?? []) {
    if (PACKAGE_ARTIFACT_RE.test(String(a.artifact_type || ''))) return true
    if (PACKAGE_NODE_RE.test(String(a.node_type || ''))) return true
  }
  return /^edge[-_ ]deploy/i.test(String(input.graphName || '').trim())
}

export function runHasModelOutput(input: {
  files?: Array<{ name?: string; path?: string; kind?: string }>
  artifacts?: Array<{ artifact_type?: string; node_type?: string; node_id?: string; data_path?: string; path?: string }>
  metrics?: Record<string, unknown> | null
  nodeStats?: Array<Record<string, unknown>> | null
  registeredModels?: number
  /** Node types of the run's graph (package-run detection). */
  graphNodeTypes?: Array<string | null | undefined> | null
  graphName?: string | null
  /**
   * Kinds from `GET /runs/{id}/models` (`trained` / `compiled_untrained` /
   * `optimized`); null/undefined when the route is unavailable. When known,
   * only a non-untrained model counts.
   */
  modelKinds?: string[] | null
}): boolean {
  if ((input.registeredModels ?? 0) > 0) return true
  if (isPackageRun({ graphNodeTypes: input.graphNodeTypes, artifacts: input.artifacts, graphName: input.graphName }))
    return false
  if (input.modelKinds && input.modelKinds.length > 0) {
    return input.modelKinds.some((k) => String(k || '').toLowerCase() !== 'compiled_untrained')
  }
  for (const f of input.files ?? []) {
    const p = f.path || f.name || ''
    if (COMPILED_UNTRAINED_RE.test(p)) continue
    if (isModelFile(p, f.kind)) return true
  }
  for (const a of input.artifacts ?? []) {
    const p = String(a.data_path || a.path || '')
    if (COMPILED_UNTRAINED_RE.test(p) || String(a.node_type || '') === 'model_builder') continue
    if (isModelArtifactType(String(a.artifact_type || ''))) return true
    if (isModelFile(p)) return true
  }
  return false
}

/**
 * Extract the workspace artifact **pack** slug from a path like
 * ``artifacts/optimized/runs/<run_id>/model.tflite`` or
 * ``workspace/artifacts/speech-commands/latest``.
 * Skips content-addressed blob dirs (``artifacts/<hex>/data``).
 */
export function artifactSlugFromPath(path: string): string | undefined {
  const p = String(path || '')
    .replace(/\\/g, '/')
    .replace(/^workspace\//, '')
  const m = p.match(/^artifacts\/([^/]+)\/(?:runs|latest|staging|prod)(?:\/|$)/i)
  if (!m?.[1]) return undefined
  const slug = m[1]
  if (looksLikeOpaqueId(slug) || /^[0-9a-f]{24,}$/i.test(slug)) return undefined
  return slug
}

/** One model-producing branch/output inside a run (dual Model Builder / Trainer). */
export type RunModelCandidate = {
  /** Stable key: node id, or `file:<path>` when ungrouped. */
  id: string
  label: string
  nodeId?: string
  /** Best path hint for the model file / artifact. */
  pathHint?: string
  /** Workspace pack slug for POST /models (e.g. speech-commands, optimized). */
  artifactSlug?: string
  artifactType?: string
}

/**
 * Discover model outputs in a run, grouped by producing node when known.
 * Dual-branch graphs yield one candidate per Model Builder / Trainer instance.
 */
export function listRunModelCandidates(input: {
  files?: Array<{ name?: string; path?: string; kind?: string; node_id?: string }>
  artifacts?: Array<{ artifact_type?: string; node_type?: string; node_id?: string; data_path?: string; path?: string }>
  /** Optional label lookup (pipeline stack). */
  labelFor?: (nodeId: string) => string | undefined
}): RunModelCandidate[] {
  const byNode = new Map<string, RunModelCandidate>()
  const loose: RunModelCandidate[] = []

  const touch = (nodeId: string | undefined, pathHint?: string, artifactType?: string) => {
    const nid = String(nodeId || '').trim()
    const slug = pathHint ? artifactSlugFromPath(pathHint) : undefined
    if (nid && !looksLikeOpaqueId(nid) && nid !== 'run') {
      const prev = byNode.get(nid)
      if (prev) {
        // Prefer pack-layout paths (have a slug) over content-addressed blobs.
        if (pathHint && (!prev.pathHint || (!prev.artifactSlug && slug))) {
          prev.pathHint = pathHint
        }
        if (slug && !prev.artifactSlug) prev.artifactSlug = slug
        if (!prev.artifactType && artifactType) prev.artifactType = artifactType
        return
      }
      byNode.set(nid, {
        id: nid,
        nodeId: nid,
        label: input.labelFor?.(nid) || displayLabelFromId(nid),
        pathHint,
        artifactSlug: slug,
        artifactType,
      })
      return
    }
    if (pathHint) {
      const id = `file:${pathHint}`
      if (!loose.some((c) => c.id === id)) {
        loose.push({
          id,
          label: pathHint.split('/').pop() || pathHint,
          pathHint,
          artifactSlug: slug,
          artifactType,
        })
      }
    }
  }

  for (const f of input.files ?? []) {
    const path = String(f.path || f.name || '')
    if (!isModelFile(path, f.kind)) continue
    touch(f.node_id, path)
  }
  for (const a of input.artifacts ?? []) {
    const path = String(a.data_path || a.path || '')
    const at = String(a.artifact_type || '')
    if (!isModelArtifactType(at) && !isModelFile(path)) continue
    touch(a.node_id || a.node_type, path || undefined, at || undefined)
  }

  return [...byNode.values(), ...loose]
}

function displayLabelFromId(id: string): string {
  // Local import avoided — keep this file free of format.ts cycles; callers
  // usually pass labelFor from the pipeline stack.
  const raw = String(id || '').trim()
  const m = raw.match(/^(.*)_([0-9a-f]{6,}|[0-9]+)$/i)
  if (m) {
    const base = m[1].replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    return `${base} #${m[2].slice(0, 8)}`
  }
  return raw.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) || raw
}
