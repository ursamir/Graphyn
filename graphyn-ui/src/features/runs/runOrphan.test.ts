import { describe, expect, it } from 'vitest'
import { extractRunFailure } from './runNodes'
import { failureView } from './runRecord'
import { runFailureReason } from './runOverview'

const msg =
  'orphaned_by_restart: the process that owned this run stopped while it was running (owner process 7 was restarted). Nothing was re-run automatically. Re-run the pipeline to retry — completed cacheable steps are reused.'

describe('orphaned_by_restart (DIST-ORPHAN-1)', () => {
  it('run failure carries the reason code from the journal event', () => {
    const f = extractRunFailure({ events: [{ type: 'error', error: msg, error_type: 'orphaned_by_restart' }] })
    expect(f?.errorType).toBe('orphaned_by_restart')
    const v = failureView({ error: f?.error, errorType: f?.errorType })
    expect(v?.errorType).toBe('Orphaned by restart')
    expect(v?.headline.startsWith('Orphaned by restart: the process that owned this run stopped')).toBe(true)
    expect(v?.headline).not.toContain('orphaned_by_restart')
  })

  it('works from meta alone (no journal event)', () => {
    const v = failureView({ error: msg })
    expect(v?.errorType).toBe('Orphaned by restart')
    const row = runFailureReason({ status: 'failed', meta: { error: msg, error_type: 'orphaned_by_restart' } })
    expect(row).toMatch(/process that owned this run stopped/)
  })
})
