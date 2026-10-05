/**
 * Home (workspace overview) pure helpers: the one-line header summary, the
 * status word used in it, and the Activity list rows (distinguishing detail +
 * collapsing of consecutive identical failures).
 */
import { formatRelativeTime } from '../../lib/format'
import { formatMetricValue, metricLabel, primaryMetric } from '../../lib/metrics'
import { normalizeRunStatus } from '../../lib/runStatus'
import { isRunStatusException, runDisplayName, runStatusLabel } from '../../lib/runDisplay'

type Rec = Record<string, unknown>

function rec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

/**
 * Status word shared with Runs (lib/runDisplay vocabulary): succeeded →
 * "Done", failed → "Failed", running → "Running", …
 */
export function runStatusWord(raw: unknown): string {
  return runStatusLabel(raw)
}

/** True for statuses that deserve a coloured badge (anything but plain success). */
export function isExceptionStatus(raw: unknown): boolean {
  return isRunStatusException(raw)
}

/** First line of a run's error, trimmed for a one-line list row ('' when none). */
export function runErrorLine(run: unknown, max = 140): string {
  const r = rec(run)
  if (!r) return ''
  const meta = rec(r.meta)
  const cand = [r.error, meta?.error, r.error_message, meta?.error_message, r.message]
  let text = ''
  for (const c of cand) {
    if (typeof c === 'string' && c.trim()) {
      text = c
      break
    }
    const o = rec(c)
    if (o && (str(o.message) || str(o.error))) {
      text = str(o.message) || str(o.error)
      break
    }
  }
  const line = text
    .split('\n')
    .map((l) => l.trim())
    .find(Boolean) ?? ''
  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

/** `replay_of` run id from a run row ('' when the run is not a replay). */
export function replayOf(run: unknown): string {
  const r = rec(run)
  if (!r) return ''
  const meta = rec(r.meta)
  return str(r.replay_of) || str(meta?.replay_of) || str(rec(r.replay)?.of) || str(rec(meta?.replay)?.of)
}

/** Number of compared training paths in the run summary (0 when unknown). */
export function runPathCount(run: unknown): number {
  const r = rec(run)
  const summary = rec(r?.summary) ?? rec(rec(r?.meta)?.summary)
  return Array.isArray(summary?.paths) ? summary.paths.length : 0
}

export type ActivityDetail = { text: string; tone: 'muted' | 'error' }

/**
 * The text that tells one Activity row from its neighbours:
 * success → "Test accuracy 75.6% · best of 2 paths"; failure → first error line;
 * a replay is prefixed "replay of <id>".
 */
export function activityDetail(run: unknown, shortId: (id: string) => string = (id) => id.slice(0, 8)): ActivityDetail | null {
  const status = normalizeRunStatus(rec(run)?.status)
  const parts: string[] = []
  const rep = replayOf(run)
  if (rep) parts.push(`replay of ${shortId(rep)}`)
  if (status === 'failed' || status === 'cancelled') {
    const err = runErrorLine(run)
    if (err) parts.push(err)
    return parts.length ? { text: parts.join(' · '), tone: err ? 'error' : 'muted' } : null
  }
  const pm = primaryMetric(run)
  const paths = runPathCount(run)
  if (pm) {
    parts.push(`${metricLabel(pm.name)} ${formatMetricValue(pm.name, pm.value)}${paths > 1 ? ` · best of ${paths} paths` : ''}`)
  } else if (paths > 1) {
    parts.push(`${paths} paths`)
  }
  return parts.length ? { text: parts.join(' · '), tone: 'muted' } : null
}

export type ActivityItem<R> =
  | { kind: 'run'; run: R }
  | { kind: 'more-failed'; key: string; runs: R[] }

function failureKey(run: unknown): string | null {
  const r = rec(run)
  const s = normalizeRunStatus(r?.status)
  if (s !== 'failed' && s !== 'cancelled') return null
  return `${s}|${runDisplayName(run)}|${runErrorLine(run)}|${replayOf(run) ? 'replay' : ''}`
}

/**
 * Activity rows with consecutive identical failures (same pipeline, same
 * status, same error line) collapsed behind the first one into a single
 * "N more failed runs" item. Groups listed in `expanded` (by key) stay open.
 * At most `max` items are returned; a collapsed group counts as one item.
 */
export function buildActivityItems<R extends { run_id: string }>(
  runs: readonly R[],
  max = 8,
  expanded: ReadonlySet<string> = new Set(),
): ActivityItem<R>[] {
  const out: ActivityItem<R>[] = []
  let i = 0
  while (i < runs.length && out.length < max) {
    const run = runs[i]
    out.push({ kind: 'run', run })
    const key = failureKey(run)
    i += 1
    if (!key) continue
    const dupes: R[] = []
    while (i < runs.length && failureKey(runs[i]) === key) {
      dupes.push(runs[i])
      i += 1
    }
    if (dupes.length === 0) continue
    const groupKey = `more-${run.run_id}`
    if (expanded.has(groupKey)) {
      for (const d of dupes) {
        if (out.length >= max) break
        out.push({ kind: 'run', run: d })
      }
    } else if (out.length < max) {
      out.push({ kind: 'more-failed', key: groupKey, runs: dupes })
    }
  }
  return out
}

/**
 * Home header line: "3 pipelines · 8 runs · last run Speech commands E2E Done 2h ago".
 * `runsCapped` (the list hit the fetch limit) renders the run count as "N+".
 */
export function homeSummaryLine(input: {
  pipelines: number
  runs: number
  runsCapped?: boolean
  lastRun?: { status?: string; created_at?: string } | null
}): string {
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  const parts = [
    plural(input.pipelines, 'pipeline'),
    input.runsCapped ? `${input.runs}+ runs` : plural(input.runs, 'run'),
  ]
  if (input.lastRun) {
    const when = input.lastRun.created_at ? ` ${formatRelativeTime(input.lastRun.created_at)}` : ''
    parts.push(`last run ${runDisplayName(input.lastRun)} ${runStatusWord(input.lastRun.status)}${when}`)
  }
  return parts.join(' · ')
}

const WORKSPACE_STATUS_WORD: Record<string, string> = {
  'in-progress': 'In progress',
  active: 'In progress',
  ready: 'Ready',
  archived: 'Archived',
}

/**
 * Workspace status word for the Home header, or null when there is nothing
 * honest to say. The API's default `draft` reads "Getting started" only when
 * the workspace truly has no runs; a draft with runs shows no status word
 * (it isn't "getting started" any more). Null while loading.
 */
export function workspaceStatusLabel(status: unknown, hasRuns: boolean, loading = false): string | null {
  if (loading) return null
  const s = String(status ?? 'draft').trim().toLowerCase()
  if (WORKSPACE_STATUS_WORD[s]) return WORKSPACE_STATUS_WORD[s]
  return hasRuns ? null : 'Getting started'
}
