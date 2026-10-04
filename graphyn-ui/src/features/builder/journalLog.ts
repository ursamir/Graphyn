/**
 * Editor execution log from a run's journal (GET /runs/{id} `logs`), formatted
 * like the live NDJSON stream so opening a graph with a linked run shows what
 * happened instead of "No events yet". Pure — unit-tested.
 */
import { formatExecutionLine, humanNodeLabel } from '../../lib/format'
import { formatProgressLine, parseProgress } from '../runs/runProgress'
import { compactNodeLabel } from '../runs/runRecord'

export type LogEntry = { message: string; level: string; ts: string; raw?: string }

/**
 * "Trainer · started" → "Trainer · Path B · started" when the node's display
 * label (path-disambiguated) differs from the generic type label.
 */
export function relabelLine(
  text: string,
  ev: Record<string, unknown>,
  labelFor?: (nodeId: string) => string | undefined,
): string {
  const id = typeof ev.node_id === 'string' ? ev.node_id : ''
  // Backend path-aware label wins ("Trainer · Path C (MobileNet · lr 0.002)" →
  // "Trainer · Path C" in the line; the description stays in the run record).
  const backend = typeof ev.node_label === 'string' ? compactNodeLabel(ev.node_label.trim()) : ''
  if (!backend && (!id || !labelFor)) return text
  const label = backend || (id && labelFor ? labelFor(id) : undefined)
  if (!label) return text
  for (const base of [humanNodeLabel(String(ev.node_type || '')), humanNodeLabel(id)]) {
    if (base && base !== label && text.startsWith(`${base} · `) && !text.startsWith(label)) {
      return `${label}${text.slice(base.length)}`
    }
  }
  return text
}

export function journalToLogEntries(
  events: Array<Record<string, unknown>>,
  opts: { labelFor?: (nodeId: string) => string | undefined; limit?: number } = {},
): LogEntry[] {
  const out: LogEntry[] = []
  let hadError = false
  for (const ev of events) {
    if (!ev || typeof ev !== 'object') continue
    const t = String(ev.type ?? ev.event ?? '')
    const ts = String(ev.timestamp ?? ev.time ?? ev.ts ?? '') || new Date(0).toISOString()
    const raw = JSON.stringify(ev)
    // Terminal error restating a node_error the log already shows.
    if (t === 'error' && ev.already_reported === true) continue
    const prog = parseProgress(ev)
    if (prog) {
      const backendLabel = typeof ev.node_label === 'string' ? compactNodeLabel(ev.node_label) : ''
      out.push({
        message: formatProgressLine(prog, backendLabel || opts.labelFor?.(prog.nodeId)),
        level: 'progress',
        ts,
        raw,
      })
      continue
    }
    if (t === 'node_error' || t === 'error') hadError = true
    const src = !t && typeof ev.message === 'string' ? ev.message : raw
    let formatted = formatExecutionLine(src)
    if ((t === 'done' || t === 'pipeline_done') && hadError) {
      formatted = { text: 'Pipeline finished with errors', level: 'error', raw }
    }
    const lvl = String(ev.level ?? '').toUpperCase()
    const level = lvl === 'ERROR' || formatted.level.includes('error') ? 'error' : formatted.level
    if (!formatted.text) continue
    out.push({ message: relabelLine(formatted.text, ev, opts.labelFor), level, ts, raw })
  }
  const limit = opts.limit ?? 500
  return out.length > limit ? out.slice(-limit) : out
}
