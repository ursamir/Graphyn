/** Normalize journal / distributed / UI run status strings to a small vocabulary. */

export type NormalizedRunStatus =
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'paused'
  | 'queued'
  | 'unknown'

const SUCCESS = new Set(['completed', 'succeeded', 'success', 'done', 'ok', 'complete'])
const FAILED = new Set(['failed', 'error', 'errored'])
const CANCELLED = new Set(['cancelled', 'canceled'])
const RUNNING = new Set(['running', 'in_progress', 'in-progress', 'active'])
const PAUSED = new Set(['paused', 'pausing'])
const QUEUED = new Set(['queued', 'pending', 'scheduled'])

export function normalizeRunStatus(raw: unknown): NormalizedRunStatus {
  const s = String(raw ?? '')
    .trim()
    .toLowerCase()
  if (!s) return 'unknown'
  if (SUCCESS.has(s)) return 'completed'
  if (FAILED.has(s)) return 'failed'
  if (CANCELLED.has(s)) return 'cancelled'
  if (RUNNING.has(s)) return 'running'
  if (PAUSED.has(s)) return 'paused'
  if (QUEUED.has(s)) return 'queued'
  return 'unknown'
}

export function isTerminalSuccess(raw: unknown): boolean {
  return normalizeRunStatus(raw) === 'completed'
}

export function isTerminalFailure(raw: unknown): boolean {
  const n = normalizeRunStatus(raw)
  return n === 'failed' || n === 'cancelled'
}

export function statusMatchesFilter(raw: unknown, filter: string): boolean {
  const needle = filter.trim().toLowerCase()
  if (!needle || needle === 'all') return true
  return normalizeRunStatus(raw) === normalizeRunStatus(needle)
}
