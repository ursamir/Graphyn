import { describe, expect, it } from 'vitest'
import { queueReasonHelp, queueReasonLabel, quotaLabel } from './fieldLabels'

describe('fieldLabels', () => {
  it('humanizes quota fields', () => {
    expect(quotaLabel('max_runs_per_day')).toBe('Runs per day')
    expect(quotaLabel('max_concurrent_jobs')).toBe('Concurrent jobs')
    expect(quotaLabel('max_widgets')).not.toContain('_')
  })
  it('humanizes queue reasons, defaulting to waiting for a worker', () => {
    expect(queueReasonLabel('no_capacity')).toBe('Workers busy')
    expect(queueReasonLabel('org_quota')).toBe('Org limit reached')
    expect(queueReasonLabel(null)).toBe('Waiting for a worker')
    expect(queueReasonLabel('some_new_reason')).not.toContain('_')
    expect(queueReasonHelp('org_quota')).toMatch(/limit/)
  })
})
