import { describe, expect, it } from 'vitest'
import { actorDisplay, hasPermission, isUnidentifiedActor, parseMe } from './identity'

describe('parseMe', () => {
  it('maps the /me payload', () => {
    expect(
      parseMe({ actor: 'alice', actor_verified: true, token_mapped: true, claimed_actor: null, auth_configured: true, token_map_configured: true }),
    ).toMatchObject({ actor: 'alice', actorVerified: true, tokenMapped: true, claimedActor: '', authConfigured: true, tokenMapConfigured: true, roles: [], permissions: [] })
    expect(parseMe({ actor: 'bob' })?.actorVerified).toBe(false)
    expect(parseMe(null)).toBeNull()
  })

  it('maps RBAC fields and checks permissions', () => {
    const me = parseMe({
      actor: 'bob', kind: 'user', auth_method: 'session', user_id: 'u_1', roles: ['viewer'],
      permissions: ['read', 'authenticated'], memberships: { alpha: 'builder', beta: '' },
    })!
    expect(me.kind).toBe('user')
    expect(me.memberships).toEqual({ alpha: 'builder' })
    expect(hasPermission(me, 'read')).toBe(true)
    expect(hasPermission(me, 'runs.execute')).toBe(false)
    expect(hasPermission(me, 'runs.execute', 'alpha')).toBe(true)
    expect(hasPermission(me, 'approve', 'alpha')).toBe(false)
    expect(hasPermission(parseMe({ actor: 'x' }), 'admin')).toBe(true)
  })
})

describe('actorDisplay', () => {
  it('verified / self-declared / unidentified / legacy', () => {
    expect(actorDisplay({ actor: 'alice', actorVerified: true })).toMatchObject({ name: 'alice', kind: 'verified', suffix: '' })
    expect(actorDisplay({ actor: 'alice', actorVerified: true, claimedActor: 'mallory' }).title).toContain('claimed "mallory"')
    expect(actorDisplay({ actor: 'bob', actorVerified: false })).toMatchObject({ kind: 'self-declared', suffix: '(self-declared)' })
    expect(actorDisplay({ actor: 'unidentified' })).toMatchObject({ name: 'Local operator', kind: 'unidentified' })
    expect(actorDisplay({ actor: '', claimedActor: 'eve' }).title).toContain('eve')
    expect(actorDisplay({ actor: 'carol' })).toMatchObject({ kind: 'unknown', suffix: '' })
  })
  it('treats generic actors as unidentified', () => {
    expect(isUnidentifiedActor('API')).toBe(true)
    expect(isUnidentifiedActor('samir')).toBe(false)
  })
})
