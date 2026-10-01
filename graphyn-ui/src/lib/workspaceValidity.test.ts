import { describe, expect, it } from 'vitest'
import {
  forgetWorkspaceVerdict,
  isWorkspaceKnownMissing,
  isWorkspaceKnownValid,
  markWorkspaceMissing,
  markWorkspaceValid,
  pickFallbackWorkspace,
  pruneRecentNames,
} from './workspaceValidity'

describe('workspaceValidity helpers', () => {
  it('prunes recents that no longer exist, keeping order', () => {
    expect(
      pruneRecentNames(['e2e-ex-06-speech-commands-e2e', 'ui-review', 'gone', 'b'], ['b', 'ui-review']),
    ).toEqual(['ui-review', 'b'])
  })

  it('picks the most recent valid workspace, skipping the excluded one', () => {
    const recents = ['does-not-exist', 'old-deleted', 'ui-review', 'other']
    expect(pickFallbackWorkspace(recents, ['ui-review', 'other'], 'does-not-exist')).toBe('ui-review')
    expect(pickFallbackWorkspace(recents, ['ui-review'], 'ui-review')).toBeNull()
    expect(pickFallbackWorkspace(recents, null)).toBeNull()
    expect(pickFallbackWorkspace([], ['ui-review'])).toBeNull()
  })

  it('tracks valid / missing verdicts exclusively', () => {
    markWorkspaceValid('w1')
    expect(isWorkspaceKnownValid('w1')).toBe(true)
    markWorkspaceMissing('w1')
    expect(isWorkspaceKnownValid('w1')).toBe(false)
    expect(isWorkspaceKnownMissing('w1')).toBe(true)
    forgetWorkspaceVerdict('w1')
    expect(isWorkspaceKnownMissing('w1')).toBe(false)
    expect(isWorkspaceKnownValid(null)).toBe(false)
  })
})
