/**
 * Results-first helpers for Runs (pure — unit-tested in the node vitest env).
 *
 * A run's "result" is its headline metric per path (fork graphs train
 * several models side by side), the dataset it trained on, and how it
 * compares with the best earlier run of the same pipeline.
 *
 * Sources, in priority order:
 *  1. backend `summary` / `regression` / `display_name` (UX API contract) on
 *     the run row / detail (`meta.*` or top level)
 *  2. fallback: evaluator `metrics.json` files fetched from Run outputs,
 *     graph config (architecture / epochs) for path descriptions, journal
 *     `node_end` counts for the dataset, and the loaded run list for the
 *     regression check.
 */
import { metricPhraseOf, pickPrimaryMetric, type PrimaryMetric } from '../../lib/metrics'
import { runDisplayName } from '../../lib/runDisplay'
import { normalizeRunModels as parseRunModelRows } from '../edge/runModels'
import { artifactSlugFromPath } from './runOutputs'
import type { PipelineShape } from './runNodes'

type Rec = Record<string, unknown>

function rec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function num(v: unknown): number | null {
  const n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** Scalar (finite number) metrics only — drops per_class / confusion_matrix. */
export function scalarMetrics(metrics: unknown): Record<string, number> {
  const o = rec(metrics)
  const out: Record<string, number> = {}
  if (!o) return out
  for (const [k, v] of Object.entries(o)) {
    const n = num(v)
    if (n != null && typeof v !== 'boolean') out[k] = n
  }
  return out
}

// ── Display name ────────────────────────────────────────────────────────

/** Run title — shared lib/runDisplay (display_name → humanized graph name → "Run <id>"). */
export function runTitle(run: unknown): string {
  return runDisplayName(run)
}

// ── Paths ───────────────────────────────────────────────────────────────

export type PathResult = {
  /** Backend `path_id` ("path-a") or lane letter fallback. */
  pathId: string
  /** "A", "B", … */
  letter: string
  /** Plain description, e.g. "DS-CNN · 50 epochs" ('' when unknown). */
  description: string
  nodeIds: string[]
  metrics: Record<string, number>
  primary: PrimaryMetric | null
  /** Node that produced the metrics (evaluator) when known. */
  metricsNodeId?: string
}

/** "Path A (DS-CNN · 30 epochs)" / "Path A". */
export function pathDisplayName(p: Pick<PathResult, 'letter' | 'description'>): string {
  const head = `Path ${p.letter}`
  const d = p.description.trim()
  if (!d || d.toLowerCase() === head.toLowerCase()) return head
  return `${head} (${d})`
}

function letterFrom(pathId: string, index: number): string {
  const m = pathId.match(/(?:^|[-_ ])([a-z])$/i)
  if (m) return m[1].toUpperCase()
  return String.fromCharCode(65 + Math.min(index, 25))
}

const ARCH_NAMES: Record<string, string> = {
  ds_cnn: 'DS-CNN',
  dscnn: 'DS-CNN',
  mobilenet: 'MobileNet',
  mobilenet_v2: 'MobileNet v2',
  simple_cnn: 'Simple CNN',
  cnn: 'CNN',
  custom: 'Custom layers',
}

export function prettyArchitecture(arch: string): string {
  const k = arch.trim().toLowerCase()
  if (!k) return ''
  return ARCH_NAMES[k] || k.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

type GraphNodeLike = { id?: unknown; node_type?: unknown; label?: unknown; config?: unknown }

/** "DS-CNN · 50 epochs" from the model builder / trainer config on a branch. */
export function describeBranch(nodeIds: string[], graphNodes: GraphNodeLike[] | null | undefined): string {
  const byId = new Map((graphNodes || []).map((n) => [str(n?.id), n]))
  let arch = ''
  let epochs: number | null = null
  for (const id of nodeIds) {
    const n = byId.get(id)
    if (!n) continue
    const cfg = rec(n.config) || {}
    const t = str(n.node_type)
    if (!arch && (t === 'model_builder' || str(cfg.architecture))) arch = prettyArchitecture(str(cfg.architecture))
    if (epochs == null && (t === 'trainer' || num(cfg.epochs) != null)) epochs = num(cfg.epochs)
  }
  const bits: string[] = []
  if (arch) bits.push(arch)
  if (epochs != null) bits.push(`${epochs} epoch${epochs === 1 ? '' : 's'}`)
  return bits.join(' · ')
}

/** Paths from backend `summary.paths` (row, top level or meta). Empty when absent. */
export function pathsFromSummary(run: unknown): PathResult[] {
  const r = rec(run)
  const summary = rec(r?.summary) ?? rec(rec(r?.meta)?.summary)
  const raw = Array.isArray(summary?.paths) ? (summary!.paths as unknown[]) : []
  const out: PathResult[] = []
  raw.forEach((p, i) => {
    const o = rec(p)
    if (!o) return
    const pathId = str(o.path_id) || str(o.id) || `path-${String.fromCharCode(97 + i)}`
    const letter = str(o.letter).toUpperCase() || letterFrom(pathId, i)
    const metrics = scalarMetrics(o.metrics)
    const pm = rec(o.primary_metric)
    const primary =
      pm && num(pm.value) != null && str(pm.name)
        ? { name: str(pm.name), value: num(pm.value)! }
        : pickPrimaryMetric(metrics)
    let description = str(o.description) || str(o.label)
    // A bare "Path A" label carries no description.
    if (/^path\s+[a-z]$/i.test(description)) description = ''
    out.push({
      pathId,
      letter,
      description,
      nodeIds: Array.isArray(o.node_ids) ? (o.node_ids as unknown[]).map(str).filter(Boolean) : [],
      metrics,
      primary,
      metricsNodeId: str(o.evaluator_node_id) || str(o.metrics_node_id) || undefined,
    })
  })
  return out
}

/** Backend `summary.best_path_id` when present. */
export function bestPathIdFromSummary(run: unknown): string | null {
  const r = rec(run)
  const summary = rec(r?.summary) ?? rec(rec(r?.meta)?.summary)
  return str(summary?.best_path_id) || null
}

/**
 * Fallback paths from the pipeline shape + evaluator metrics files.
 * Linear runs → one "Path A" (whole graph); fork/parallel → one per branch.
 */
export function fallbackPathResults(input: {
  shape: PipelineShape
  graphNodes?: GraphNodeLike[] | null
  /** node id → parsed metrics.json (any shape). */
  metricsByNode: Record<string, unknown>
}): PathResult[] {
  const { shape } = input
  const branches =
    shape.kind === 'linear' ? [shape.sharedIds] : shape.branches.map((b) => [...b])
  const shared = shape.kind === 'fork' ? shape.sharedIds : []
  const results: PathResult[] = []
  branches.forEach((ids, i) => {
    let metricsNodeId: string | undefined
    let metrics: Record<string, number> = {}
    // Last metrics-producing node on the branch wins (evaluator after trainer).
    for (const id of ids) {
      const m = scalarMetrics(input.metricsByNode[id])
      if (Object.keys(m).length) {
        metrics = m
        metricsNodeId = id
      }
    }
    const letter = String.fromCharCode(65 + Math.min(i, 25))
    results.push({
      pathId: `path-${letter.toLowerCase()}`,
      letter,
      description: describeBranch([...shared, ...ids], input.graphNodes),
      nodeIds: ids,
      metrics,
      primary: pickPrimaryMetric(metrics),
      metricsNodeId,
    })
  })
  return results
}

/** Higher is better unless the metric name says otherwise (loss / error). */
export function higherIsBetter(name: string): boolean {
  return !/(loss|error|mae|mse|rmse|latency|duration)/i.test(name)
}

/** Best path by primary metric (backend best_path_id wins when it matches). */
export function pickBestPath(paths: PathResult[], backendBest?: string | null): PathResult | null {
  if (backendBest) {
    const hit = paths.find((p) => p.pathId === backendBest)
    if (hit) return hit
  }
  let best: PathResult | null = null
  for (const p of paths) {
    if (!p.primary) continue
    if (!best || !best.primary) {
      best = p
      continue
    }
    const up = higherIsBetter(p.primary.name)
    if (up ? p.primary.value > best.primary.value : p.primary.value < best.primary.value) best = p
  }
  return best
}

/** node id → path, from backend node_ids or the lane map (A/B…). */
export function pathOfNodeMap(paths: PathResult[], laneOf?: Map<string, string> | null): Map<string, PathResult> {
  const m = new Map<string, PathResult>()
  for (const p of paths) for (const id of p.nodeIds) if (!m.has(id)) m.set(id, p)
  if (laneOf) {
    for (const [id, lane] of laneOf) {
      if (m.has(id) || !lane || lane === 'shared') continue
      const p = paths.find((x) => x.letter === lane)
      if (p) m.set(id, p)
    }
  }
  return m
}

/**
 * Shape lane ("A", "B"… or "shared" for linear) → path result. Matches by
 * node ids first (backend paths may be ordered differently), then by letter.
 */
export function lanePathMap(shape: PipelineShape, paths: PathResult[]): Map<string, PathResult> {
  const m = new Map<string, PathResult>()
  if (shape.kind === 'linear') {
    if (paths.length === 1) m.set('shared', paths[0])
    return m
  }
  shape.branches.forEach((branch, i) => {
    const lane = String.fromCharCode(65 + Math.min(i, 25))
    const hit =
      paths.find((p) => p.nodeIds.length > 0 && branch.some((id) => p.nodeIds.includes(id))) ||
      paths.find((p) => p.letter === lane)
    if (hit) m.set(lane, hit)
  })
  return m
}

// ── Dataset ─────────────────────────────────────────────────────────────

export type DatasetInfo = { count: number | null; source: string | null; fallbackUsed: boolean }

/** "workspace/datasets/input/speech-commands" → "speech-commands". */
export function datasetShortName(source: string): string {
  const parts = source.replace(/\\/g, '/').split('/').filter(Boolean)
  return parts[parts.length - 1] || source
}

/**
 * Dataset used: backend `summary.dataset`, else the ingest node's `node_end`
 * (`dataset` block or `output_count`) + its configured path.
 */
export function datasetFromRun(input: {
  run?: unknown
  events?: Array<Record<string, unknown>> | null
  graphNodes?: GraphNodeLike[] | null
}): DatasetInfo | null {
  const r = rec(input.run)
  const summary = rec(r?.summary) ?? rec(rec(r?.meta)?.summary)
  const ds = rec(summary?.dataset)
  if (ds) {
    const count = num(ds.clip_count) ?? num(ds.count) ?? num(ds.num_samples)
    const source = str(ds.source_path) || str(ds.source) || str(ds.label) || null
    if (count != null || source) return { count, source, fallbackUsed: ds.fallback_used === true }
  }
  const ingest = (input.graphNodes || []).find((n) => /ingest/i.test(str(n?.node_type)))
  const ingestId = ingest ? str(ingest.id) : ''
  let count: number | null = null
  let source: string | null = null
  let fallbackUsed = false
  for (const ev of input.events || []) {
    const t = str(ev.type) || str(ev.event)
    if (t !== 'node_end' && t !== 'node_complete') continue
    const nid = str(ev.node_id)
    const isIngest = ingestId ? nid === ingestId : /ingest/i.test(str(ev.node_type))
    if (!isIngest) continue
    const d = rec(ev.dataset)
    if (d) {
      count = num(d.clip_count) ?? num(d.count) ?? count
      source = str(d.source_path) || source
      fallbackUsed = d.fallback_used === true
    }
    if (count == null) count = num(ev.output_count)
    break
  }
  if (!source && ingest) {
    const cfg = rec(ingest.config) || {}
    source = str(cfg.path) || str(cfg.dataset_path) || str(cfg.input_dir) || str(cfg.repo_id) || null
  }
  if (count == null && !source) return null
  return { count, source, fallbackUsed }
}

/**
 * Domain-neutral dataset line. Verb/unit follow graph phase when known
 * (train → "Trained on … clips"; preprocess → "Processed …"; else "Used … items").
 */
export function datasetSentence(
  ds: DatasetInfo,
  phaseOrVerb?: string | null,
): string {
  // Graph names are snake_case ("…_e2e_train_ml") — `\b` does not split on "_".
  const phaseHint = String(phaseOrVerb || '').toLowerCase().replace(/[_\-.]+/g, ' ')
  let verb = 'Used'
  if (/\btrain(ing)?\b/.test(phaseHint)) verb = 'Trained on'
  else if (/\b(preprocess(ing)?|prep)\b/.test(phaseHint)) verb = 'Processed'
  else if (/\binfer(ence)?\b/.test(phaseHint)) verb = 'Ran on'
  else if (/\beval(uat\w*)?\b/.test(phaseHint)) verb = 'Evaluated on'
  else if (phaseOrVerb && !/\s/.test(phaseOrVerb) && /^(Used|Trained on|Processed|Ran on|Evaluated on)$/.test(phaseOrVerb)) {
    verb = phaseOrVerb
  }
  const audioish =
    verb === 'Trained on' ||
    verb === 'Processed' ||
    /clip|audio|wav|speech|sound/i.test(ds.source || '')
  const unit = audioish ? 'clip' : 'item'
  const what =
    ds.count != null
      ? `${ds.count.toLocaleString()} ${unit}${ds.count === 1 ? '' : 's'}`
      : 'data'
  const from = ds.source ? ` from ${datasetShortName(ds.source)}` : ''
  return `${verb} ${what}${from}`
}

// ── Regression ──────────────────────────────────────────────────────────

export type RegressionView = {
  delta: number
  previousValue: number | null
  previousRunId: string | null
  metricName: string
}

/**
 * Backend `regression` (delta = current − best previous), else compute it
 * from earlier runs of the same pipeline in the loaded list.
 */
export function regressionFromHistory(input: {
  runId: string
  graphName: string
  createdAt?: string | null
  current: PrimaryMetric | null
  rows: Array<Record<string, unknown>>
  /** Primary metric for a row (lib/metrics primaryMetric). */
  metricOf: (row: Record<string, unknown>) => PrimaryMetric | null
}): RegressionView | null {
  const cur = input.current
  if (!cur || !input.graphName) return null
  const t0 = input.createdAt ? Date.parse(input.createdAt) : NaN
  const up = higherIsBetter(cur.name)
  let best: { value: number; runId: string } | null = null
  for (const row of input.rows) {
    const id = str(row.run_id)
    if (!id || id === input.runId) continue
    if (str(row.graph_name) !== input.graphName) continue
    const t = Date.parse(str(row.created_at))
    if (Number.isFinite(t0) && Number.isFinite(t) && t > t0) continue
    const pm = input.metricOf(row)
    if (!pm || pm.name !== cur.name) continue
    if (!best || (up ? pm.value > best.value : pm.value < best.value)) best = { value: pm.value, runId: id }
  }
  if (!best) return null
  return { delta: cur.value - best.value, previousValue: best.value, previousRunId: best.runId, metricName: cur.name }
}

/** True when the delta moves the wrong way by more than noise. */
export function isRegression(r: Pick<RegressionView, 'delta' | 'metricName'>, epsilon = 0.005): boolean {
  return higherIsBetter(r.metricName) ? r.delta < -epsilon : r.delta > epsilon
}

// ── Headline ────────────────────────────────────────────────────────────

/** "Test accuracy 0.561". */
export function metricPhrase(pm: PrimaryMetric | null): string | null {
  if (!pm) return null
  return metricPhraseOf(pm)
}

/**
 * List-row metric text: best path value (+ "· 2 paths") for multi-path runs,
 * else the run's primary metric.
 */
export function listRowMetric(input: {
  primary: PrimaryMetric | null
  paths: PathResult[]
  bestPathId?: string | null
}): string | null {
  const scored = input.paths.filter((p) => p.primary)
  if (scored.length >= 2) {
    const best = pickBestPath(scored, input.bestPathId)
    const phrase = metricPhrase(best?.primary ?? input.primary)
    return phrase ? `${phrase} · ${input.paths.length} paths` : null
  }
  return metricPhrase(input.primary ?? scored[0]?.primary ?? null)
}

// ── Evaluator detail ────────────────────────────────────────────────────

export type PerClassRow = { label: string; precision: number | null; recall: number | null; f1: number | null }

/** metrics.json `per_class` → table rows (sorted by label). */
export function perClassRows(metrics: unknown): PerClassRow[] {
  const pc = rec(rec(metrics)?.per_class)
  if (!pc) return []
  return Object.entries(pc)
    .map(([label, v]) => {
      const o = rec(v) || {}
      return { label, precision: num(o.precision), recall: num(o.recall), f1: num(o.f1 ?? o.f1_score) }
    })
    .sort((a, b) => a.label.localeCompare(b.label))
}

/** metrics.json `confusion_matrix` as a numeric grid, or null. */
export function confusionMatrix(metrics: unknown): number[][] | null {
  const cm = rec(metrics)?.confusion_matrix
  if (!Array.isArray(cm) || cm.length === 0) return null
  const rows = cm.map((r) => (Array.isArray(r) ? r.map((x) => num(x) ?? 0) : null))
  if (rows.some((r) => !r)) return null
  return rows as number[][]
}

/** Files named like evaluator metrics output. */
export function isMetricsFile(name: string): boolean {
  return /(^|[_-])metrics\.json$/i.test(name.trim())
}

// ── Models ──────────────────────────────────────────────────────────────

export type ModelKind = 'trained' | 'optimized' | 'compiled_untrained' | 'unknown'

export type ModelOption = {
  /** Stable key (path). */
  id: string
  path: string
  nodeId?: string
  nodeType?: string
  pathId?: string
  pathLabel?: string
  kind: ModelKind
  format?: string
  sizeBytes?: number | null
  metrics: Record<string, number>
  labels: string[]
  suggestedName?: string
  /** Workspace pack slug (artifacts/<slug>/runs/…) for POST /models. */
  slug?: string
}

function normKind(raw: unknown, path: string, nodeType: string): ModelKind {
  const k = str(raw).toLowerCase()
  if (k === 'trained' || k === 'optimized' || k === 'compiled_untrained') return k
  if (k.includes('untrained') || k === 'compiled') return 'compiled_untrained'
  if (k) return 'unknown'
  return guessModelKind(path, nodeType)
}

/** Kind from path / producing node when the API does not say. */
export function guessModelKind(path: string, nodeType?: string | null): ModelKind {
  const p = path.toLowerCase()
  const t = String(nodeType || '').toLowerCase()
  if (t === 'model_builder' || /(^|\/)compiled_[0-9a-f]{6,}\.(keras|h5)$/.test(p)) return 'compiled_untrained'
  if (t.includes('optimi') || t.includes('quantiz') || /\.(tflite|onnx)$/.test(p)) return 'optimized'
  if (t === 'trainer' || /(^|\/)(model|best)\.(keras|h5|pt|pth)$/.test(p) || p.includes('saved_model')) return 'trained'
  return 'unknown'
}

export function isUntrained(o: Pick<ModelOption, 'kind'>): boolean {
  return o.kind === 'compiled_untrained'
}

function formatOf(path: string): string | undefined {
  const m = path.toLowerCase().match(/\.(keras|h5|tflite|onnx|pt|pth|pb)$/)
  if (m) return m[1] === 'pb' ? 'saved_model' : m[1]
  if (/saved_model\/?$/i.test(path)) return 'saved_model'
  return undefined
}

/** GET /runs/{id}/models → options (parsing shared with Ship: edge/runModels). */
export function normalizeRunModels(raw: unknown): ModelOption[] {
  return parseRunModelRows(raw).map((m) => ({
    id: m.path,
    path: m.path,
    nodeId: m.node_id,
    nodeType: m.node_type,
    pathId: m.path_id,
    pathLabel: m.path_label,
    kind: normKind(m.kind, m.path, m.node_type || ''),
    format: m.format ?? formatOf(m.path),
    sizeBytes: m.size_bytes ?? null,
    metrics: scalarMetrics(m.metrics),
    labels: m.labels ?? [],
    suggestedName: m.suggested_name,
    slug: artifactSlugFromPath(m.path),
  }))
}

/**
 * Order for the Register list: never an untrained model first. Best path's
 * trained model, then its optimized one, then other paths, untrained last.
 */
export function rankModelOptions(options: ModelOption[], bestPathId?: string | null): ModelOption[] {
  const kindRank: Record<ModelKind, number> = { trained: 0, optimized: 1, unknown: 2, compiled_untrained: 9 }
  return [...options].sort((a, b) => {
    const ua = isUntrained(a) ? 1 : 0
    const ub = isUntrained(b) ? 1 : 0
    if (ua !== ub) return ua - ub
    const ba = bestPathId && a.pathId === bestPathId ? 0 : 1
    const bb = bestPathId && b.pathId === bestPathId ? 0 : 1
    if (ba !== bb) return ba - bb
    return kindRank[a.kind] - kindRank[b.kind] || a.path.localeCompare(b.path)
  })
}

/** Default selection: first ranked option that is not untrained (null if none). */
export function defaultModelOption(options: ModelOption[], bestPathId?: string | null): ModelOption | null {
  return rankModelOptions(options, bestPathId).find((o) => !isUntrained(o)) ?? null
}

/** "speech-commands-dscnn" style slug: lowercase, [a-z0-9-], ≤ 48 chars. */
export function slugifyModelName(...parts: Array<string | null | undefined>): string {
  const s = parts
    .filter(Boolean)
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
    .replace(/-+$/g, '')
  return s || 'model'
}

/** Backend suggestion, else `<graph> · <path description>` as a slug. */
export function suggestModelName(opt: Pick<ModelOption, 'suggestedName' | 'pathLabel'> | null, graphName: string, pathLabel?: string): string {
  if (opt?.suggestedName) return opt.suggestedName
  return slugifyModelName(graphName.replace(/_/g, '-'), pathLabel ?? opt?.pathLabel ?? '')
}

/** Plain-language kind label. */
export function modelKindLabel(kind: ModelKind): string {
  switch (kind) {
    case 'trained':
      return 'Trained model'
    case 'optimized':
      return 'Optimized for devices'
    case 'compiled_untrained':
      return 'Untrained (architecture only)'
    default:
      return 'Model file'
  }
}
