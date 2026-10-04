/**
 * Ops → Audit: pure helpers for audit event rows — what a resource id links
 * to (run / model / pipeline / proposal, always with the FULL id), friendly
 * action labels + tones for the run lifecycle (run.start / finish / fail /
 * cancel / archive / restore / purge / replay), and run-id search.
 * Unit-tested (auditEvents.test.ts).
 */

export type AuditEvent = {
  event_id?: string
  ts?: string
  timestamp?: string
  actor?: string
  actor_kind?: string
  action?: string
  resource_type?: string
  resource_id?: string
  result?: string
  metadata?: Record<string, unknown> | null
  meta?: Record<string, unknown> | null
}

export type AuditTarget =
  | { kind: 'run'; runId: string; project: string }
  | { kind: 'model'; name: string; project: string }
  | { kind: 'pipeline'; project: string; name: string; version: string }
  | { kind: 'proposal'; id: string }

function metaOf(ev: AuditEvent): Record<string, unknown> {
  const m = ev.metadata ?? ev.meta
  return m && typeof m === 'object' && !Array.isArray(m) ? m : {}
}

function s(v: unknown): string {
  return typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : ''
}

/** Link target for the event's resource (null when it is not navigable). */
export function auditTarget(ev: AuditEvent): AuditTarget | null {
  const type = s(ev.resource_type).toLowerCase()
  const id = s(ev.resource_id)
  const meta = metaOf(ev)
  const project = s(meta.project)
  if (!id) return null
  if (type === 'run') return { kind: 'run', runId: id, project }
  if (type === 'model') {
    // "speech-commands@staging" | "speech-commands->prod" | "speech-commands"
    const name = id.split(/@|->/)[0].trim()
    return name ? { kind: 'model', name, project } : null
  }
  if (type === 'pipeline') {
    // "<project>/<name>@<version>"
    const m = id.match(/^([^/]+)\/([^@]+)(?:@(.+))?$/)
    if (m) return { kind: 'pipeline', project: m[1], name: m[2], version: m[3] || '' }
    return project ? { kind: 'pipeline', project, name: id.split('@')[0], version: id.split('@')[1] || '' } : null
  }
  if (type === 'proposal') return { kind: 'proposal', id }
  return null
}

/** A run this event is about besides its resource (e.g. model.register → meta.run_id). */
export function relatedRunId(ev: AuditEvent): string {
  const meta = metaOf(ev)
  const rid = s(meta.run_id) || s(meta.source_run_id) || s(meta.replay_of)
  if (!rid) return ''
  if (s(ev.resource_type).toLowerCase() === 'run' && rid === s(ev.resource_id)) return ''
  return rid
}

const ACTION_LABELS: Record<string, string> = {
  'run.start': 'Run started',
  'run.finish': 'Run finished',
  'run.fail': 'Run failed',
  'run.cancel': 'Run cancelled',
  'run.archive': 'Run archived',
  'run.restore': 'Run restored',
  'run.purge': 'Run deleted permanently',
  'run.replay': 'Run replayed',
  'run.promote': 'Run outputs promoted',
}

export function auditActionLabel(action: string | undefined): string {
  const a = s(action)
  if (!a) return 'unknown'
  return ACTION_LABELS[a.toLowerCase()] || a
}

export type AuditTone = 'success' | 'danger' | 'warning' | 'neutral' | 'info'

export function auditActionTone(action: string | undefined, result?: string): AuditTone {
  const a = s(action).toLowerCase()
  const r = s(result).toLowerCase()
  if (r === 'failure' || r === 'denied') return 'danger'
  if (/\.(fail|purge|delete|reject)$/.test(a) || a.endsWith('_delete')) return 'danger'
  if (/\.(cancel|archive|disable|shutdown_drain)$/.test(a)) return 'warning'
  if (/\.(finish|accept|register|promote|restore|publish)$/.test(a)) return 'success'
  if (/\.(start|replay|create|run)$/.test(a)) return 'info'
  return 'neutral'
}

/**
 * Search box: run id (full or ≥ 4-char prefix), resource id, action or actor.
 * Matches the resource id and any related run id in metadata.
 */
export function auditMatchesQuery(ev: AuditEvent, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const meta = metaOf(ev)
  const hay = [
    ev.resource_id,
    ev.resource_type,
    ev.action,
    auditActionLabel(ev.action),
    ev.actor,
    meta.run_id,
    meta.replay_of,
    meta.graph_name,
    meta.project,
  ]
    .map((v) => s(v).toLowerCase())
    .filter(Boolean)
  return hay.some((h) => h.includes(q))
}

/** Next page size for "Load more" (API caps `limit` at 1000). */
export function nextAuditLimit(current: number, step = 100, max = 1000): number {
  return Math.min(max, Math.max(step, current + step))
}
