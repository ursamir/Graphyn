/**
 * Pure helpers for Compare runs: node config parameters from each run's
 * graph.json, flattened to `node_id.field`, plus a diff-aware table.
 *
 * Compare showed "No parameters recorded" for runs whose node configs
 * differed, because only experiment-level params were read. Feed
 * `flattenNodeConfigParams(graph)` into the per-run params (graph-level
 * `parameters` included as `graph.<key>`), then render `compareParamRows`.
 *
 * No React here so it can be unit-tested in the node vitest env.
 */
import { stableStringify } from '../builder/graphHistory'
import { naturalCompare } from '../../lib/naturalSort'

type GraphLike = {
  nodes?: Array<{ id?: unknown; config?: unknown }> | null
  parameters?: unknown
} | null | undefined

function scalar(v: unknown): unknown {
  if (v === null || v === undefined) return v ?? null
  if (typeof v === 'object') return stableStringify(v)
  return v
}

/**
 * `{ "<node_id>.<field>": value }` for every node config field, and
 * `{ "graph.<key>": value }` for graph-level parameters (except `ui`).
 * Object/array values are stringified (stable key order) so they compare.
 */
export function flattenNodeConfigParams(graph: GraphLike): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const params = graph?.parameters
  if (params && typeof params === 'object' && !Array.isArray(params)) {
    for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
      if (k === 'ui') continue
      out[`graph.${k}`] = scalar(v)
    }
  }
  for (const n of Array.isArray(graph?.nodes) ? graph!.nodes! : []) {
    const id = typeof n?.id === 'string' ? n.id : ''
    if (!id || !n.config || typeof n.config !== 'object') continue
    for (const [k, v] of Object.entries(n.config as Record<string, unknown>)) {
      out[`${id}.${k}`] = scalar(v)
    }
  }
  return out
}

export type CompareParamRow = { key: string; values: unknown[]; differs: boolean }

/**
 * Rows for the compare table: one per key present in any run, in natural key
 * order. `differs` is true when any two runs disagree (a key missing in one
 * run counts as different). With `onlyDiffering`, identical rows are dropped.
 */
export function compareParamRows(
  runs: Array<{ params?: Record<string, unknown> | null }>,
  opts: { onlyDiffering?: boolean } = {},
): CompareParamRow[] {
  const keys = new Set<string>()
  for (const r of runs) for (const k of Object.keys(r.params ?? {})) keys.add(k)
  const rows = [...keys].sort(naturalCompare).map((key) => {
    const values = runs.map((r) => (r.params && key in r.params ? r.params[key] : undefined))
    const sigs = new Set(values.map((v) => (v === undefined ? '\u0000missing' : stableStringify(v))))
    return { key, values, differs: sigs.size > 1 }
  })
  return opts.onlyDiffering ? rows.filter((r) => r.differs) : rows
}

/** Merge experiment-level params with node config params (experiment keys win). */
export function mergeRunParams(
  experimentParams: Record<string, unknown> | null | undefined,
  graph: GraphLike,
): Record<string, unknown> {
  return { ...flattenNodeConfigParams(graph), ...(experimentParams ?? {}) }
}

/** Config fields that hold a node's write location. */
const RUN_PATH_FIELD = /\.(output_path|output_dir|out_dir|output|save_path|artifacts_dir|checkpoint_dir|log_dir)$/i

/**
 * True when a param row only differs because each run writes under its own
 * `runs/<run_id>` folder (e.g. `trainer_0.output_path`). Those rows always
 * differ and are hidden behind "Show run-specific paths".
 */
export function isRunScopedPathParam(key: string, values: unknown[], runIds: string[]): boolean {
  const strs = values.map((v) => (typeof v === 'string' ? v : ''))
  const mentionsOwnRun = strs.some((s, i) => {
    const id = runIds[i]
    return Boolean(s && id && (s.includes(`runs/${id}`) || s.includes(id)))
  })
  if (mentionsOwnRun) {
    // Every non-empty value is the same path once its own run id is masked.
    const masked = new Set(
      strs.filter(Boolean).map((s, i) => (runIds[i] ? s.split(runIds[i]).join('<run>') : s)),
    )
    if (masked.size <= 1) return true
  }
  if (!RUN_PATH_FIELD.test(key)) return false
  return strs.some((s) => /(^|\/)runs\/[0-9a-f]{8,}/i.test(s))
}

/**
 * "trainer_24212f65.epochs" → "Trainer · Path C · epochs" using node labels
 * from the runs' graphs (ids stay in the tooltip). Keys without a known node
 * id (graph.* / experiment params) are returned unchanged.
 */
export function paramKeyLabel(key: string, labelOf: ReadonlyMap<string, string>): string {
  const dot = key.indexOf('.')
  if (dot <= 0) return key
  const nodeId = key.slice(0, dot)
  const label = labelOf.get(nodeId)
  return label ? `${label} · ${key.slice(dot + 1)}` : key
}

type LabelGraph = {
  nodes?: Array<{ id?: unknown; node_type?: unknown; label?: unknown; config?: unknown }> | null
  edges?: Array<{ src_id?: unknown; dst_id?: unknown }> | null
} | null | undefined

/**
 * node id → path-aware label ("Trainer · Path C") across the compared runs'
 * graphs; `labelsFor(graph)` is the Editor's canvasPathView-style labeller
 * (injected so this module stays React/builder-free). First graph wins.
 */
export function compareNodeLabels(
  graphs: Iterable<LabelGraph>,
  labelsFor: (graph: NonNullable<LabelGraph>) => ReadonlyMap<string, string>,
): Map<string, string> {
  const out = new Map<string, string>()
  for (const g of graphs) {
    if (!g || !Array.isArray(g.nodes)) continue
    for (const [id, label] of labelsFor(g)) if (!out.has(id)) out.set(id, label)
  }
  return out
}
