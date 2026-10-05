import { describe, expect, it } from 'vitest'
import {
  lastVerifyOf,
  lastVerifyText,
  parseLastVerify,
  parseVerifyCounts,
  parseVerifyHistory,
  verifyStripSummary,
} from './runRecord'
import { recordSummaryParts } from './runOverview'

const fmt = () => 'Oct 4 17:59'

describe('last verify', () => {
  it('parses a run row last_verify', () => {
    const lv = lastVerifyOf({
      last_verify: { checked_at: '2026-10-04T08:59:00Z', actor: 'alice', actor_verified: true, ok: true, status: 'verified', passed: 6, total: 6 },
    })
    expect(lv).toMatchObject({ actor: 'alice', actorVerified: true, ok: true, passed: 6, total: 6 })
    expect(lastVerifyOf({ last_verify: null })).toBeNull()
    expect(lastVerifyOf({ meta: { last_verify: { ok: false, checked_at: 'x' } } })?.ok).toBe(false)
  })

  it('parses a verify response with summary counts', () => {
    const lv = parseLastVerify({
      ok: false,
      status: 'failed',
      checked_at: '2026-10-04T08:59:00Z',
      actor: 'bob',
      actor_verified: false,
      summary: { passed: 4, failed: 1, changed: 1, missing: 0, skipped: 0, total: 6 },
    })
    expect(lv).toMatchObject({ passed: 4, total: 6, actorVerified: false })
    expect(parseVerifyCounts({ passed: 4, failed: 2, total: 6 })).toEqual({ passed: 4, failed: 2, changed: 0, missing: 0, skipped: 0, total: 6 })
    expect(parseVerifyCounts({})).toBeNull()
  })

  it('formats the record summary text', () => {
    const ok = parseLastVerify({ ok: true, checked_at: 't', actor: 'alice', passed: 6, total: 6 })
    expect(lastVerifyText(ok, fmt)).toMatchObject({ text: 'Verified ✓ Oct 4 17:59 by alice · 6/6', tone: 'ok' })
    const bad = parseLastVerify({ ok: false, status: 'failed', checked_at: 't', actor: 'alice', passed: 4, total: 6 })
    expect(lastVerifyText(bad, fmt).text).toBe('Verify failed Oct 4 17:59 by alice · 4/6')
    const anon = parseLastVerify({ ok: true, checked_at: 't', actor: 'unidentified' })
    expect(lastVerifyText(anon, fmt).text).toBe('Verified ✓ Oct 4 17:59')
    expect(lastVerifyText(null).text).toBe('Not verified')
    expect(lastVerifyText(parseLastVerify({ ok: false, status: 'unsealed' })).text).toBe('Not sealed')
  })

  it('feeds the Run record summary line', () => {
    const lv = parseLastVerify({ ok: true, checked_at: 't', actor: 'alice', passed: 6, total: 6 })
    expect(
      recordSummaryParts({ hasProve: true, gapCount: 0, chainPosition: 3, seed: null, lastVerify: lv, formatWhen: fmt }),
    ).toEqual({ verdict: 'Verified ✓ Oct 4 17:59 by alice · 6/6', tone: 'ok', details: ['chain #3'] })
  })

  it('server counts win in the verify strip', () => {
    const groups = [{ state: 'pass' as const, items: [] }]
    expect(verifyStripSummary(groups, true, 'verified', { passed: 6, total: 6 })).toMatchObject({ passed: 6, total: 6 })
    expect(verifyStripSummary(groups, true, 'verified')).toMatchObject({ passed: 1, total: 1 })
  })

  it('parses verify history newest first', () => {
    const h = parseVerifyHistory({
      run_id: 'r',
      total: 3,
      history: [
        { checked_at: '2026-10-04T09:00:00Z', actor: 'alice', actor_verified: true, ok: true, status: 'verified', record_hash: 'abc', summary: { passed: 6, total: 6 } },
        { checked_at: '2026-10-03T09:00:00Z', actor: 'bob', actor_verified: false, ok: false, status: 'failed', summary: { passed: 5, total: 6 } },
      ],
    })
    expect(h.total).toBe(3)
    expect(h.rows).toHaveLength(2)
    expect(h.rows[0]).toMatchObject({ actor: 'alice', ok: true, passed: 6, total: 6, recordHash: 'abc' })
    expect(h.rows[1].counts?.passed).toBe(5)
    expect(parseVerifyHistory(null)).toEqual({ total: 0, rows: [] })
  })
})
