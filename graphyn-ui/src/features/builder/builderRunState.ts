/**
 * Pure helpers for the Editor's run-state + catalog decoration.
 *
 * Kept free of React / JSX so they can be unit-tested in the node vitest env.
 *
 *  - Execution badge: the outcome of a run must come from the server (or from
 *    this session's own terminal stream event for that exact run id) — never
 *    from component-local flags that reset on remount, and never defaulted to
 *    "succeeded".
 *  - Cancel / abort reconciliation: per-node statuses come from the run's
 *    journal events, not from painting every running/pending node cancelled.
 *  - Catalog re-decoration: a graph loaded before the node catalog arrived is
 *    re-decorated (category, runtime, schema, ports, defaults UNDER config)
 *    once the catalog is available.
 */
import { normalizeRunStatus } from '../../lib/runStatus'
import { humanNodeLabel } from '../../lib/format'
import { catalogPorts, type NodeCatalogEntry, type PortDef } from '../../types/graph'

/** What the Editor's Execution badge can show. */
export type ExecBadgeStatus = 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown' | 'loading' | 'missing'

/** Terminal outcome of a run started from this Editor session. */
export type KnownRunOutcome = 'succeeded' | 'failed' | 'cancelled'

/**
 * Module-level (survives BuilderView remounts, not page reloads) map of
 * run id → outcome observed by this session. The global store's `runOutcome`
 * is not keyed by run id, so it can't be trusted for an arbitrary lastRunId.
 */
const sessionOutcomes = new Map<string, KnownRunOutcome>()

export function rememberRunOutcome(runId: string | null | undefined, outcome: KnownRunOutcome): void {
  if (!runId) return
  sessionOutcomes.set(runId, outcome)
}

export function rememberedRunOutcome(runId: string | null | undefined): KnownRunOutcome | null {
  if (!runId) return null
  return sessionOutcomes.get(runId) ?? null
}

/** Test-only reset. */
export function _resetRememberedOutcomes(): void {
  sessionOutcomes.clear()
}

/** Map a server run status string to the badge vocabulary. */
export function badgeFromServerStatus(raw: unknown): ExecBadgeStatus {
  const n = normalizeRunStatus(raw)
  if (n === 'completed') return 'succeeded'
  if (n === 'failed') return 'failed'
  if (n === 'cancelled') return 'cancelled'
  if (n === 'running' || n === 'queued' || n === 'paused') return 'running'
  return 'unknown'
}

export function isTerminalBadge(s: ExecBadgeStatus): s is KnownRunOutcome {
  return s === 'succeeded' || s === 'failed' || s === 'cancelled'
}

type NodeStatus = 'idle' | 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled'

/**
 * Per-node statuses from journal events (`/runs/{id}` logs).
 * `order` maps backend `node_index` (execution order) → canvas node id for
 * events that lack `node_id`.
 */
export function statusesFromEvents(
  events: Array<Record<string, unknown>>,
  order: string[] | null,
): Map<string, NodeStatus> {
  const byId = new Map<string, NodeStatus>()
  for (const ev of events) {
    if (!ev || typeof ev !== 'object') continue
    const t = String(ev.type ?? ev.event ?? '')
    let st: NodeStatus | null = null
    if (t === 'node_start') st = 'running'
    else if (t === 'node_end' || t === 'node_complete') st = 'succeeded'
    else if (t === 'node_error') st = 'failed'
    else if (t === 'node_skip') st = 'skipped'
    else if (t === 'node_cancelled' || t === 'node_cancel') st = 'cancelled'
    if (!st) continue
    let nodeId = typeof ev.node_id === 'string' ? ev.node_id : undefined
    const idx = Number(ev.node_index)
    if (!nodeId && order && !Number.isNaN(idx)) nodeId = order[idx]
    if (!nodeId) continue
    // A terminal status never regresses to running (out-of-order journal rows).
    const prev = byId.get(nodeId)
    if (st === 'running' && prev && prev !== 'running') continue
    byId.set(nodeId, st)
  }
  return byId
}

/**
 * Final per-node statuses after a run reached (or was asked to reach) a
 * terminal state. Event-derived terminal statuses always win (a node the
 * journal says completed stays succeeded even if the run was cancelled).
 * Nodes with no terminal event:
 *  - run cancelled → started-but-unfinished 'cancelled'; never-started 'skipped' (not run)
 *  - run still live → keep 'running' / 'pending'
 *  - run failed → a started-but-unfinished node is 'failed'; never-started → 'skipped' (not run)
 *  - run succeeded / unknown → 'idle' (no claim we can't back up)
 */
export function reconcileNodeStatuses(
  nodeIds: string[],
  events: Array<Record<string, unknown>>,
  order: string[] | null,
  runStatus: ExecBadgeStatus,
): Map<string, NodeStatus> {
  const fromEvents = statusesFromEvents(events, order)
  const out = new Map<string, NodeStatus>()
  for (const id of nodeIds) {
    const ev = fromEvents.get(id)
    if (ev && ev !== 'running') {
      out.set(id, ev)
      continue
    }
    // Status unknown (network error / 404 / still loading): only report what
    // the journal itself says; never invent a status for the rest.
    if (!isTerminalBadge(runStatus) && runStatus !== 'running') {
      if (ev) out.set(id, ev)
      continue
    }
    if (runStatus === 'cancelled') out.set(id, ev === 'running' ? 'cancelled' : 'skipped')
    else if (runStatus === 'running') out.set(id, ev ?? 'pending')
    else if (ev === 'running' && runStatus === 'failed') out.set(id, 'failed')
    else if (runStatus === 'failed') out.set(id, 'skipped')
    else out.set(id, 'idle')
  }
  return out
}

/** Field-level defaults from a catalog entry's config schema. */
export function defaultsFromSchema(entry?: NodeCatalogEntry): Record<string, unknown> {
  const props = entry?.config_schema?.properties ?? {}
  const cfg: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(props)) {
    if (v && typeof v === 'object' && 'default' in v) cfg[k] = v.default
  }
  const nodeType = entry?.node_type || 'node'
  for (const key of ['output_dir', 'output_path'] as const) {
    if (key in props) {
      const current = cfg[key]
      if (current === undefined || current === null || current === '') {
        cfg[key] = `workspace/artifacts/builder/${nodeType}`
      }
    }
  }
  return cfg
}

export type DecoratableNodeData = {
  nodeType: string
  label: string
  category?: string
  runtime?: string
  config: Record<string, unknown>
  schemaProps?: Record<string, Record<string, unknown>>
  inputs: PortDef[]
  outputs: PortDef[]
  /** True once catalog data (category/schema/ports) has been applied. */
  catalogDecorated?: boolean
}

function mergePorts(catalog: PortDef[], existing: PortDef[], used: Set<string>, placeholder: string): PortDef[] {
  const out = [...catalog]
  for (const p of existing) {
    if (out.some((c) => c.name === p.name)) continue
    // Drop the "no catalog" placeholder port unless an edge actually uses it.
    if (p.name === placeholder && !used.has(p.name)) continue
    out.push(p)
  }
  return out
}

/**
 * Apply catalog data to a node that was built without it. User config wins
 * over schema defaults; an explicit label wins over the catalog label (the
 * humanized node-type fallback counts as "not explicit").
 */
export function decorateNodeData<T extends DecoratableNodeData>(
  data: T,
  entry: NodeCatalogEntry,
  usedInputs: Set<string> = new Set(),
  usedOutputs: Set<string> = new Set(),
): T {
  const ports = catalogPorts(entry)
  const labelIsDefault = !data.label || data.label === humanNodeLabel(data.nodeType) || data.label === 'node'
  return {
    ...data,
    label: labelIsDefault ? entry.label || data.label || humanNodeLabel(data.nodeType) : data.label,
    category: data.category ?? entry.category,
    runtime: data.runtime ?? entry.runtime,
    config: { ...defaultsFromSchema(entry), ...(data.config ?? {}) },
    schemaProps:
      data.schemaProps && Object.keys(data.schemaProps).length > 0
        ? data.schemaProps
        : (entry.config_schema?.properties ?? {}),
    inputs: mergePorts(ports.inputs, data.inputs ?? [], usedInputs, 'input'),
    outputs: mergePorts(ports.outputs, data.outputs ?? [], usedOutputs, 'output'),
    catalogDecorated: true,
  }
}

/**
 * Readable message for a non-OK run-start response. Handles FastAPI shapes:
 * `{detail: "..."}`, `{detail: {code, message}}`, `{error: {code, message}, detail}`.
 * Falls back to the already-parsed ApiError message.
 */
export function runStartErrorMessage(body: unknown, fallback: string): string {
  const pick = (v: unknown): string => {
    if (typeof v === 'string') return v.trim()
    if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>
      for (const k of ['message', 'detail', 'error'] as const) {
        const s = pick(o[k])
        if (s) return s
      }
    }
    return ''
  }
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>
    const msg = pick(b.detail) || pick(b.error) || pick(b.message)
    if (msg) {
      const code =
        b.detail && typeof b.detail === 'object' && typeof (b.detail as Record<string, unknown>).code === 'string'
          ? String((b.detail as Record<string, unknown>).code)
          : ''
      return code && !msg.toLowerCase().includes(code.toLowerCase()) ? `${msg} (${code})` : msg
    }
  }
  return fallback
}

/** Title for a non-OK run-start response. */
export function runStartErrorTitle(status: number): string {
  if (status === 503) return 'Run not started — server busy'
  if (status === 429) return 'Run not started — rate limited'
  if (status === 401 || status === 403) return 'Run not started — not authorized'
  if (status === 422 || status === 400) return 'Run not started — invalid graph'
  return 'Run not started'
}
