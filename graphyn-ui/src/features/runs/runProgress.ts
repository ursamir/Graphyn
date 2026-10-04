/**
 * `node_progress` events (UX API contract §7) — pure helpers shared by the
 * Editor execution log, the Editor canvas progress bar, and Runs → Logs.
 *
 * Event: {type:"node_progress", node_id, node_type, ts, phase, epoch, epochs,
 *         loss, accuracy, val_loss, val_accuracy, pct, message}
 *
 * Pretty logs collapse repeated progress of one node into its latest line
 * (with a history for a sparkline); raw logs keep every event.
 */
import { formatMetric, formatMetricValue } from '../../lib/metrics'
import { humanNodeLabel } from '../../lib/format'

type Rec = Record<string, unknown>

export type NodeProgress = {
  nodeId: string
  nodeType?: string
  phase?: string
  epoch: number | null
  epochs: number | null
  loss: number | null
  accuracy: number | null
  valLoss: number | null
  valAccuracy: number | null
  /** 0..100 */
  pct: number | null
  message?: string
  ts?: string
}

function num(v: unknown): number | null {
  const n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

/** Parse a journal row / stream line (object or JSON string) into an event object. */
export function eventObject(row: unknown): Rec | null {
  if (typeof row === 'string') {
    const t = row.trim()
    if (!t.startsWith('{')) return null
    try {
      const v = JSON.parse(t) as unknown
      return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
    } catch {
      return null
    }
  }
  if (!row || typeof row !== 'object' || Array.isArray(row)) return null
  const o = row as Rec
  if (typeof o.message === 'string' && o.message.trim().startsWith('{') && !o.type) {
    const inner = eventObject(o.message)
    if (inner) return { ...o, ...inner }
  }
  return o
}

export function isProgressEvent(ev: Rec | null | undefined): boolean {
  return Boolean(ev) && String(ev!.type ?? ev!.event ?? '') === 'node_progress'
}

/** node_progress event → NodeProgress (null for other events). */
export function parseProgress(row: unknown): NodeProgress | null {
  const ev = eventObject(row)
  if (!ev || !isProgressEvent(ev)) return null
  const nodeId = str(ev.node_id)
  if (!nodeId) return null
  const epoch = num(ev.epoch)
  const epochs = num(ev.epochs ?? ev.total_epochs)
  let pct = num(ev.pct ?? ev.progress)
  if (pct != null && pct <= 1 && pct > 0 && num(ev.pct) == null) pct *= 100 // `progress` as 0..1
  if (pct == null && epoch != null && epochs) pct = (epoch / epochs) * 100
  if (pct != null) pct = Math.max(0, Math.min(100, pct))
  return {
    nodeId,
    nodeType: str(ev.node_type) || undefined,
    phase: str(ev.phase) || undefined,
    epoch,
    epochs,
    loss: num(ev.loss),
    accuracy: num(ev.accuracy ?? ev.acc),
    valLoss: num(ev.val_loss),
    valAccuracy: num(ev.val_accuracy ?? ev.val_acc),
    pct,
    message: str(ev.message) || undefined,
    ts: str(ev.ts) || str(ev.timestamp) || undefined,
  }
}

/** "Trainer · epoch 3/30 · loss 0.41 · val acc 0.78". */
export function formatProgressLine(p: NodeProgress, label?: string): string {
  const who = label || humanNodeLabel(p.nodeType || p.nodeId)
  const bits: string[] = [who]
  if (p.epoch != null) bits.push(p.epochs ? `epoch ${p.epoch}/${p.epochs}` : `epoch ${p.epoch}`)
  else if (p.phase) bits.push(p.phase)
  if (p.loss != null) bits.push(`loss ${formatMetric(p.loss)}`)
  if (p.valAccuracy != null) bits.push(`val acc ${formatMetricValue('val_accuracy', p.valAccuracy)}`)
  else if (p.accuracy != null) bits.push(`acc ${formatMetricValue('accuracy', p.accuracy)}`)
  if (bits.length === 1) {
    if (p.message) return p.message
    if (p.pct != null) bits.push(`${Math.round(p.pct)}%`)
  }
  return bits.join(' · ')
}

/** Short tail for a canvas node: "3/30 · val acc 0.78". */
export function progressBadgeText(p: NodeProgress): string {
  const bits: string[] = []
  if (p.epoch != null) bits.push(p.epochs ? `epoch ${p.epoch}/${p.epochs}` : `epoch ${p.epoch}`)
  else if (p.pct != null) bits.push(`${Math.round(p.pct)}%`)
  if (p.valAccuracy != null) bits.push(`val acc ${formatMetricValue('val_accuracy', p.valAccuracy)}`)
  else if (p.loss != null) bits.push(`loss ${formatMetric(p.loss)}`)
  return bits.join(' · ')
}

/** Latest progress per node from a list of rows (events or log entries). */
export function latestProgressByNode(rows: unknown[]): Map<string, NodeProgress> {
  const out = new Map<string, NodeProgress>()
  for (const r of rows) {
    const p = parseProgress(r)
    if (p) out.set(p.nodeId, p)
  }
  return out
}

/** Node ids whose run finished (node_end / node_error / node_skip) — their bar should go. */
export function finishedNodeIds(rows: unknown[]): Set<string> {
  const out = new Set<string>()
  for (const r of rows) {
    const ev = eventObject(r)
    if (!ev) continue
    const t = String(ev.type ?? ev.event ?? '')
    if (t === 'node_end' || t === 'node_complete' || t === 'node_error' || t === 'node_skip') {
      const id = str(ev.node_id)
      if (id) out.add(id)
    }
  }
  return out
}

export type CollapsedRow<T> =
  | { kind: 'row'; row: T }
  | { kind: 'progress'; row: T; progress: NodeProgress; history: NodeProgress[]; count: number }

/**
 * Pretty-view collapse: every node's progress events become ONE entry (at the
 * position of its first progress event) holding the latest values + history.
 * Non-progress rows pass through unchanged and in order.
 */
export function collapseProgressRows<T>(rows: T[], rawOf: (row: T) => unknown): CollapsedRow<T>[] {
  const out: CollapsedRow<T>[] = []
  const slot = new Map<string, number>()
  for (const row of rows) {
    const p = parseProgress(rawOf(row))
    if (!p) {
      out.push({ kind: 'row', row })
      continue
    }
    const at = slot.get(p.nodeId)
    if (at == null) {
      slot.set(p.nodeId, out.length)
      out.push({ kind: 'progress', row, progress: p, history: [p], count: 1 })
    } else {
      const prev = out[at] as Extract<CollapsedRow<T>, { kind: 'progress' }>
      out[at] = { kind: 'progress', row, progress: p, history: [...prev.history, p], count: prev.count + 1 }
    }
  }
  return out
}

/** Series for a sparkline: val accuracy when present, else accuracy, else loss. */
export function progressSeries(history: NodeProgress[]): { name: string; values: number[] } | null {
  const pick = (name: string, get: (p: NodeProgress) => number | null) => {
    const values = history.map(get).filter((v): v is number => v != null)
    return values.length >= 2 ? { name, values } : null
  }
  return (
    pick('val acc', (p) => p.valAccuracy) ||
    pick('acc', (p) => p.accuracy) ||
    pick('loss', (p) => p.loss)
  )
}

/** SVG polyline points for values in a w×h box. */
export function sparklinePoints(values: number[], w: number, h: number): string {
  if (values.length < 2) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w
      const y = h - ((v - min) / span) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export type RunningNode = { id: string; label: string }

/**
 * Nodes currently executing in a live run — from the per-node statuses
 * (journal `node_start` without `node_end`/`node_error`, else node_stats).
 * Parallel paths can have several. The backend `current_node` is only a
 * fallback (it can lag behind and name the last *finished* node), and is
 * ignored once that node is known to be finished. `pathOf` adds "· Path C"
 * when the label does not already name the path.
 */
export function runningNodesOf(
  items: Array<{ id: string; label: string; status?: string }>,
  opts: { currentNode?: unknown; pathOf?: (id: string) => string | null | undefined } = {},
): RunningNode[] {
  const withPath = (id: string, label: string): string => {
    const p = opts.pathOf?.(id)
    return p && !label.includes(p) ? `${label} · ${p}` : label
  }
  const running = items.filter((i) => i.status === 'running')
  if (running.length > 0) return running.map((i) => ({ id: i.id, label: withPath(i.id, i.label) }))
  const cur = typeof opts.currentNode === 'string' ? opts.currentNode.trim() : ''
  if (!cur) return []
  const hit = items.find((i) => i.id === cur)
  if (hit && hit.status && hit.status !== 'pending') return []
  return [{ id: cur, label: withPath(cur, hit?.label || humanNodeLabel(cur)) }]
}
