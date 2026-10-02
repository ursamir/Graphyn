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

const MODEL_ARTIFACT_RE = /\b(model|checkpoint|weights|saved_model|keras|tflite|onnx|classifier|estimator)\b/i
const TRAIN_NODE_RE = /(train|fit|finetune|fine_tune|distill)/i
const TRAIN_METRIC_RE = /^(val_|train_|test_)?(acc|accuracy|loss|auc|roc_auc|f1|precision|recall|mae|mse|rmse|top\d+)/i

/**
 * Should Runs show "Promote model" for this run? Only when the run produced
 * something model-like: a model file, a model-typed artifact, a training
 * node, training-style metrics, or a model already registered from it.
 * A preprocess-only run (ingest → condition → segment) gets no button.
 */
export function runHasModelOutput(input: {
  files?: Array<{ name?: string; path?: string; kind?: string }>
  artifacts?: Array<{ artifact_type?: string; node_type?: string; node_id?: string; data_path?: string; path?: string }>
  metrics?: Record<string, unknown> | null
  nodeStats?: Array<Record<string, unknown>> | null
  registeredModels?: number
}): boolean {
  if ((input.registeredModels ?? 0) > 0) return true
  for (const f of input.files ?? []) {
    if (String(f.kind || '').toLowerCase() === 'model') return true
    if (detectFileKind(f.path || f.name || '') === 'model') return true
  }
  for (const a of input.artifacts ?? []) {
    if (MODEL_ARTIFACT_RE.test(String(a.artifact_type || '').replace(/[_-]/g, ' '))) return true
    if (TRAIN_NODE_RE.test(String(a.node_type || a.node_id || ''))) return true
    if (detectFileKind(String(a.data_path || a.path || '')) === 'model') return true
  }
  for (const n of input.nodeStats ?? []) {
    if (TRAIN_NODE_RE.test(String(n.node_type || n.node_id || ''))) return true
  }
  for (const k of Object.keys(input.metrics ?? {})) {
    if (TRAIN_METRIC_RE.test(k)) return true
  }
  return false
}
