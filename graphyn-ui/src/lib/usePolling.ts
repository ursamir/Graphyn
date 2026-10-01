import React from 'react'

export type UsePollingOptions = {
  /** Poll only while true (default true). Toggling restarts the loop. */
  enabled?: boolean
  /** Run once immediately when (re)enabled (default true). Always runs, even
   *  while the tab is hidden — otherwise a page opened in a background tab
   *  never gets its first data and sits on "Loading…" forever. */
  immediate?: boolean
  /** Skip *interval* ticks while the tab is hidden; run once on becoming visible (default true). */
  pauseWhenHidden?: boolean
}

/** Minimal environment the poll loop needs (injectable for tests). */
export type PollEnv = {
  isHidden: () => boolean
  setInterval: (fn: () => void, ms: number) => unknown
  clearInterval: (id: unknown) => void
  onVisibilityChange: (fn: () => void) => () => void
}

function browserEnv(): PollEnv {
  return {
    isHidden: () => typeof document !== 'undefined' && document.hidden,
    setInterval: (fn, ms) => window.setInterval(fn, ms),
    clearInterval: (id) => window.clearInterval(id as number),
    onVisibilityChange: (fn) => {
      if (typeof document === 'undefined') return () => undefined
      document.addEventListener('visibilitychange', fn)
      return () => document.removeEventListener('visibilitychange', fn)
    },
  }
}

/**
 * Framework-free poll loop (what `usePolling` runs inside its effect).
 * Returns a dispose function.
 *
 *  - the **immediate** first call always runs (hidden or not);
 *  - **interval** ticks are skipped while hidden (`pauseWhenHidden`), with a
 *    catch-up call when the tab becomes visible again;
 *  - **in-flight skip** — a tick is dropped while the previous call is pending.
 */
export function startPolling(
  fn: () => unknown,
  intervalMs: number,
  opts: { immediate?: boolean; pauseWhenHidden?: boolean } = {},
  env: PollEnv = browserEnv(),
): () => void {
  const { immediate = true, pauseWhenHidden = true } = opts
  let inFlight = false
  let disposed = false
  const run = (force: boolean) => {
    if (disposed || inFlight) return
    if (!force && pauseWhenHidden && env.isHidden()) return
    inFlight = true
    let result: unknown
    try {
      result = fn()
    } catch {
      inFlight = false
      return
    }
    Promise.resolve(result)
      .catch(() => undefined)
      .finally(() => {
        inFlight = false
      })
  }
  if (immediate) run(true)
  const id = env.setInterval(() => run(false), intervalMs)
  const off = pauseWhenHidden
    ? env.onVisibilityChange(() => {
        if (!env.isHidden()) run(false)
      })
    : () => undefined
  return () => {
    disposed = true
    env.clearInterval(id)
    off()
  }
}

/**
 * Interval polling with the hygiene rules every poll in the console needs
 * (see `startPolling`): in-flight skip, visibility pause for interval ticks,
 * and an initial call that always fires.
 *
 * `fn` is read through a ref, so callers may pass an inline closure without
 * restarting the interval every render. The loop restarts only when
 * `intervalMs` / `enabled` change (or when `resetKey` changes).
 */
export function usePolling(
  fn: () => unknown | Promise<unknown>,
  intervalMs: number,
  opts: UsePollingOptions & { resetKey?: unknown } = {},
): void {
  const { enabled = true, immediate = true, pauseWhenHidden = true, resetKey } = opts
  const fnRef = React.useRef(fn)
  fnRef.current = fn

  React.useEffect(() => {
    if (!enabled) return
    return startPolling(() => fnRef.current(), intervalMs, { immediate, pauseWhenHidden })
  }, [enabled, immediate, intervalMs, pauseWhenHidden, resetKey])
}
