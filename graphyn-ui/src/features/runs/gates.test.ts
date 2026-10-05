import { describe, expect, it } from 'vitest'
import { gateCardState, gateTitle, parseGates } from './gates'

const payload = {
  run_id: 'r1',
  run_status: 'running',
  awaiting_approval: true,
  gates: [
    {
      node_id: 'approve',
      gate_id: 'approve',
      label: 'Ship approval',
      prompt: 'Deploy?',
      status: 'pending',
      pending: true,
      waiting_since: '2026-10-05T00:00:00Z',
      timeout_s: 3600,
      expires_at: '2026-10-05T01:00:00Z',
      approver_roles: ['lead', 'qa'],
      reason_required: true,
    },
    {
      node_id: 'g2',
      status: 'decided',
      pending: false,
      decision: { approved: false, approver: 'alice', actor_verified: true, decided_at: 't', comment_sha256: 'abc' },
    },
    { node_id: 'g3', status: 'not_reached' },
    { status: 'pending' },
  ],
}

describe('parseGates', () => {
  it('parses gates and drops rows without node id', () => {
    const p = parseGates(payload)
    expect(p.awaitingApproval).toBe(true)
    expect(p.gates.map((g) => g.nodeId)).toEqual(['approve', 'g2', 'g3'])
    expect(p.gates[0].approverRoles).toEqual(['lead', 'qa'])
    expect(p.gates[1].decision).toMatchObject({ approved: false, approver: 'alice', actorVerified: true })
    expect(parseGates(null).gates).toEqual([])
  })
})

describe('gateCardState', () => {
  const [pending, decided, notReached] = parseGates(payload).gates
  it('requires a reason and a role before deciding', () => {
    expect(gateCardState(pending, '')).toMatchObject({ canDecide: true, needsComment: true, needsRole: true, tone: 'pending' })
    expect(gateCardState(pending, '').disabledReason).toMatch(/reason/)
    expect(gateCardState(pending, 'ok').disabledReason).toMatch(/role/)
    expect(gateCardState(pending, 'ok', 'lead').disabledReason).toBe('')
    expect(gateCardState(pending, 'ok', 'lead', true).disabledReason).toBe('Sending…')
  })
  it('reads decided / not reached gates', () => {
    expect(gateCardState(decided, '')).toMatchObject({ canDecide: false, headline: 'Rejected', tone: 'bad' })
    expect(gateCardState(notReached, '')).toMatchObject({ canDecide: false, headline: 'Not reached yet', tone: 'muted' })
    const approved = { ...decided, status: 'approved' as const, decision: null }
    expect(gateCardState(approved, '').headline).toBe('Approved')
  })
  it('titles a gate by label, then step label, then id', () => {
    expect(gateTitle(pending)).toBe('Ship approval')
    expect(gateTitle(decided, () => 'Review step')).toBe('Review step')
    expect(gateTitle(notReached)).toBe('g3')
    // Backend path-suffixed labels lose to the run view's step name.
    expect(gateTitle({ ...pending, label: 'Hitl approve · Path C' }, () => 'gate')).toBe('gate')
    expect(gateTitle({ ...pending, label: 'Hitl approve · Path C' })).toBe('Hitl approve')
  })
})
