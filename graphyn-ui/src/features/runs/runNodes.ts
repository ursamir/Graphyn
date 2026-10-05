/**
 * Pure helpers for the Runs detail: the run's node list (step picker / What happened) and
 * the failure summary used by "Ask agent to fix".
 *
 *  - `pipelineNodesFromRun` builds the node list from the run's graph in
 *    execution order (topological, ties by graph order / node_stats index), so
 *    nodes that never ran (e.g. Segmenter after an Audio Conditioner failure)
 *    still appear, numbered correctly. Statuses come from journal events, then
 *    node_stats; a node with no status on a failed/cancelled run is "skipped".
 *  - `extractRunFailure` finds the real error text. Node failures carry the
 *    message in the event's `error` / `error_message` field, not `message`.
 *
 * No React here so it can be unit-tested in the node vitest env.
 */
import { humanNodeLabel, instanceIdCue } from '../../lib/format'
import { normalizeRunStatus } from '../../lib/runStatus'
import { statusesFromEvents } from '../builder/builderRunState'
import { looksLikeOpaqueId } from './runOutputs'

export type RunGraphLike = {
  nodes?: Array<{ id?: unknown; node_type?: unknown; label?: unknown; config?: unknown }> | null
  edges?: Array<{ src_id?: unknown; dst_id?: unknown }> | null
} | null | undefined

export type RunNodeItem = { id: string; label: string; nodeType?: string; status?: string }

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function toIdx(v: unknown): number | null {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : null
}

/**
 * Stable Kahn topological order of the graph's nodes. Ties (several ready
 * nodes) break by `rank` (e.g. node_stats.node_index) and then graph order.
 * Nodes left in a cycle are appended in graph order.
 */
export function topoOrderGraph(graph: RunGraphLike, rank: Map<string, number> = new Map()): string[] {
  const nodes = (Array.isArray(graph?.nodes) ? graph!.nodes! : []).map((n) => str(n?.id)).filter(Boolean)
  const ids = [...new Set(nodes)]
  const pos = new Map(ids.map((id, i) => [id, i]))
  const indeg = new Map(ids.map((id) => [id, 0]))
  const out = new Map(ids.map((id) => [id, [] as string[]]))
  for (const e of Array.isArray(graph?.edges) ? graph!.edges! : []) {
    const s = str(e?.src_id)
    const d = str(e?.dst_id)
    if (!indeg.has(s) || !indeg.has(d) || s === d) continue
    out.get(s)!.push(d)
    indeg.set(d, (indeg.get(d) ?? 0) + 1)
  }
  const key = (id: string) => [rank.get(id) ?? Number.MAX_SAFE_INTEGER, pos.get(id) ?? 0] as const
  const cmp = (a: string, b: string) => {
    const [ra, pa] = key(a)
    const [rb, pb] = key(b)
    return ra - rb || pa - pb
  }
  const ready = ids.filter((id) => (indeg.get(id) ?? 0) === 0).sort(cmp)
  const order: string[] = []
  while (ready.length) {
    const id = ready.shift()!
    order.push(id)
    for (const t of out.get(id) ?? []) {
      indeg.set(t, (indeg.get(t) ?? 0) - 1)
      if (indeg.get(t) === 0) {
        ready.push(t)
        ready.sort(cmp)
      }
    }
  }
  for (const id of ids) if (!order.includes(id)) order.push(id)
  return order
}

/** node_stats / event status strings → the vocabulary the step views colour. */
export function normalizeNodeStatus(raw: unknown): string | undefined {
  const s = str(raw).toLowerCase()
  if (!s) return undefined
  if (['succeeded', 'success', 'completed', 'complete', 'done', 'ok'].includes(s)) return 'succeeded'
  if (['failed', 'error', 'fail'].includes(s)) return 'failed'
  if (['skipped', 'skip', 'not_run', 'not-run'].includes(s)) return 'skipped'
  if (['cancelled', 'canceled', 'cancel'].includes(s)) return 'cancelled'
  if (['running', 'started', 'in_progress'].includes(s)) return 'running'
  if (['pending', 'queued', 'waiting'].includes(s)) return 'pending'
  return s
}

/**
 * The run's nodes in execution order with statuses.
 *  - graph present → every graph node, topologically ordered
 *  - no graph → node_stats (by node_index), then journal node_start order
 */
export function pipelineNodesFromRun(input: {
  graph?: RunGraphLike
  nodeStats?: Array<Record<string, unknown>> | null
  events?: Array<Record<string, unknown>> | null
  runStatus?: unknown
  /** false → keep plain labels (caller disambiguates by path). Default true (`#cue`). */
  disambiguate?: boolean
}): RunNodeItem[] {
  const stats = Array.isArray(input.nodeStats) ? input.nodeStats : []
  const events = Array.isArray(input.events) ? input.events : []
  const rank = new Map<string, number>()
  stats.forEach((n, i) => {
    const id = str(n.node_id)
    if (!id || rank.has(id)) return
    rank.set(id, toIdx(n.node_index) ?? 10_000 + i)
  })
  const graphNodes = Array.isArray(input.graph?.nodes) ? input.graph!.nodes! : []
  let order: string[]
  if (graphNodes.length > 0) {
    order = topoOrderGraph(input.graph, rank)
  } else {
    order = [...rank.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id)
    for (const ev of events) {
      if (String(ev?.type ?? ev?.event ?? '') !== 'node_start') continue
      const id = str(ev.node_id)
      if (id && !order.includes(id)) order.push(id)
    }
  }
  const byGraph = new Map(graphNodes.map((n) => [str(n?.id), n]))
  const byStats = new Map(stats.map((n) => [str(n.node_id), n]))
  const fromEvents = statusesFromEvents(events, order)
  const run = normalizeRunStatus(input.runStatus)
  const terminalNotOk = run === 'failed' || run === 'cancelled'
  const terminal = terminalNotOk || run === 'completed'
  const items = order
    .filter((id) => id && !looksLikeOpaqueId(id))
    .map((id) => {
      const g = byGraph.get(id)
      const s = byStats.get(id)
      const nodeType = str(g?.node_type) || str(s?.node_type) || undefined
      let status = normalizeNodeStatus(fromEvents.get(id)) ?? normalizeNodeStatus(s?.status ?? s?.state)
      // A node still "running" in a finished run never completed.
      if (status === 'running' && terminal) status = run === 'cancelled' ? 'cancelled' : run === 'failed' ? 'failed' : status
      if (!status || status === 'pending') {
        if (terminalNotOk) status = 'skipped'
      }
      return {
        id,
        label: str(g?.label) || humanNodeLabel(nodeType || id),
        nodeType,
        status,
      }
    })
  return input.disambiguate === false ? items : disambiguatePipelineLabels(items)
}

/**
 * Human disambiguation for dual-branch copies: two "Trainer" steps become
 * "Trainer · Path A" / "Trainer · Path B" (via `pathOf`). Steps whose path is
 * unknown fall back to the `#cue` suffix. Unique labels are left alone.
 */
export function disambiguateByPath<T extends { id: string; label: string; nodeType?: string }>(
  items: T[],
  pathOf: (id: string) => string | null | undefined,
): T[] {
  const counts = new Map<string, number>()
  for (const it of items) {
    const key = it.label.toLowerCase()
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  const out = items.map((it) => {
    if ((counts.get(it.label.toLowerCase()) || 0) < 2) return it
    const path = pathOf(it.id)
    if (path) return { ...it, label: `${it.label} · ${path}` }
    return it
  })
  // Still-ambiguous labels (same path, or no path) keep the id cue.
  const after = new Map<string, number>()
  for (const it of out) after.set(it.label.toLowerCase(), (after.get(it.label.toLowerCase()) || 0) + 1)
  return out.map((it) => {
    if ((after.get(it.label.toLowerCase()) || 0) < 2) return it
    const cue = instanceIdCue(it.id, it.nodeType)
    return cue ? { ...it, label: `${it.label} #${cue}` } : it
  })
}

/** Append `#0` / `#c3f15543` when two steps share the same base label. */
export function disambiguatePipelineLabels<T extends { id: string; label: string; nodeType?: string }>(
  items: T[],
): T[] {
  const counts = new Map<string, number>()
  for (const it of items) {
    const key = it.label.toLowerCase()
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return items.map((it) => {
    if ((counts.get(it.label.toLowerCase()) || 0) < 2) return it
    const cue = instanceIdCue(it.id, it.nodeType)
    if (!cue) return it
    return { ...it, label: `${it.label} #${cue}` }
  })
}

export type PipelineShapeKind = 'linear' | 'fork' | 'parallel'

export type PipelineShape = {
  kind: PipelineShapeKind
  sharedIds: string[]
  /** Ordered node ids after the shared spine (fork) or full sink paths (parallel). */
  branches: string[][]
  /** id → `shared` | `A` | `B` | … — meaningful for fork/parallel only. */
  laneOf: Map<string, string>
}

/** True when Overview / stack should show Path chrome (not a single spine). */
export function isMultiTrackShape(shape: PipelineShape | null | undefined): boolean {
  return shape?.kind === 'fork' || shape?.kind === 'parallel'
}

/**
 * Recover a readable pipeline shape from stack order + graph edges.
 * Walks each sink backwards via its closest parent (highest stack index).
 * - linear: one sink (or one path) — includes single-sink diamonds
 * - fork: ≥2 sinks with a shared prefix
 * - parallel: ≥2 sinks with no shared prefix (no fake Shared trunk)
 */
export function computePipelineShape(
  orderedIds: string[],
  edges: Array<{ src_id?: unknown; dst_id?: unknown }> | null | undefined,
): PipelineShape {
  const ids = orderedIds.map((id) => String(id || '').trim()).filter(Boolean)
  const idSet = new Set(ids)
  const orderIndex = new Map(ids.map((id, i) => [id, i]))
  const fromMap = new Map<string, string[]>()
  const toMap = new Map<string, string[]>()
  for (const e of Array.isArray(edges) ? edges : []) {
    const src = str(e?.src_id)
    const dst = str(e?.dst_id)
    if (!src || !dst || !idSet.has(src) || !idSet.has(dst) || src === dst) continue
    toMap.set(src, [...(toMap.get(src) || []), dst])
    fromMap.set(dst, [...(fromMap.get(dst) || []), src])
  }

  const linear = (): PipelineShape => {
    const laneOf = new Map(ids.map((id) => [id, 'shared']))
    return { kind: 'linear', sharedIds: ids, branches: [], laneOf }
  }

  if (ids.length === 0 || toMap.size === 0) return linear()

  const sinks = ids.filter((id) => !(toMap.get(id) || []).length)
  if (sinks.length < 2) return linear()

  const primaryParent = (id: string): string | null => {
    const parents = (fromMap.get(id) || []).filter((p) => orderIndex.has(p))
    if (!parents.length) return null
    return parents.slice().sort((a, b) => (orderIndex.get(b) || 0) - (orderIndex.get(a) || 0))[0]
  }

  const pathToRoot = (endId: string): string[] => {
    const path = [endId]
    const seen = new Set([endId])
    let cur = endId
    for (;;) {
      const p = primaryParent(cur)
      if (!p || seen.has(p)) break
      path.unshift(p)
      seen.add(p)
      cur = p
    }
    return path
  }

  const paths = sinks.map(pathToRoot)
  let sharedLen = 0
  const minLen = Math.min(...paths.map((p) => p.length))
  while (
    sharedLen < minLen &&
    paths.every((p) => p[sharedLen] === paths[0][sharedLen])
  ) {
    sharedLen++
  }

  const rawBranches = paths.map((p) => p.slice(sharedLen)).filter((b) => b.length > 0)
  const uniqBranches: string[][] = []
  const seenKey = new Set<string>()
  for (const b of rawBranches) {
    const key = b.join('>')
    if (seenKey.has(key)) continue
    seenKey.add(key)
    uniqBranches.push(b)
  }
  if (uniqBranches.length < 2) return linear()

  const sharedIds = paths[0].slice(0, sharedLen)
  const kind: PipelineShapeKind = sharedLen >= 1 ? 'fork' : 'parallel'
  const laneOf = new Map<string, string>()
  for (const id of sharedIds) laneOf.set(id, 'shared')
  const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
  uniqBranches.forEach((branch, i) => {
    const lane = letters[i] || String(i + 1)
    for (const id of branch) {
      if (!laneOf.has(id)) laneOf.set(id, lane)
    }
  })
  for (const id of ids) {
    if (!laneOf.has(id)) laneOf.set(id, kind === 'parallel' ? 'A' : 'shared')
  }
  return { kind, sharedIds, branches: uniqBranches, laneOf }
}

/** Short lane copy for Overview / Pipeline stack (fork/parallel only). */
export function laneLabel(lane: string | undefined | null): string {
  if (!lane || lane === 'shared') return 'Shared'
  return `Path ${lane}`
}

export type RunFailure = {
  nodeId: string | null
  nodeType: string | null
  error: string
  /** Real exception class (audit API: node_error `error_type` / meta `error_type`). */
  errorType?: string
  /** Worker traceback text (node_error `traceback` / meta `error_traceback`). */
  traceback?: string
  /** Backend path-aware step label (`node_label`). */
  nodeLabel?: string
}

/** Parse a journal row whose `message` is itself a JSON event. */
function eventOf(row: Record<string, unknown>): Record<string, unknown> {
  if (typeof row.message === 'string' && row.message.trim().startsWith('{')) {
    try {
      const inner = JSON.parse(row.message) as unknown
      if (inner && typeof inner === 'object' && !Array.isArray(inner)) return { ...row, ...(inner as object) }
    } catch {
      /* plain text */
    }
  }
  return row
}

function errText(v: unknown): string {
  if (typeof v === 'string') return v.trim()
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    return errText(o.message ?? o.error ?? o.detail)
  }
  return ''
}

/**
 * Best error text for a failed run. Priority:
 *  1. last `node_error` event (error_message / error / message)
 *  2. last pipeline `error` event, or any event with a non-empty `error`
 *  3. `detail.error` / `status.error` / `meta.error`
 *  4. debug-report `recent_errors`
 *  5. last ERROR-level log message
 */
export function extractRunFailure(input: {
  events?: Array<Record<string, unknown>> | null
  detail?: Record<string, unknown> | null
  status?: Record<string, unknown> | null
  debug?: Record<string, unknown> | null
}): RunFailure | null {
  const events = (Array.isArray(input.events) ? input.events : [])
    .filter((e) => e && typeof e === 'object')
    .map(eventOf)
  const nodeOf = (ev: Record<string, unknown>) => ({
    nodeId: str(ev.node_id) || null,
    nodeType: str(ev.node_type) || null,
  })
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]
    if (String(ev.type ?? ev.event ?? '') !== 'node_error') continue
    const error = errText(ev.error_message) || errText(ev.error) || errText(ev.message)
    if (error) {
      return {
        ...nodeOf(ev),
        error,
        ...(str(ev.error_type) ? { errorType: str(ev.error_type) } : {}),
        ...(str(ev.traceback) ? { traceback: str(ev.traceback) } : {}),
        ...(str(ev.node_label) ? { nodeLabel: str(ev.node_label) } : {}),
      }
    }
  }
  let failedNode: { nodeId: string | null; nodeType: string | null } | null = null
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]
    const t = String(ev.type ?? ev.event ?? '')
    const error = errText(ev.error_message) || errText(ev.error) || (t === 'error' ? errText(ev.message) : '')
    if (error) {
      const n = nodeOf(ev)
      return { nodeId: n.nodeId, nodeType: n.nodeType, error }
    }
    if (!failedNode && (ev.status === 'failed' || t === 'node_failed') && str(ev.node_id)) failedNode = nodeOf(ev)
  }
  const meta = input.detail?.meta && typeof input.detail.meta === 'object' ? (input.detail.meta as Record<string, unknown>) : null
  const direct = errText(input.detail?.error) || errText(input.status?.error) || errText(meta?.error)
  const failedFromStatus =
    str(meta?.failed_node_id) || str(input.status?.failed_node) || str(input.status?.current_node) || null
  const fallbackNode = failedNode ?? { nodeId: failedFromStatus, nodeType: null }
  if (direct) {
    const errorType = str(meta?.error_type) || str(input.detail?.error_type)
    const traceback = str(meta?.error_traceback) || str(input.detail?.error_traceback)
    return {
      ...fallbackNode,
      error: direct,
      ...(errorType ? { errorType } : {}),
      ...(traceback ? { traceback } : {}),
    }
  }
  const recent = Array.isArray(input.debug?.recent_errors) ? (input.debug!.recent_errors as unknown[]) : []
  for (let i = recent.length - 1; i >= 0; i--) {
    const r = recent[i]
    const error = errText(r)
    if (error) {
      const o = r && typeof r === 'object' ? (r as Record<string, unknown>) : {}
      return { nodeId: str(o.node_id) || fallbackNode.nodeId, nodeType: str(o.node_type) || fallbackNode.nodeType, error }
    }
  }
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]
    if (String(ev.level ?? '').toUpperCase() !== 'ERROR') continue
    const error = errText(ev.message)
    if (error) return { ...nodeOf(ev), error }
  }
  return null
}

/** Proposal summary line for "Ask agent to fix" (≤ 280 chars). */
export function failureProposalSummary(runId: string, failure: RunFailure | null): string {
  const short = runId.slice(0, 8)
  if (!failure) return `Fix failed run ${short}: no error message was recorded — inspect the run logs`.slice(0, 280)
  const where = failure.nodeId
    ? ` at node ${failure.nodeId}${failure.nodeType && !failure.nodeId.startsWith(failure.nodeType) ? ` (${failure.nodeType})` : ''}`
    : ''
  const firstLine = failure.error.split('\n')[0].trim()
  return `Fix failed run ${short}${where}: ${firstLine}`.slice(0, 280)
}
