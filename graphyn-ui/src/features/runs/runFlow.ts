/**
 * Workflow-aware helpers for run views and the editor canvas — pure,
 * unit-tested (runFlow.test.ts):
 *
 *  - `isMlMultiPath` / `graphHasMlPaths`: only an ML-style multi-path graph
 *    (≥2 branches that each train / evaluate, or ≥2 paths carrying metrics)
 *    gets "Path A…" grouping, the Paths compared table and canvas path badges.
 *    Workflows (if_switch / hitl_approve / error-routed branches) read as one
 *    ordered step list instead.
 *  - `stepDisplayNames`: IR label → node id (several nodes share a type) →
 *    catalog type label, with the type as secondary text.
 *  - `skipReasonText` / `skipReasonsByNode`: node_skip `reason` in plain words.
 *  - `branchContextByNode`: "check → true", "gate → approved", "bad_call → error".
 *  - `handledErrorNodes` / `splitRunErrors`: routed / continued failures are
 *    handled errors (amber), not run errors (red).
 */
import { isMultiTrackShape, type PipelineShape } from './runNodes'
import type { PathResult } from './runResults'
import type { StepResilience } from './runWorkflow'

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '')

/** Parse a journal row whose `message` is itself a JSON event. */
function eventOf(row: unknown): Rec | null {
  const r = rec(row)
  if (!r) return null
  if (typeof r.message === 'string' && r.message.trim().startsWith('{')) {
    try {
      const inner = rec(JSON.parse(r.message))
      if (inner) return { ...r, ...inner }
    } catch {
      /* plain text */
    }
  }
  return r
}

// ── ML multi-path detection ─────────────────────────────────────────────

/** Node types that make a branch an ML "path" (train / evaluate a model). */
export const ML_STEP_RE = /(train|evaluat|model_builder|fine_?tune)/i

function branchHasMlStep(branch: string[], nodeTypeOf: (id: string) => string | null | undefined): boolean {
  return branch.some((id) => ML_STEP_RE.test(`${nodeTypeOf(id) || ''}`))
}

/** Graph-only rule (editor canvas, live runs): ≥2 branches each with a train / evaluate step. */
export function graphHasMlPaths(
  shape: Pick<PipelineShape, 'kind' | 'branches'> | null | undefined,
  nodeTypeOf: (id: string) => string | null | undefined,
): boolean {
  if (!shape || !isMultiTrackShape(shape as PipelineShape)) return false
  return shape.branches.filter((b) => branchHasMlStep(b, nodeTypeOf)).length >= 2
}

/**
 * Run rule: fork/parallel shape AND (≥2 paths carrying metrics, or the graph
 * rule). A workflow fan-out (if_switch / hitl_approve / error branch) has
 * neither, so it never shows Path A…F chrome.
 */
export function isMlMultiPath(input: {
  shape: Pick<PipelineShape, 'kind' | 'branches'> | null | undefined
  paths?: Array<Pick<PathResult, 'metrics' | 'primary' | 'metricsNodeId'>> | null
  nodeTypeOf: (id: string) => string | null | undefined
}): boolean {
  if (!input.shape || !isMultiTrackShape(input.shape as PipelineShape)) return false
  const scored = (input.paths || []).filter(
    (p) => p && (p.primary || Object.keys(p.metrics || {}).length > 0 || p.metricsNodeId),
  )
  if (scored.length >= 2) return true
  return graphHasMlPaths(input.shape, input.nodeTypeOf)
}

/** "Http request · Path C" / "Trainer · Path B (MobileNet)" → "Http request" (non-ML views). */
export function stripPathSuffix(label: string): string {
  return label.replace(/\s·\sPath [A-Z](\s*\([^()]*\))?\s*$/, '').trim() || label
}

// ── Step names ──────────────────────────────────────────────────────────

export type StepName = {
  /** Title line: IR label, else node id (shared type), else type label. */
  title: string
  /** Secondary text: type label (or the node id when the title is the type). '' when redundant. */
  subtitle: string
}

/** True when an id is just the type with an instance suffix ("set_map_2", "trainer_b66a5330"). */
function idIsTypeLike(id: string, nodeType: string): boolean {
  const i = id.toLowerCase()
  const t = nodeType.toLowerCase()
  if (!t) return false
  return i === t || i.startsWith(`${t}_`)
}

/**
 * Display name per node. `typeLabelOf` should return the plugin catalog label
 * ("IF Switch", "HTTP Request"); a label equal to the type / its catalog label
 * counts as "no label".
 */
export function stepDisplayNames(
  nodes: Array<{ id?: unknown; node_type?: unknown; label?: unknown }> | null | undefined,
  typeLabelOf: (nodeType: string) => string,
): Map<string, StepName> {
  const list = (nodes || [])
    .map((n) => ({ id: str(n?.id), nodeType: str(n?.node_type), label: str(n?.label) }))
    .filter((n) => n.id)
  const typeCount = new Map<string, number>()
  for (const n of list) typeCount.set(n.nodeType, (typeCount.get(n.nodeType) ?? 0) + 1)
  const out = new Map<string, StepName>()
  for (const n of list) {
    const typeLabel = n.nodeType ? typeLabelOf(n.nodeType) || n.nodeType : n.id
    const custom =
      n.label &&
      n.label !== n.nodeType &&
      n.label.toLowerCase() !== typeLabel.toLowerCase() &&
      !(typeCount.get(n.nodeType)! > 1 && list.filter((m) => m.nodeType === n.nodeType && m.label === n.label).length > 1)
    if (custom) {
      out.set(n.id, { title: n.label, subtitle: typeLabel })
    } else if ((typeCount.get(n.nodeType) ?? 0) > 1) {
      out.set(n.id, { title: n.id, subtitle: typeLabel })
    } else {
      out.set(n.id, { title: typeLabel, subtitle: idIsTypeLike(n.id, n.nodeType) ? '' : n.id })
    }
  }
  return out
}

// ── Skip reasons ────────────────────────────────────────────────────────

/** node_skip `reason` → plain words. */
export function skipReasonText(reason: unknown): string {
  const r = str(reason).toLowerCase()
  if (!r) return 'not run'
  if (r === 'upstream_skipped' || r === 'all_inputs_unproduced' || r === 'branch_not_taken') return 'branch not taken'
  if (r === 'condition_false') return 'condition false'
  if (r === 'resumed_from_checkpoint') return 'reused from checkpoint'
  if (r === 'excluded_from_partial_execution') return 'not part of this partial run'
  if (r === 'cancelled' || r === 'run_cancelled') return 'run cancelled'
  return r.replace(/_/g, ' ')
}

/** node id → raw skip reason, from the run's node_skip events (last wins). */
export function skipReasonsByNode(events: unknown): Map<string, string> {
  const out = new Map<string, string>()
  if (!Array.isArray(events)) return out
  for (const row of events) {
    const ev = eventOf(row)
    if (!ev) continue
    if ((str(ev.type) || str(ev.event)) !== 'node_skip') continue
    const id = str(ev.node_id)
    if (id) out.set(id, str(ev.reason))
  }
  return out
}

// ── Branch context ──────────────────────────────────────────────────────

type EdgeLike = { src_id?: unknown; src_port?: unknown; dst_id?: unknown; dst_port?: unknown }

/** Node types whose output ports are alternative branches. */
export const BRANCHING_TYPE_RE = /(switch|approve|router|branch|condition|gate)/i

/**
 * node id → "check → true" when the node hangs off a branching output: a
 * branching node (if_switch, hitl_approve, a node with on_error route — see
 * `branchingNodes`) sending ≥2 ports to different nodes, or a routed error
 * port. `nameOf` names the source (default: its id).
 */
export function branchContextByNode(
  edges: EdgeLike[] | null | undefined,
  opts: { branchingNodes?: Set<string>; errorPorts?: Map<string, string>; nameOf?: (id: string) => string } = {},
): Map<string, string> {
  const list = (edges || [])
    .map((e) => ({ src: str(e?.src_id), port: str(e?.src_port), dst: str(e?.dst_id) }))
    .filter((e) => e.src && e.dst && e.port)
  const portsBySrc = new Map<string, Set<string>>()
  for (const e of list) {
    const s = portsBySrc.get(e.src) ?? new Set<string>()
    s.add(e.port)
    portsBySrc.set(e.src, s)
  }
  const out = new Map<string, string>()
  const nameOf = opts.nameOf ?? ((id: string) => id)
  for (const e of list) {
    const isErr = e.port === (opts.errorPorts?.get(e.src) ?? 'error')
    const fan = (portsBySrc.get(e.src)?.size ?? 0) >= 2 && (!opts.branchingNodes || opts.branchingNodes.has(e.src))
    if (!(isErr || fan) || out.has(e.dst)) continue
    out.set(e.dst, `${nameOf(e.src)} → ${e.port}`)
  }
  return out
}

/** Graph nodes that branch: type matches BRANCHING_TYPE_RE, or IR on_error mode "route". */
export function branchingNodesOf(
  nodes: Array<{ id?: unknown; node_type?: unknown; on_error?: unknown }> | null | undefined,
): { branching: Set<string>; errorPorts: Map<string, string> } {
  const branching = new Set<string>()
  const errorPorts = new Map<string, string>()
  for (const n of nodes || []) {
    const id = str(n?.id)
    if (!id) continue
    const oe = rec(n?.on_error)
    if (oe && str(oe.mode) === 'route') {
      branching.add(id)
      errorPorts.set(id, str(oe.port) || 'error')
    }
    if (BRANCHING_TYPE_RE.test(str(n?.node_type))) branching.add(id)
  }
  return { branching, errorPorts }
}

// ── Handled errors ──────────────────────────────────────────────────────

/** Steps whose failure was routed to an error branch or continued (on_error). */
export function handledErrorNodes(resilience: Map<string, StepResilience> | null | undefined): Set<string> {
  const out = new Set<string>()
  for (const [id, r] of resilience || []) if (r.routed || r.continued) out.add(id)
  return out
}

/** "Failed → routed to error branch" / "Failed → run continued" ('' when not handled). */
export function handledErrorText(r: StepResilience | null | undefined): string {
  if (!r) return ''
  if (r.routed) return `Failed → routed to ${r.routed.port === 'error' ? 'error' : `“${r.routed.port}”`} branch`
  if (r.continued) return 'Failed → run continued'
  return ''
}

/** True when one error log row belongs to a handled failure. */
export function isHandledErrorRow(row: unknown, handled: Set<string>): boolean {
  const ev = eventOf(row)
  if (!ev) return false
  const t = str(ev.type) || str(ev.event)
  if (t === 'node_error_routed' || t === 'node_failed_continued' || t === 'node_retry') return true
  const id = str(ev.node_id)
  if (id && handled.has(id)) return true
  const msg = str(ev.message)
  return /failure routed to port|on_error\s*=\s*continue/i.test(msg)
}

export type RunErrorSplit = {
  /** Errors that failed something (red). */
  unhandledCount: number
  unhandledRecent: Rec[]
  /** Failures routed / continued (amber) — counted per step. */
  handledCount: number
  handledRecent: Rec[]
}

/**
 * Split the debug report's error log lines into unhandled vs handled. The
 * report counts every ERROR / "error" line, so lines of handled steps are
 * subtracted from `errorCount`.
 */
export function splitRunErrors(input: {
  errorCount?: number | null
  recentErrors?: Array<Record<string, unknown>> | null
  handled: Set<string>
}): RunErrorSplit {
  const recent = Array.isArray(input.recentErrors) ? input.recentErrors : []
  const handledRecent: Rec[] = []
  const unhandledRecent: Rec[] = []
  for (const r of recent) (isHandledErrorRow(r, input.handled) ? handledRecent : unhandledRecent).push(r)
  const total = typeof input.errorCount === 'number' && Number.isFinite(input.errorCount) ? input.errorCount : null
  const unhandledCount = total != null ? Math.max(0, total - handledRecent.length) : unhandledRecent.length
  return {
    unhandledCount,
    unhandledRecent,
    handledCount: input.handled.size,
    handledRecent,
  }
}

/** "1 handled error" / "2 handled errors". */
export function handledErrorsLabel(n: number): string {
  return `${n} handled error${n === 1 ? '' : 's'}`
}
