import { humanizeTemplateName, shortRunId } from './format'
import { normalizeRunStatus } from './runStatus'

/**
 * Human title for a run row / run detail. Backend (UX API draft) adds
 * `display_name` at top level and under `meta`; older APIs only have
 * `graph_name` (often the generic "pipeline") and the run id.
 */
const GENERIC_GRAPH_NAMES = new Set(['', 'pipeline', 'graph', 'untitled', 'default'])

function rec(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

export function runDisplayName(run: unknown): string {
  const r = rec(run)
  if (!r) return 'Run'
  const meta = rec(r.meta)
  const dn = str(r.display_name) || str(meta?.display_name)
  if (dn) return dn
  const graph = str(r.graph_name) || str(meta?.graph_name) || str(r.pipeline) || str(r.name)
  const id = str(r.run_id) || str(r.id) || str(meta?.run_id)
  if (graph && !GENERIC_GRAPH_NAMES.has(graph.toLowerCase())) return humanizeTemplateName(graph)
  return id ? `Run ${shortRunId(id)}` : 'Run'
}

/**
 * Full run id for a run opened by a (possibly shortened) id. The API resolves
 * an 8-char prefix on `GET /runs/{id}` but most other routes (POST /models,
 * trace, …) need the full id. Returns the detail's `run_id` (top level or
 * `meta`) when it extends `requested`; otherwise `requested` unchanged.
 */
export function resolveFullRunId(requested: string, detail: unknown): string {
  const d = rec(detail)
  if (!d || !requested) return requested
  const full = str(d.run_id) || str(rec(d.meta)?.run_id) || str(d.id)
  if (!full || full === requested) return requested
  return full.toLowerCase().startsWith(requested.toLowerCase()) ? full : requested
}

/* ── Shared run-status vocabulary ─────────────────────────────────────────
 * One mapping for every surface (header, Runs, Home, Ops, …) so the console
 * never says SUCCEEDED in one place and Done in another. Raw API statuses go
 * through `normalizeRunStatus` (lib/runStatus) plus the few extra states the
 * run journal / proposals use (archived, needs-action).
 */

export type RunStatusTone =
  | 'done'
  | 'failed'
  | 'running'
  | 'queued'
  | 'cancelled'
  | 'paused'
  | 'needs-action'
  | 'archived'
  | 'unknown'

const ARCHIVED = new Set(['archived', 'archive'])
const NEEDS_ACTION = new Set([
  'needs_action',
  'needs-action',
  'action_required',
  'awaiting_approval',
  'waiting_approval',
  'pending_approval',
  'awaiting_input',
  'blocked',
])

function rawStatus(status: unknown): string {
  return String(status ?? '')
    .trim()
    .toLowerCase()
}

/** Coarse tone bucket for a raw run status (drives StatusBadge colour). */
export function runStatusTone(status: unknown): RunStatusTone {
  const s = rawStatus(status)
  if (ARCHIVED.has(s)) return 'archived'
  if (NEEDS_ACTION.has(s)) return 'needs-action'
  switch (normalizeRunStatus(s)) {
    case 'completed':
      return 'done'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    case 'running':
      return 'running'
    case 'paused':
      return 'paused'
    case 'queued':
      return 'queued'
    default:
      return 'unknown'
  }
}

const TONE_LABEL: Record<Exclude<RunStatusTone, 'unknown'>, string> = {
  done: 'Done',
  failed: 'Failed',
  running: 'Running',
  queued: 'Queued',
  cancelled: 'Cancelled',
  paused: 'Paused',
  'needs-action': 'Needs action',
  archived: 'Archived',
}

/**
 * Human label for a raw run status: succeeded/completed/success → "Done",
 * error → "Failed", pending/scheduled → "Queued", canceled → "Cancelled", …
 * Unrecognised statuses are sentence-cased ("skipped" → "Skipped"); empty →
 * "Unknown".
 */
export function runStatusLabel(status: unknown): string {
  const raw = rawStatus(status)
  if (raw === 'awaiting_approval' || raw === 'waiting_approval' || raw === 'pending_approval') return 'Awaiting approval'
  const tone = runStatusTone(status)
  if (tone !== 'unknown') return TONE_LABEL[tone]
  const s = String(status ?? '').trim().replace(/[_-]+/g, ' ')
  if (!s) return 'Unknown'
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
}

/**
 * True when a status deserves a coloured badge — failed, running, queued,
 * paused, cancelled, needs action. Done / archived / unknown render as plain
 * muted text.
 */
export function isRunStatusException(status: unknown): boolean {
  const tone = runStatusTone(status)
  return tone !== 'done' && tone !== 'archived' && tone !== 'unknown'
}

/** First `length` chars of an id (default 8) — the console's short-id spelling. */
export function shortId(id: unknown, length = 8): string {
  const s = String(id ?? '').trim()
  if (!s) return '—'
  return s.length > length ? s.slice(0, length) : s
}
