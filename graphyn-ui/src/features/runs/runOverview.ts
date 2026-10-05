/**
 * Pure helpers for the Runs Overview layout (unit-tested in the node vitest env):
 *
 *  - path comparison table (one row per path; primary metric + key metrics + time)
 *  - comparable-run selection for the regression line (same pipeline, same path count)
 *  - step grouping for "What happened" (Shared / Path X, numbered within each group)
 *  - friendly names for internal artifact files (compiled_<hex>.keras → "Untrained model …")
 *  - run-list helpers (one-line failure reason)
 *  - the collapsed "Run record" summary line
 *  - compact step-picker options (Logs / Run outputs / Checkpoints)
 */
import { humanizeErrorText } from '../../lib/errorText'
import type { PrimaryMetric } from '../../lib/metrics'
import { laneLabel, type PipelineShape } from './runNodes'
import { looksLikeOpaqueId } from './runOutputs'
import { lastVerifyText, type LastVerify } from './runRecord'
import {
  higherIsBetter,
  pathDisplayName,
  pathsFromSummary,
  pickBestPath,
  type PathResult,
  type RegressionView,
} from './runResults'

type Rec = Record<string, unknown>

function rec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

/** "850 ms" / "4.2 s" / "3m 12s" ('—' when unknown). */
export function formatStepDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}

// ── Path comparison table ───────────────────────────────────────────────

/** Metric keys worth a column, in display order (after the primary metric). */
const KEY_METRIC_ORDER = [
  'roc_auc',
  'auc',
  'val_accuracy',
  'accuracy',
  'test_accuracy',
  'f1',
  'f1_score',
  'macro_f1',
  'precision',
  'recall',
  'test_loss',
  'val_loss',
  'loss',
]

/** Counters / bookkeeping that are not quality metrics. */
const NON_METRIC_RE = /(^|_)(epochs?|num_|n_|count|samples|steps|batch|seed|size|params|time|duration|seconds|ms)($|_)/i

/**
 * Columns for the path table besides the primary metric: key metrics present
 * on at least one path, preferred order first, then the rest alphabetically.
 */
export function pathTableColumns(paths: PathResult[], primaryName: string | null, max = 5): string[] {
  const present = new Set<string>()
  for (const p of paths) for (const k of Object.keys(p.metrics)) present.add(k)
  if (primaryName) present.delete(primaryName)
  const preferred = KEY_METRIC_ORDER.filter((k) => present.has(k))
  const rest = [...present]
    .filter((k) => !KEY_METRIC_ORDER.includes(k) && !NON_METRIC_RE.test(k))
    .sort((a, b) => a.localeCompare(b))
  return [...preferred, ...rest].slice(0, Math.max(0, max))
}

export type PathTiming = { trainingMs: number | null; totalMs: number | null }

export type PathTableRow = {
  pathId: string
  letter: string
  /** "Path A". */
  label: string
  /** "MobileNet · lr 0.002" ('' when unknown). */
  description: string
  /** Primary metric value for the table's primary column (null when this path lacks it). */
  primaryValue: number | null
  /** Other metric values keyed by column. */
  values: Record<string, number>
  /** Every scalar metric of the path (row tooltip — nothing is lost to the column cap). */
  allMetrics: Record<string, number>
  trainingMs: number | null
  totalMs: number | null
  best: boolean
  /** Step to focus when the row is clicked (metrics node, else last node). */
  focusNodeId: string | null
}

/** Primary metric name shared by the table (best path's, else first scored path's). */
export function pathTablePrimaryName(paths: PathResult[], bestPathId?: string | null): string | null {
  const scored = paths.filter((p) => p.primary)
  const best = pickBestPath(scored, bestPathId)
  return best?.primary?.name ?? scored[0]?.primary?.name ?? null
}

/**
 * One row per path for the Overview comparison table. `best` is set only when
 * at least two paths are scored (a single scored path is not "best" of anything).
 */
export function pathTableRows(input: {
  paths: PathResult[]
  bestPathId?: string | null
  columns: string[]
  primaryName: string | null
  timingOf?: (p: PathResult) => PathTiming | null | undefined
}): PathTableRow[] {
  const scored = input.paths.filter((p) => p.primary)
  const best = scored.length >= 2 ? pickBestPath(scored, input.bestPathId) : null
  const primaryName = input.primaryName
  return input.paths.map((p) => {
    const values: Record<string, number> = {}
    for (const c of input.columns) if (typeof p.metrics[c] === 'number') values[c] = p.metrics[c]
    let primaryValue: number | null = null
    if (primaryName) {
      if (typeof p.metrics[primaryName] === 'number') primaryValue = p.metrics[primaryName]
      else if (p.primary?.name === primaryName) primaryValue = p.primary.value
    }
    const t = input.timingOf?.(p) ?? null
    return {
      pathId: p.pathId,
      letter: p.letter,
      label: `Path ${p.letter}`,
      description: p.description,
      primaryValue,
      values,
      allMetrics: { ...p.metrics },
      trainingMs: t?.trainingMs ?? null,
      totalMs: t?.totalMs ?? null,
      best: Boolean(best && best.pathId === p.pathId),
      focusNodeId: p.metricsNodeId || p.nodeIds[p.nodeIds.length - 1] || null,
    }
  })
}

/**
 * Training time + total time of one path's steps. `trainingMs` sums steps whose
 * node type / id says train (null when the path has no trainer).
 */
export function pathTiming(
  nodeIds: string[],
  durationOf: (id: string) => number | null | undefined,
  nodeTypeOf: (id: string) => string | null | undefined,
): PathTiming {
  let total = 0
  let anyTotal = false
  let train = 0
  let anyTrain = false
  for (const id of nodeIds) {
    const d = durationOf(id)
    if (typeof d !== 'number' || !Number.isFinite(d)) continue
    total += d
    anyTotal = true
    if (/train/i.test(`${nodeTypeOf(id) || ''} ${id}`)) {
      train += d
      anyTrain = true
    }
  }
  return { trainingMs: anyTrain ? train : null, totalMs: anyTotal ? total : null }
}

// ── Comparable runs (regression line) ───────────────────────────────────

/** Graph name of a run row / detail (top level or meta). */
export function graphNameOf(run: unknown): string {
  const r = rec(run)
  if (!r) return ''
  return str(r.graph_name) || str(rec(r.meta)?.graph_name)
}

/** Number of paths a run reports (backend summary.paths) — null when unknown. */
export function pathCountOf(run: unknown): number | null {
  const n = pathsFromSummary(run).length
  return n > 0 ? n : null
}

/**
 * Same pipeline (graph name) and — when both sides know it — the same number
 * of paths. Comparing a 3-path sweep with a 1-path run is not meaningful.
 */
export function isComparableRun(
  row: unknown,
  target: { graphName: string; pathCount: number | null },
): boolean {
  if (!target.graphName) return false
  if (graphNameOf(row) !== target.graphName) return false
  const n = pathCountOf(row)
  if (target.pathCount != null && n != null && n !== target.pathCount) return false
  return true
}

/**
 * Regression vs the best earlier comparable run, or null (hide the line).
 *
 * A backend `regression` is kept only when its previous run is in the loaded
 * list and comparable; otherwise the best earlier comparable run in `rows` is
 * used (same metric name, created before this run).
 */
export function comparableRegression(input: {
  runId: string
  graphName: string
  pathCount: number | null
  createdAt?: string | null
  current: PrimaryMetric | null
  backend: RegressionView | null
  rows: Array<Record<string, unknown>>
  metricOf: (row: Record<string, unknown>) => PrimaryMetric | null
}): RegressionView | null {
  const cur = input.current
  if (!cur || !input.graphName) return null
  const target = { graphName: input.graphName, pathCount: input.pathCount }
  const comparable = input.rows.filter(
    (r) => str(r.run_id) && str(r.run_id) !== input.runId && isComparableRun(r, target),
  )
  const b = input.backend
  if (b?.previousRunId && comparable.some((r) => str(r.run_id) === b.previousRunId)) return b
  const t0 = input.createdAt ? Date.parse(input.createdAt) : NaN
  const up = higherIsBetter(cur.name)
  let best: { value: number; runId: string } | null = null
  for (const row of comparable) {
    const t = Date.parse(str(row.created_at))
    if (Number.isFinite(t0) && Number.isFinite(t) && t > t0) continue
    const pm = input.metricOf(row)
    if (!pm || pm.name !== cur.name) continue
    if (!best || (up ? pm.value > best.value : pm.value < best.value)) best = { value: pm.value, runId: str(row.run_id) }
  }
  if (!best) return null
  return { delta: cur.value - best.value, previousValue: best.value, previousRunId: best.runId, metricName: cur.name }
}

// ── "What happened" grouping ────────────────────────────────────────────

export type StepGroup<T> = {
  key: string
  /** "Shared" / "Path A (MobileNet · lr 0.002)" — null for a linear run. */
  label: string | null
  /** Rows numbered 1… within the group. */
  rows: Array<{ item: T; index: number }>
}

/**
 * Linear runs → one unlabeled group; fork/parallel → Shared, Path A, Path B…
 * Numbers restart in every group (no 1, 2, 3, 7, 10 jumps).
 */
export function groupStepsByLane<T>(
  items: T[],
  idOf: (item: T) => string,
  shape: Pick<PipelineShape, 'kind' | 'branches' | 'laneOf'>,
  lanePaths?: Map<string, Pick<PathResult, 'letter' | 'description'>> | null,
): Array<StepGroup<T>> {
  const number = (list: T[]) => list.map((item, i) => ({ item, index: i + 1 }))
  if (shape.kind !== 'fork' && shape.kind !== 'parallel') {
    return items.length ? [{ key: 'all', label: null, rows: number(items) }] : []
  }
  const laneOrder: string[] = []
  if (shape.kind === 'fork') laneOrder.push('shared')
  shape.branches.forEach((_, i) => laneOrder.push(String.fromCharCode(65 + Math.min(i, 25))))
  const out: Array<StepGroup<T>> = []
  const seen = new Set<T>()
  for (const lane of laneOrder) {
    const list = items.filter((it) => (shape.laneOf.get(idOf(it)) || 'shared') === lane)
    if (!list.length) continue
    list.forEach((it) => seen.add(it))
    const path = lane === 'shared' ? null : lanePaths?.get(lane)
    out.push({ key: lane, label: path ? pathDisplayName(path) : laneLabel(lane), rows: number(list) })
  }
  const rest = items.filter((it) => !seen.has(it))
  if (rest.length) out.push({ key: 'rest', label: 'Other steps', rows: number(rest) })
  return out
}

// ── Friendly artifact names ─────────────────────────────────────────────

export type FriendlyName = { label: string; raw: string; renamed: boolean }

const COMPILED_RE = /^compiled_[0-9a-f]{6,}\.(keras|h5)$/i
const LONG_HEX_RE = /[0-9a-f]{16,}/gi

/**
 * Display name for an output file. Internal names such as
 * `compiled_<32 hex>.keras` become "Untrained model (architecture)"; other long
 * hex runs are shortened to 8 chars + "…". `raw` keeps the real name (tooltip).
 */
export function friendlyArtifactName(nameOrPath: string): FriendlyName {
  const raw = String(nameOrPath || '').replace(/\/+$/, '').split('/').pop() || String(nameOrPath || '')
  if (COMPILED_RE.test(raw)) return { label: 'Untrained model (architecture)', raw, renamed: true }
  if (/[0-9a-f]{16,}/i.test(raw)) {
    const label = raw.replace(LONG_HEX_RE, (m) => `${m.slice(0, 8)}…`)
    return { label, raw, renamed: label !== raw }
  }
  return { label: raw, raw, renamed: false }
}

// ── Run list ────────────────────────────────────────────────────────────

function errLine(v: unknown): string {
  if (typeof v === 'string') return v.trim()
  const o = rec(v)
  if (!o) return ''
  return str(o.message) || str(o.error_message) || str(o.error) || str(o.detail) || str(o.reason)
}

/**
 * One-line failure reason for a run-list row (`error` / `error_message` /
 * `failure` on the row or its meta), humanized, first line only, ≤ max chars.
 */
export function runFailureReason(run: unknown, max = 140): string | null {
  const r = rec(run)
  if (!r) return null
  const meta = rec(r.meta)
  const sources = [r.error_message, r.error, r.failure, r.failure_reason, meta?.error_message, meta?.error, meta?.failure, meta?.failure_reason]
  let text = ''
  for (const s of sources) {
    text = errLine(s)
    if (text) break
  }
  if (!text) return null
  const errorType = str(r.error_type) || str(meta?.error_type) || str(rec(r.failure)?.error_type) || str(rec(meta?.failure)?.error_type)
  let line = humanizeErrorText(text.split(/\r?\n/).find((l) => l.trim()) || text).trim()
  if (errorType && !line.toLowerCase().startsWith(errorType.toLowerCase())) line = `${errorType}: ${line}`
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line
}

// ── Run record summary ──────────────────────────────────────────────────

/**
 * Parts of the collapsed Run record line:
 * "Verified ✓ · chain #12 · seed 42 · 3 not recorded".
 */
export function recordSummaryParts(input: {
  hasProve: boolean
  pending?: boolean
  loading?: boolean
  gapCount: number
  chainPosition: number | null
  seed: number | null
  /** Result of Verify in this session (null = not run). */
  verify?: { ok: boolean | null; status?: string } | null
  /**
   * Last server-recorded verify (`last_verify` on the run, or this session's
   * Verify response) → "Verified ✓ Oct 4 17:59 by alice · 6/6". Wins over `verify`.
   */
  lastVerify?: LastVerify | null
  /** Time formatter for `lastVerify` (tests). */
  formatWhen?: (iso: string) => string
}): { verdict: string; tone: 'ok' | 'warn' | 'muted'; details: string[] } {
  let verdict = 'Not verified'
  let tone: 'ok' | 'warn' | 'muted' = 'muted'
  if (input.pending) verdict = 'Sealed when the run finishes'
  else if (input.loading) verdict = 'Loading…'
  else if (!input.hasProve) {
    verdict = 'No record'
    tone = 'warn'
  } else if (input.lastVerify) {
    const t = lastVerifyText(input.lastVerify, input.formatWhen)
    verdict = t.text
    tone = t.tone === 'ok' ? 'ok' : 'warn'
  } else if (input.verify) {
    if (input.verify.status === 'unsealed') verdict = 'Not sealed'
    else if (input.verify.ok) {
      verdict = 'Verified ✓'
      tone = 'ok'
    } else {
      verdict = 'Verification found changes'
      tone = 'warn'
    }
  }
  const details: string[] = []
  if (input.chainPosition != null) details.push(`chain #${input.chainPosition}`)
  if (input.seed != null) details.push(`seed ${input.seed}`)
  if (input.gapCount > 0) details.push(`${input.gapCount} not recorded`)
  return { verdict, tone, details }
}

// ── Step picker ─────────────────────────────────────────────────────────

export type StepOption = { value: string; label: string; description?: string }

function statusWord(status?: string): string {
  const s = String(status || '').toLowerCase()
  if (['succeeded', 'completed', 'success', 'done'].includes(s)) return 'done'
  if (s === 'error') return 'failed'
  if (s === 'canceled') return 'cancelled'
  return s
}

/**
 * Options for the compact step dropdown: "All steps", then steps grouped
 * Shared → Path A → Path B (path prefix on multi-path runs). Opaque ids are dropped.
 */
export function stepPickerOptions(
  items: Array<{ id: string; label?: string; status?: string }>,
  laneOf?: Map<string, string> | null,
): StepOption[] {
  const visible = items.filter((it) => it.id && !looksLikeOpaqueId(it.id))
  const lanes: string[] = ['shared']
  if (laneOf) for (const it of visible) {
    const l = laneOf.get(it.id) || 'shared'
    if (!lanes.includes(l)) lanes.push(l)
  }
  const ordered = laneOf
    ? lanes.flatMap((l) => visible.filter((it) => (laneOf.get(it.id) || 'shared') === l))
    : visible
  const out: StepOption[] = [{ value: '', label: 'All steps' }]
  for (const it of ordered) {
    const lane = laneOf?.get(it.id) || 'shared'
    const base = (it.label || it.id).replace(/\s·\sPath [A-Z]$/, '')
    const label = laneOf ? `${laneLabel(lane)} · ${base}` : base
    const st = statusWord(it.status)
    out.push({ value: it.id, label, ...(st ? { description: st } : {}) })
  }
  return out
}
