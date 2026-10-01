import { afterEach, describe, expect, it } from 'vitest'
import {
  clearNavigationGuards,
  confirmNavigation,
  DEFAULT_NAVIGATION_GUARD_MESSAGE,
  pendingNavigationBlock,
  registerNavigationGuard,
} from './navigationGuard'

afterEach(() => clearNavigationGuards())

describe('navigationGuard', () => {
  it('passes with no guards', () => {
    expect(pendingNavigationBlock()).toBeNull()
    expect(confirmNavigation(() => false)).toBe(true)
  })

  it('clean guards (false / empty string) do not block', () => {
    registerNavigationGuard(() => false)
    registerNavigationGuard(() => '')
    expect(confirmNavigation(() => false)).toBe(true)
  })

  it('true uses the default message; string uses custom', () => {
    const off = registerNavigationGuard(() => true)
    let seen = ''
    expect(confirmNavigation((m) => ((seen = m), false))).toBe(false)
    expect(seen).toBe(DEFAULT_NAVIGATION_GUARD_MESSAGE)
    off()
    registerNavigationGuard(() => 'Custom')
    expect(pendingNavigationBlock()).toBe('Custom')
    expect(confirmNavigation(() => true)).toBe(true)
  })

  it('unregister removes the guard; throwing guard is ignored', () => {
    const off = registerNavigationGuard(() => true)
    off()
    registerNavigationGuard(() => {
      throw new Error('x')
    })
    expect(pendingNavigationBlock()).toBeNull()
  })
})
