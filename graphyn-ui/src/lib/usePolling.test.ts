import { describe, expect, it } from 'vitest'
import { startPolling, type PollEnv } from './usePolling'

function fakeEnv(hidden: boolean) {
  const state = { hidden, tick: null as null | (() => void), vis: null as null | (() => void), cleared: false }
  const env: PollEnv = {
    isHidden: () => state.hidden,
    setInterval: (fn) => {
      state.tick = fn
      return 1
    },
    clearInterval: () => {
      state.cleared = true
    },
    onVisibilityChange: (fn) => {
      state.vis = fn
      return () => {
        state.vis = null
      }
    },
  }
  return { env, state }
}

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('startPolling', () => {
  it('runs the immediate call even while the tab is hidden', () => {
    const { env } = fakeEnv(true)
    let calls = 0
    startPolling(() => calls++, 1000, {}, env)
    expect(calls).toBe(1)
  })

  it('skips interval ticks while hidden and catches up on visible', async () => {
    const { env, state } = fakeEnv(true)
    let calls = 0
    startPolling(() => calls++, 1000, {}, env)
    await flush()
    state.tick!()
    expect(calls).toBe(1)
    state.hidden = false
    state.vis!()
    expect(calls).toBe(2)
    await flush()
    state.tick!()
    expect(calls).toBe(3)
  })

  it('does not run immediately when immediate=false', () => {
    const { env } = fakeEnv(false)
    let calls = 0
    startPolling(() => calls++, 1000, { immediate: false }, env)
    expect(calls).toBe(0)
  })

  it('drops ticks while a call is in flight', async () => {
    const { env, state } = fakeEnv(false)
    let calls = 0
    let resolve: () => void = () => undefined
    startPolling(
      () => {
        calls++
        return new Promise<void>((r) => {
          resolve = r
        })
      },
      1000,
      {},
      env,
    )
    state.tick!()
    expect(calls).toBe(1)
    resolve()
    await flush()
    state.tick!()
    expect(calls).toBe(2)
  })

  it('stops after dispose', () => {
    const { env, state } = fakeEnv(false)
    let calls = 0
    const stop = startPolling(() => calls++, 1000, { immediate: false }, env)
    stop()
    state.tick?.()
    expect(calls).toBe(0)
    expect(state.cleared).toBe(true)
    expect(state.vis).toBeNull()
  })
})
