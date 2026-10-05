import { describe, expect, it } from 'vitest'
import { actorDisplay, isUnidentifiedActor, parseMe } from './identity'

describe('parseMe', () => {
  it('maps the /me payload', () => {
    expect(
      parseMe({ actor: 'alice', actor_verified: true, token_mapped: true, claimed_actor: null, auth_configured: true, token_map_configured: true }),
    ).toEqual({ actor: 'alice', actorVerified: true, tokenMapped: true, claimedActor: '', authConfigured: true, tokenMapConfigured: true })
    expect(parseMe({ actor: 'bob' })?.actorVerified).toBe(false)
    expect(parseMe(null)).toBeNull()
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
