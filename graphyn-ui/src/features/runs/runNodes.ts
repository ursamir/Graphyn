/**
 * Pure helpers for the Runs detail: the run's node list (PipelineStack) and
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
import { humanNodeLabel } from '../../lib/format'
import { normalizeRunStatus } from '../../lib/runStatus'
import { statusesFromEvents } from '../builder/builderRunState'

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

/** node_stats / event status strings → the vocabulary PipelineStack colors. */
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
  return order.map((id) => {
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
}

export type RunFailure = { nodeId: string | null; nodeType: string | null; error: string }

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
    if (error) return { ...nodeOf(ev), error }
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
  const failedFromStatus = str(input.status?.failed_node) || str(input.status?.current_node) || null
  const fallbackNode = failedNode ?? { nodeId: failedFromStatus, nodeType: null }
  if (direct) return { ...fallbackNode, error: direct }
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
