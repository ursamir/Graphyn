/**
 * Pure helpers for the compact Runs Overview + inline step details and the
 * Run outputs default ordering (unit-tested in the node vitest env):
 *
 *  - one-line path group summaries ("Path C · MobileNet · 4 steps · 4m 31s · Test accuracy 75.6%")
 *  - which "What happened" groups start open (best path, or the failed path)
 *  - the step's config as key/value rows (changed-from-default when the schema knows defaults)
 *  - the step's last log lines / image outputs
 *  - Run outputs: steps ordered by importance (best path's evaluator/trainer/optimizer first,
 *    dataset ingest last) and the file preselected on open (metrics / plot / model)
 */
import { formatMetricValue, metricLabel } from '../../lib/metrics'
import { formatStepDuration } from './runOverview'

// ── Path groups ─────────────────────────────────────────────────────────

/** Parts of a collapsed path group row, joined with " · " by the caller. */
export function pathGroupSummary(input: {
  letter: string
  description?: string | null
  stepCount: number
  totalMs?: number | null
  primary?: { name: string; value: number } | null
}): string[] {
  const parts = [`Path ${input.letter}`]
  const desc = String(input.description || '').trim()
  if (desc) parts.push(desc)
  parts.push(`${input.stepCount} step${input.stepCount === 1 ? '' : 's'}`)
  if (input.totalMs != null && Number.isFinite(input.totalMs) && input.totalMs > 0) {
    parts.push(formatStepDuration(input.totalMs))
  }
  if (input.primary && Number.isFinite(input.primary.value)) {
    parts.push(`${metricLabel(input.primary.name)} ${formatMetricValue(input.primary.name, input.primary.value)}`)
  }
  return parts
}

/**
 * Groups open by default: non-path groups (Shared, linear "all", Other steps)
 * always; of the path lanes, the failed ones when any failed, else the best
 * one; plus the lane of the focused step (so a clicked step is never hidden).
 */
export function defaultOpenGroups(input: {
  keys: string[]
  bestLane?: string | null
  failedLanes?: string[]
  focusLane?: string | null
}): Set<string> {
  const isPathLane = (k: string) => /^[A-Z]$/.test(k)
  const open = new Set(input.keys.filter((k) => !isPathLane(k)))
  const failed = (input.failedLanes || []).filter((k) => input.keys.includes(k))
  if (failed.length) failed.forEach((k) => open.add(k))
  else if (input.bestLane && input.keys.includes(input.bestLane)) open.add(input.bestLane)
  else {
    // No best / failure known: open the only path, else leave paths folded.
    const lanes = input.keys.filter(isPathLane)
    if (lanes.length === 1) open.add(lanes[0])
  }
  if (input.focusLane && input.keys.includes(input.focusLane)) open.add(input.focusLane)
  return open
}

// ── Step config ─────────────────────────────────────────────────────────

export type ConfigEntry = {
  key: string
  value: string
  /** true = differs from the schema default, false = equals it / default used, null = no default known. */
  changed: boolean | null
  /** Schema default (formatted) when known and different. */
  defaultValue?: string
  /** Not set in the graph — the schema default was used. */
  fromDefault?: boolean
}

function fmtValue(v: unknown): string {
  if (v == null) return 'null'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function same(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a === 'number' && typeof b === 'string') return String(a) === b.trim()
  if (typeof b === 'number' && typeof a === 'string') return String(b) === a.trim()
  try {
    return JSON.stringify(a) === JSON.stringify(b)
  } catch {
    return false
  }
}

/**
 * The settings a step ran with (graph snapshot `config`). Keys set in the graph
 * come first (changed-from-default first), then schema defaults that applied.
 * Private keys (`_ui`, `__meta`) are skipped.
 */
export function stepConfigEntries(
  config: Record<string, unknown> | null | undefined,
  schema?: { properties?: Record<string, Record<string, unknown>> } | null,
): ConfigEntry[] {
  const props = schema?.properties || {}
  const cfg = config && typeof config === 'object' && !Array.isArray(config) ? config : {}
  const set: ConfigEntry[] = []
  for (const [key, value] of Object.entries(cfg)) {
    if (key.startsWith('_')) continue
    const p = props[key]
    const hasDefault = Boolean(p && Object.prototype.hasOwnProperty.call(p, 'default'))
    const changed = hasDefault ? !same(value, p!.default) : null
    set.push({
      key,
      value: fmtValue(value),
      changed,
      ...(changed ? { defaultValue: fmtValue(p!.default) } : {}),
    })
  }
  const rank = (e: ConfigEntry) => (e.changed === true ? 0 : e.changed === null ? 1 : 2)
  set.sort((a, b) => rank(a) - rank(b))
  const defaults: ConfigEntry[] = []
  for (const [key, p] of Object.entries(props)) {
    if (key.startsWith('_') || Object.prototype.hasOwnProperty.call(cfg, key)) continue
    if (!p || !Object.prototype.hasOwnProperty.call(p, 'default')) continue
    defaults.push({ key, value: fmtValue(p.default), changed: false, fromDefault: true })
  }
  return [...set, ...defaults]
}

// ── Logs / images per step ──────────────────────────────────────────────

/** Last `limit` rows whose node hint matches the step (+ how many matched in total). */
export function lastLogsForNode<T>(
  rows: T[],
  nodeId: string,
  hintOf: (row: T) => string | null | undefined,
  matches: (focus: string, hint: string | null | undefined) => boolean,
  limit = 20,
): { rows: T[]; total: number } {
  const hit = rows.filter((r) => matches(nodeId, hintOf(r)))
  return { rows: hit.slice(Math.max(0, hit.length - limit)), total: hit.length }
}

const IMAGE_RE = /\.(png|jpe?g|gif|svg|webp)$/i

/** Image outputs of one step, confusion matrix first, then curves, then the rest (max `limit`). */
export function imageOutputsForNode<F extends { name: string; path: string; node_id?: string | null }>(
  files: F[],
  nodeId: string,
  matches: (focus: string, candidate: string | null | undefined) => boolean,
  limit = 6,
): F[] {
  const rank = (n: string) => (/confusion/i.test(n) ? 0 : /curve|history|loss|acc|roc|pr_/i.test(n) ? 1 : 2)
  const seen = new Set<string>()
  return files
    .filter((f) => IMAGE_RE.test(f.name || f.path) && matches(nodeId, f.node_id))
    .filter((f) => (seen.has(f.path) ? false : (seen.add(f.path), true)))
    .sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
    .slice(0, limit)
}

// ── Run outputs: importance ordering + default file ─────────────────────

export type OutputGroupInfo = {
  nodeType?: string | null
  /** Lane of the step ('shared', 'A', 'B'…) — null on linear runs. */
  lane?: string | null
  /** Source step (no incoming edges / dataset reader). */
  isSource?: boolean
}

const EVAL_RE = /evaluat/i
const TRAIN_RE = /train/i
const SHIP_RE = /optimi|quantiz|tflite|export|convert|packag|compress|prune|edge/i
const INGEST_RE = /ingest|dataset|loader|reader|load_|source|download/i

function roleWeight(text: string): number | null {
  if (EVAL_RE.test(text)) return 0
  if (TRAIN_RE.test(text)) return 1
  if (SHIP_RE.test(text)) return 2
  return null
}

/**
 * Run outputs groups by importance: evaluator / trainer / optimizer steps first
 * (best path first, then other paths, then shared), then other steps in
 * execution order, then run-level files, then dataset ingest / source steps.
 */
export function orderOutputGroupsByImportance(
  order: string[],
  infoOf: (id: string) => OutputGroupInfo | null | undefined,
  bestLane?: string | null,
): string[] {
  const laneRank = (lane: string | null | undefined): number => {
    if (!lane || lane === 'shared') return 50
    if (bestLane && lane === bestLane) return 0
    return 1 + (lane.charCodeAt(0) - 65)
  }
  const keyed = order.map((id, index) => {
    if (id === 'run') return { id, tier: 2, lane: 0, role: 0, index }
    const info = infoOf(id) || {}
    const text = `${info.nodeType || ''} ${id}`
    const role = roleWeight(text)
    const source = Boolean(info.isSource) || INGEST_RE.test(text)
    if (role != null && !source) return { id, tier: 0, lane: laneRank(info.lane), role, index }
    if (source) return { id, tier: 3, lane: 0, role: 0, index }
    return { id, tier: 1, lane: 0, role: 0, index }
  })
  keyed.sort((a, b) => a.tier - b.tier || a.lane - b.lane || a.role - b.role || a.index - b.index)
  return keyed.map((k) => k.id)
}

function fileScore(name: string): number {
  const n = name.toLowerCase()
  if (/metrics.*\.json$/.test(n)) return 0
  if (/confusion.*\.(png|jpe?g|svg)$/.test(n)) return 1
  if (IMAGE_RE.test(n)) return 2
  if (/\.(tflite|keras|h5|onnx|pt|pth)$/.test(n) && !/^compiled_/.test(n)) return 3
  return 9
}

/**
 * File to preview when Run outputs opens: within the first group that has a
 * metrics file, plot or trained model, the best of those; else the first file.
 */
export function pickDefaultOutput<F extends { name: string; path: string }>(groups: F[][]): F | null {
  for (const files of groups) {
    let best: F | null = null
    let bestScore = 99
    for (const f of files) {
      const s = fileScore(f.name || f.path.split('/').pop() || '')
      if (s < bestScore) {
        best = f
        bestScore = s
      }
    }
    if (best && bestScore <= 3) return best
  }
  for (const files of groups) if (files.length) return files[0]
  return null
}

/** Summary-line chip for provenance records ("21 tracked files"). */
export function trackedFilesLabel(n: number | null | undefined): string | null {
  if (n == null || !Number.isFinite(n) || n <= 0) return null
  return `${n.toLocaleString()} tracked file${n === 1 ? '' : 's'}`
}
