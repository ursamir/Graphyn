/** Human labels for API field names shown in the console (F19 — F18 carried: no raw snake_case). */
import { startCase } from './format'

const QUOTA_LABELS: Record<string, string> = {
  max_seats: 'Seats',
  max_projects: 'Projects',
  max_runs_per_day: 'Runs per day',
  max_credentials: 'Credentials',
  max_concurrent_jobs: 'Concurrent jobs',
  max_queued_jobs: 'Queued jobs',
}

/** Quota field → short label (the form already says these are limits). */
export function quotaLabel(key: string): string {
  return QUOTA_LABELS[key] ?? startCase(key.replace(/^max_/, ''))
}

const QUEUE_REASONS: Record<string, { label: string; help: string }> = {
  waiting_worker: {
    label: 'Waiting for a worker',
    help: 'No connected worker can run this node type yet (check pools, plugins and GPU needs).',
  },
  no_capacity: {
    label: 'Workers busy',
    help: 'Matching workers exist but every slot is in use; the job starts when one frees up.',
  },
  org_quota: {
    label: 'Org limit reached',
    help: "Your organization is at its concurrent-jobs limit; it starts when one of the org's jobs finishes.",
  },
}

export function queueReasonLabel(reason?: string | null): string {
  const r = reason || 'waiting_worker'
  return QUEUE_REASONS[r]?.label ?? startCase(r)
}

export function queueReasonHelp(reason?: string | null): string {
  const r = reason || 'waiting_worker'
  return QUEUE_REASONS[r]?.help ?? ''
}
