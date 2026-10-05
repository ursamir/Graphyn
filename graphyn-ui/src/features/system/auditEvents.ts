/**
 * Ops → Audit: pure helpers for audit event rows — what a resource id links
 * to (run / model / pipeline / proposal, always with the FULL id), friendly
 * action labels + tones for the run lifecycle (run.start / finish / fail /
 * cancel / archive / restore / purge / replay) and every other audited
 * action, actor display ("Unidentified (API)"), housekeeping filter
 * (notifications.*), short resource labels, and run-id search.
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
  /** Server read-time plain-words label ("Model registered"). */
  label?: string
  /** Server category: run | model | data | admin | system | ui. */
  category?: string
  /** true = named API token; false = self-declared / legacy. */
  actor_verified?: boolean
  /** Name the caller claimed (X-Actor) when it differs. */
  claimed_actor?: string | null
  /** http | internal. */
  origin?: string
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
  'model.register': 'Model registered',
  'model.promote': 'Model promoted',
  'model.promote_request': 'Model promotion requested',
  'pipeline.publish': 'Pipeline published',
  'pipeline.promote': 'Pipeline promoted',
  'pipeline.promote_request': 'Pipeline promotion requested',
  'pipeline.rollback': 'Pipeline rolled back',
  'proposal.create': 'Proposal created',
  'proposal.accept': 'Proposal accepted',
  'proposal.reject': 'Proposal rejected',
  'credential.create': 'Connection added',
  'credential.update': 'Connection updated',
  'credential.revoke': 'Connection revoked',
  'credential.delete': 'Connection deleted',
  'credential.bind_default': 'Default connection set',
  'schedule.create': 'Schedule created',
  'schedule.delete': 'Schedule deleted',
  'schedule.enable': 'Schedule enabled',
  'schedule.disable': 'Schedule disabled',
  'schedule.env': 'Schedule environment changed',
  'schedule.run': 'Schedule run now',
  'schedule.tick': 'Schedules checked',
  'ship.create': 'Ship package created',
  'ship.validate': 'Ship package validated',
  'ship.build': 'Ship package built',
  'ship.sign': 'Ship package signed',
  'ship.publish': 'Ship package published',
  'ship.deploy': 'Ship package deployed',
  'ship.supersede': 'Ship package superseded',
  'ship.fail': 'Ship package failed',
  'ship.promote': 'Ship package promoted',
  'webhook.set': 'Webhook saved',
  'webhook.test': 'Webhook tested',
  'webhook.received': 'Webhook delivery accepted',
  'webhook.rejected': 'Webhook delivery rejected',
  'hook.create': 'Inbound webhook created',
  'hook.update': 'Inbound webhook updated',
  'hook.delete': 'Inbound webhook removed',
  'hook.rotate': 'Inbound webhook secret rotated',
  'gate.decision': 'Approval decision',
  'worker.register': 'Worker registered',
  'template.save': 'Template saved',
  'dataset.version_delete': 'Dataset version deleted',
  'dataset.version_create': 'Dataset version written',
  'dataset.upload': 'Dataset files uploaded',
  'dataset.label_delete': 'Input dataset deleted',
  'dataset.snapshot': 'Input dataset frozen as version',
  'dataset.merge': 'Datasets merged',
  'dataset.download': 'Dataset downloaded',
  'dataset.ingest_start': 'Dataset import started',
  'dataset.ingest_finish': 'Dataset import finished',
  'dataset.link': 'Dataset linked to workspace',
  'dataset.unlink': 'Dataset unlinked from workspace',
  'workspace.created': 'Workspace created',
  'workspace.deleted': 'Workspace deleted',
  'workspace.renamed': 'Workspace id renamed (legacy)',
  'workspace.updated': 'Workspace details updated',
  'workspace.status_changed': 'Workspace status changed',
  'workspace.archived': 'Workspace archived',
  'workspace.unarchived': 'Workspace unarchived',
  'workspace.cloned': 'Workspace cloned',
  'workspace.spec_updated': 'Workspace spec updated',
  'workspace.taxonomy_updated': 'Workspace taxonomy updated',
  'workspace.contract_updated': 'Workspace contract updated',
  'workspace.snapshot_created': 'Workspace snapshot created',
  'workspace.snapshot_restored': 'Workspace snapshot restored',
  'workspace.version_restored': 'Dataset version restored into workspace',
  'system.cleanup': 'Old runs cleaned up',
  'ops.shutdown_drain': 'Server drain started',
  'notifications.mark_read': 'Notifications marked read',
}

const RESOURCE_NOUNS: Record<string, string> = {
  run: 'Run',
  model: 'Model',
  pipeline: 'Pipeline',
  proposal: 'Proposal',
  credential: 'Connection',
  schedule: 'Schedule',
  ship: 'Ship package',
  webhook: 'Webhook',
  worker: 'Worker',
  template: 'Template',
  dataset: 'Dataset',
  project: 'Workspace',
  workspace: 'Workspace',
  plugin: 'Plugin',
  notifications: 'Notifications',
  notification: 'Notification',
  system: 'System',
  ops: 'Server',
}

const IRREGULAR_PAST: Record<string, string> = {
  run: 'run',
  set: 'set',
  reset: 'reset',
  read: 'read',
  build: 'built',
  send: 'sent',
  begin: 'begun',
  stop: 'stopped',
  drop: 'dropped',
}

function pastTense(verb: string): string {
  const v = verb.toLowerCase()
  if (IRREGULAR_PAST[v]) return IRREGULAR_PAST[v]
  if (v.endsWith('ed')) return v
  if (v.endsWith('e')) return `${v}d`
  if (/[^aeiou]y$/.test(v)) return `${v.slice(0, -1)}ied`
  return `${v}ed`
}

/**
 * Plain-words label for every audit action: known actions from the table,
 * otherwise "<Resource> <verb>ed" ("plugin.install" → "Plugin installed",
 * "dataset.label_delete" → "Dataset label deleted").
 */
export function auditActionLabel(action: string | undefined): string {
  const a = s(action)
  if (!a) return 'Unknown action'
  const key = a.toLowerCase()
  if (ACTION_LABELS[key]) return ACTION_LABELS[key]
  const dot = key.indexOf('.')
  if (dot <= 0) return a
  const res = key.slice(0, dot)
  const words = key.slice(dot + 1).split(/[._-]+/).filter(Boolean)
  if (!words.length) return a
  const noun = RESOURCE_NOUNS[res] ?? res.charAt(0).toUpperCase() + res.slice(1).replace(/_/g, ' ')
  const verb = pastTense(words[words.length - 1])
  return [noun, ...words.slice(0, -1), verb].join(' ')
}

/** Housekeeping events (hidden unless "Show system events" is on). */
export function isSystemAuditEvent(ev: AuditEvent): boolean {
  const a = s(ev.action).toLowerCase()
  return a.startsWith('notifications.') || a.startsWith('notification.')
}

const UNIDENTIFIED_ACTORS = new Set(['', 'api', 'anonymous', 'unknown', 'system'])

/**
 * Who did it: a named actor, or "Unidentified (API)" (muted) when the request
 * carried no actor ("api" / empty, usually with actor_kind "system").
 */
export function auditActorDisplay(ev: AuditEvent): { label: string; muted: boolean; detail: string } {
  const actor = s(ev.actor)
  const kind = s(ev.actor_kind)
  if (UNIDENTIFIED_ACTORS.has(actor.toLowerCase())) {
    return {
      label: 'Unidentified (API)',
      muted: true,
      detail: [actor, kind].filter(Boolean).join(' · ') || 'no actor recorded',
    }
  }
  return { label: actor, muted: false, detail: kind && kind.toLowerCase() !== 'user' ? kind : '' }
}

/** Short, readable text for the event's resource (full id stays in the tooltip). */
export function auditResourceLabel(ev: AuditEvent): string {
  const id = s(ev.resource_id)
  if (!id) return ''
  const target = auditTarget(ev)
  if (target?.kind === 'run') return id.length > 12 ? id.slice(0, 8) : id
  if (target?.kind === 'proposal') return id.length > 12 ? id.slice(0, 8) : id
  if (target?.kind === 'model') return id
  if (target?.kind === 'pipeline') return target.version ? `${target.name}@${target.version}` : target.name
  // Long opaque ids (uuid / hex) → first 8 chars; names stay readable.
  if (/^[0-9a-f-]{16,}$/i.test(id)) return id.slice(0, 8)
  return id.length > 40 ? `${id.slice(0, 37)}…` : id
}

export type AuditTone = 'success' | 'danger' | 'warning' | 'neutral' | 'info'

export function auditActionTone(action: string | undefined, result?: string): AuditTone {
  const a = s(action).toLowerCase()
  const r = s(result).toLowerCase()
  if (r === 'failure' || r === 'failed' || r === 'error' || r === 'denied' || r === 'forbidden') return 'danger'
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

// ── Categories (server `category`, client fallback mirrors app/core/trust/audit.py) ──

export const AUDIT_CATEGORIES = ['run', 'model', 'data', 'admin', 'system', 'ui'] as const
export type AuditCategory = (typeof AUDIT_CATEGORIES)[number]

export const AUDIT_CATEGORY_LABEL: Record<AuditCategory, string> = {
  run: 'Runs',
  model: 'Models',
  data: 'Data',
  admin: 'Admin',
  system: 'System',
  ui: 'UI',
}

/** Shown by default; UI (notifications read …) and System (schedule ticks, workers) are hidden. */
export const DEFAULT_AUDIT_CATEGORIES: ReadonlySet<AuditCategory> = new Set<AuditCategory>(['run', 'model', 'data', 'admin'])

const CATEGORY_BY_PREFIX: Record<string, AuditCategory> = {
  run: 'run',
  model: 'model',
  ship: 'model',
  notifications: 'ui',
  notification: 'ui',
  ui: 'ui',
  system: 'admin',
  ops: 'system',
  worker: 'system',
  webhook: 'admin',
  schedule: 'admin',
  credential: 'admin',
  plugin: 'admin',
  pipeline: 'admin',
  template: 'admin',
  proposal: 'admin',
  dataset: 'data',
  workspace: 'admin',
  hook: 'admin',
  gate: 'run',
}

function isCategory(v: string): v is AuditCategory {
  return (AUDIT_CATEGORIES as readonly string[]).includes(v)
}

/** Server `category`, else derived from the action like the API does. */
export function auditCategory(ev: AuditEvent): AuditCategory {
  const c = s(ev.category).toLowerCase()
  if (isCategory(c)) return c
  const a = s(ev.action).toLowerCase()
  if (a === 'schedule.tick') return 'system'
  return CATEGORY_BY_PREFIX[a.split('.')[0]] ?? 'system'
}

/** Server `label` when present, else the client table (`auditActionLabel`). */
export function auditEventLabel(ev: AuditEvent): string {
  const base = s(ev.label) || auditActionLabel(ev.action)
  const outcome = auditFailureWord(ev.result)
  if (!outcome) return base
  // "dataset.upload" + failure → "Dataset upload failed" (not "Dataset uploaded").
  const key = s(ev.action).toLowerCase()
  const dot = key.indexOf('.')
  if (dot > 0) {
    const res = key.slice(0, dot)
    const words = key.slice(dot + 1).split(/[._-]+/).filter(Boolean)
    if (words.length) {
      const noun = RESOURCE_NOUNS[res] ?? res.charAt(0).toUpperCase() + res.slice(1).replace(/_/g, ' ')
      return [noun, ...words, outcome].join(' ')
    }
  }
  return `${base} — ${outcome}`
}

/** "failed" / "denied" for a non-success audit `result` ('' for success / unknown). */
export function auditFailureWord(result: string | undefined): string {
  const r = s(result).toLowerCase()
  if (r === 'failure' || r === 'failed' || r === 'error') return 'failed'
  if (r === 'denied' || r === 'forbidden') return 'denied'
  return ''
}

/** `GET /audit` filter for the chosen categories: `{exclude_category: "system,ui"}`, or {} for all. */
export function auditCategoryQuery(selected: ReadonlySet<string>): { exclude_category?: string } {
  const hidden = AUDIT_CATEGORIES.filter((c) => !selected.has(c))
  if (hidden.length === 0) return {}
  return { exclude_category: hidden.join(',') }
}
