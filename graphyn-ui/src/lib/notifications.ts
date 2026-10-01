/**
 * Humanize in-app notification rows (GET /system/notifications).
 *
 * The backend title is often the raw event (`pipeline_complete: run <uuid>`)
 * with `status=… / graph=… / project=… / error=…` lines in the body. This turns
 * that into "Run succeeded · basic-wakeword · ui-review" plus a short detail.
 */
import { shortRunId } from './format'

export type NotificationRow = {
  id: string
  title?: string
  body?: string
  level?: string
  event?: string
  run_id?: string
  project?: string
  read?: boolean
  created_at?: string
  ts?: string
  meta?: { graph_name?: string | null; status?: string | null; [k: string]: unknown } | null
}

export type NotificationTone = 'success' | 'error' | 'cancelled' | 'info'

function parseBody(body?: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of (body || '').split('\n')) {
    const m = /^\s*([a-z_]+)=(.*)$/i.exec(line)
    if (m) out[m[1].toLowerCase()] = m[2].trim()
  }
  return out
}

const RAW_TITLE = /^[a-z]+(_[a-z]+)+:\s/i

export function humanizeNotification(n: NotificationRow): {
  title: string
  detail: string | null
  tone: NotificationTone
} {
  const fields = parseBody(n.body)
  const event = (n.event || '').toLowerCase()
  const status = String(n.meta?.status || fields.status || '').toLowerCase()
  const graph = String(n.meta?.graph_name || fields.graph || '').trim()
  const project = String(n.project || fields.project || '').trim()
  const error = fields.error || ''

  let verb: string | null = null
  let tone: NotificationTone = n.level === 'error' ? 'error' : 'info'
  if (event === 'pipeline_cancelled' || status === 'cancelled' || status === 'canceled') {
    verb = 'Run cancelled'
    tone = 'cancelled'
  } else if (event === 'pipeline_failed' || status === 'failed' || status === 'error') {
    verb = 'Run failed'
    tone = 'error'
  } else if (event === 'pipeline_complete' || status === 'succeeded' || status === 'completed') {
    verb = 'Run succeeded'
    tone = 'success'
  } else if (event.startsWith('pipeline_') || event.startsWith('run_')) {
    verb = `Run ${event.replace(/^(pipeline|run)_/, '').replace(/_/g, ' ')}`
  }

  const rawTitle = (n.title || '').trim()
  const titleLooksRaw = !rawTitle || RAW_TITLE.test(rawTitle) || rawTitle === n.event
  let title: string
  if (verb && titleLooksRaw) {
    title = [verb, graph, project].filter(Boolean).join(' · ')
  } else if (rawTitle && !titleLooksRaw) {
    title = rawTitle
  } else {
    title = (n.event || 'Event').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
  }

  let detail: string | null
  if (error) detail = error
  else if (Object.keys(fields).length > 0) detail = null // structured body fully represented in the title
  else detail = n.body?.trim() || null
  return { title, detail, tone }
}

export function notificationRunLabel(runId?: string | null): string | null {
  return runId ? `Run ${shortRunId(runId)}` : null
}
