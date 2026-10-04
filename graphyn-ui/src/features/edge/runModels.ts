/**
 * Ship → Configure model picker helpers (pure).
 *
 * Source of truth: `GET /runs/{id}/models` → `{ run_id, models: ModelRow[] }`
 * (UX API draft §4). Older APIs lack that route, so `runModelsFromOutputs`
 * scans `GET /runs/{id}/outputs` entries for model-like files
 * (`.keras` / `.h5` / `.tflite` / `.onnx` / `saved_model` dirs).
 */
import { formatBytes } from '../../lib/format'
import { formatMetric, isRatioMetric, metricLabel, pickPrimaryMetric } from '../../lib/metrics'

export type RunModelKind = 'trained' | 'compiled_untrained' | 'optimized' | string

export type RunModel = {
  path: string
  node_id?: string
  node_type?: string
  path_id?: string
  path_label?: string
  kind?: RunModelKind
  format?: string
  size_bytes?: number
  created_at?: string
  metrics?: Record<string, unknown>
  labels?: string[]
  suggested_name?: string
  /** True when inferred from run outputs (no backend metadata). */
  inferred?: boolean
}

function rec(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

function optStr(v: unknown): string | undefined {
  return typeof v === 'string' && v.trim() ? v.trim() : undefined
}

export function inferModelFormat(path: string): string | undefined {
  const p = path.toLowerCase().replace(/\/+$/, '')
  if (p.endsWith('.keras')) return 'keras'
  if (p.endsWith('.h5')) return 'h5'
  if (p.endsWith('.tflite')) return 'tflite'
  if (p.endsWith('.onnx')) return 'onnx'
  if (p.endsWith('.pt') || p.endsWith('.pth')) return 'pt'
  if (/(^|\/)saved_model$/.test(p)) return 'saved_model'
  return undefined
}

/** Parse `{ run_id, models: [...] }` / bare array / envelope into RunModel rows. */
export function normalizeRunModels(raw: unknown): RunModel[] {
  const o = rec(raw)
  const list: unknown[] = Array.isArray(raw)
    ? raw
    : Array.isArray(o?.models)
      ? (o!.models as unknown[])
      : Array.isArray(o?.items)
        ? (o!.items as unknown[])
        : []
  const out: RunModel[] = []
  for (const item of list) {
    const r = rec(item)
    const path = optStr(r?.path) ?? optStr(r?.artifact_path)
    if (!r || !path) continue
    out.push({
      path,
      node_id: optStr(r.node_id),
      node_type: optStr(r.node_type),
      path_id: optStr(r.path_id),
      path_label: optStr(r.path_label),
      kind: optStr(r.kind),
      format: optStr(r.format) ?? inferModelFormat(path),
      size_bytes: typeof r.size_bytes === 'number' ? r.size_bytes : typeof r.size === 'number' ? r.size : undefined,
      created_at: optStr(r.created_at),
      metrics: rec(r.metrics) ?? undefined,
      labels: Array.isArray(r.labels) ? r.labels.map(String) : undefined,
      suggested_name: optStr(r.suggested_name),
    })
  }
  return out
}

/** Fallback: model-like files from `GET /runs/{id}/outputs` (bare list or `{items}`). */
export function runModelsFromOutputs(raw: unknown): RunModel[] {
  const o = rec(raw)
  const list: unknown[] = Array.isArray(raw) ? raw : Array.isArray(o?.items) ? (o!.items as unknown[]) : []
  const out: RunModel[] = []
  const seen = new Set<string>()
  for (const item of list) {
    const r = rec(item)
    let path = optStr(r?.path)
    if (!r || !path) continue
    // saved_model.pb inside a SavedModel dir → the dir is the model.
    if (/\/saved_model\.pb$/i.test(path)) path = path.replace(/\/saved_model\.pb$/i, '')
    // Files nested inside a SavedModel dir (variables/…) are not separate models.
    if (/\/saved_model\/.+/i.test(path)) continue
    const format = inferModelFormat(path)
    if (!format || seen.has(path)) continue
    seen.add(path)
    const nodeId = optStr(r.node_id)
    out.push({
      path,
      node_id: nodeId,
      format,
      kind: format === 'tflite' || /optimi[sz]er/i.test(nodeId ?? '') ? 'optimized' : 'trained',
      size_bytes: typeof r.size === 'number' && r.size > 0 ? r.size : undefined,
      inferred: true,
    })
  }
  return out
}

/** Formats the edge optimizer can take as input (it converts *to* tflite/onnx). */
export function isShippableSource(m: RunModel): boolean {
  if (m.kind === 'compiled_untrained') return false
  const f = (m.format ?? '').toLowerCase()
  return f === 'keras' || f === 'saved_model' || f === 'h5' || f === ''
}

/**
 * Default selection: the explicitly preferred path (from Models → Use in Ship),
 * else the trained model on the run's best path, else any trained shippable
 * model, else the first shippable one. Never invents a path.
 */
export function pickDefaultRunModel(
  models: RunModel[],
  opts: { preferredPath?: string | null; bestPathId?: string | null } = {},
): RunModel | null {
  if (models.length === 0) return null
  const norm = (p: string) => p.replace(/^\/+|\/+$/g, '').replace(/^artifacts\//, 'workspace/artifacts/')
  const pref = opts.preferredPath ? norm(opts.preferredPath) : ''
  if (pref) {
    const hit = models.find((m) => norm(m.path) === pref)
    if (hit) return hit
  }
  const shippable = models.filter(isShippableSource)
  const trained = shippable.filter((m) => !m.kind || m.kind === 'trained')
  if (opts.bestPathId) {
    const best = trained.find((m) => m.path_id === opts.bestPathId)
    if (best) return best
  }
  return trained[0] ?? shippable[0] ?? null
}

const KIND_LABEL: Record<string, string> = {
  trained: 'Trained',
  compiled_untrained: 'Untrained (architecture only)',
  optimized: 'Optimized',
}

export function runModelKindLabel(kind?: string): string {
  if (!kind) return 'Model'
  return KIND_LABEL[kind] ?? kind.replace(/_/g, ' ')
}

/**
 * Metrics that belong to this artifact. The API copies a path's evaluation
 * metrics onto every model row of that path, but they describe the *trained*
 * model only — an untrained (compiled-only) or converted artifact never shows
 * the path's accuracy.
 */
export function runModelOwnMetrics(m: Pick<RunModel, 'kind' | 'metrics'>): Record<string, unknown> | undefined {
  if (m.kind && m.kind !== 'trained') return undefined
  return m.metrics
}

/** One-line picker label: "Trained · keras · 1.2 MB · Test accuracy 0.561". */
export function runModelSummary(m: RunModel): string {
  const parts = [runModelKindLabel(m.kind)]
  if (m.format) parts.push(m.format)
  if (typeof m.size_bytes === 'number' && m.size_bytes > 0) parts.push(formatBytes(m.size_bytes))
  const pm = pickPrimaryMetric(runModelOwnMetrics(m))
  if (pm) parts.push(`${metricLabel(pm.name)} ${formatMetric(pm.value, { percent: isRatioMetric(pm.name, pm.value) })}`)
  return parts.join(' · ')
}

/** Short title for a model row: path label, else node, else file name. */
export function runModelTitle(m: RunModel): string {
  const file = m.path.replace(/\/+$/, '').split('/').pop() || m.path
  if (m.path_label) return `${m.path_label} — ${file}`
  return file
}

export function parseLabelsCsv(csv: string): string[] {
  return csv
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export type LabelCheck =
  | { status: 'ok' }
  | { status: 'unknown' }
  | { status: 'order'; expected: string[] }
  | { status: 'set'; expected: string[]; missing: string[]; extra: string[] }

/**
 * Compare user-entered labels with the model's class order (labels.txt).
 * `order` = same classes in a different order (would silently mislabel every
 * prediction); `set` = different classes.
 */
export function checkLabelsAgainstModel(modelLabels: string[] | undefined | null, entered: string[]): LabelCheck {
  if (!modelLabels || modelLabels.length === 0) return { status: 'unknown' }
  const same = modelLabels.length === entered.length && modelLabels.every((l, i) => l === entered[i])
  if (same) return { status: 'ok' }
  const a = new Set(modelLabels)
  const b = new Set(entered)
  const missing = modelLabels.filter((l) => !b.has(l))
  const extra = entered.filter((l) => !a.has(l))
  if (missing.length === 0 && extra.length === 0 && modelLabels.length === entered.length) {
    return { status: 'order', expected: modelLabels }
  }
  return { status: 'set', expected: modelLabels, missing, extra }
}

type LineageStage = { artifact_path?: string; version?: string | number | null; exists?: boolean }
type LineageRegistryModel = { name: string; stages?: Record<string, LineageStage | undefined> }

/** `lineage.model` for a Ship package run: the registered model being shipped. */
export type ShipLineageModel = { name: string; version?: string; stage: string }

const STAGE_PREFERENCE = ['prod', 'production', 'staging', 'latest']

function normModelPath(p: string): string {
  return p
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\/+|\/+$/g, '')
    .replace(/^workspace\//, '')
}

/**
 * Which registered model (name + stage [+ version]) a Ship package run ships,
 * for the run payload's optional `lineage: { model }`. The explicitly chosen
 * registry model (Advanced picker, or Models → Use in Ship) wins when its
 * stage's file is the model being shipped (or the file is unknown); otherwise
 * the registry is searched for a stage whose `artifact_path` is `modelPath`
 * (prod → staging → latest). Null when the shipped file is not registered.
 */
export function shipLineageModel(input: {
  registry: LineageRegistryModel[]
  modelPath: string
  preferredName?: string | null
  preferredStage?: string | null
}): ShipLineageModel | null {
  const path = normModelPath(input.modelPath || '')
  const stageKeys = (stages: Record<string, LineageStage | undefined>, first?: string | null): string[] => {
    const keys = Object.keys(stages).filter((k) => stages[k])
    const order = [...(first ? [first] : []), ...STAGE_PREFERENCE]
    return [...order.filter((k) => keys.includes(k)), ...keys.filter((k) => !order.includes(k))]
  }
  const out = (name: string, stage: string, st: LineageStage): ShipLineageModel => {
    const v = st.version
    return v != null && String(v).trim() ? { name, stage, version: String(v) } : { name, stage }
  }
  const preferred = input.preferredName
    ? input.registry.find((m) => m.name === input.preferredName)
    : undefined
  if (preferred) {
    const stages = preferred.stages || {}
    for (const k of stageKeys(stages, input.preferredStage)) {
      const st = stages[k]!
      const ap = normModelPath(st.artifact_path || '')
      if (!path || !ap || ap === path) return out(preferred.name, k, st)
    }
  }
  if (!path) return null
  for (const m of input.registry) {
    const stages = m.stages || {}
    for (const k of stageKeys(stages)) {
      const st = stages[k]!
      if (normModelPath(st.artifact_path || '') === path) return out(m.name, k, st)
    }
  }
  return null
}
