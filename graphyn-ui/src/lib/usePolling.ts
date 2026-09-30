import React from 'react'

export type UsePollingOptions = {
  /** Poll only while true (default true). Toggling restarts the loop. */
  enabled?: boolean
  /** Run once immediately when (re)enabled (default true). */
  immediate?: boolean
  /** Skip ticks while the tab is hidden; run once on becoming visible (default true). */
  pauseWhenHidden?: boolean
}

/**
 * Interval polling with the two hygiene rules every poll in the console needs:
 *
 *  - **in-flight skip** — a tick is dropped while the previous call is still
 *    pending, so slow backends never accumulate overlapping requests;
 *  - **visibility pause** — ticks are skipped while `document.hidden`, and a
 *    catch-up call fires when the tab becomes visible again.
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
    let inFlight = false
    let disposed = false
    const tick = () => {
      if (disposed || inFlight) return
      if (pauseWhenHidden && typeof document !== 'undefined' && document.hidden) return
      inFlight = true
      let result: unknown
      try {
        result = fnRef.current()
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
    if (immediate) tick()
    const id = window.setInterval(tick, intervalMs)
    const onVisible = () => {
      if (!document.hidden) tick()
    }
    if (pauseWhenHidden) document.addEventListener('visibilitychange', onVisible)
    return () => {
      disposed = true
      window.clearInterval(id)
      if (pauseWhenHidden) document.removeEventListener('visibilitychange', onVisible)
    }
  }, [enabled, immediate, intervalMs, pauseWhenHidden, resetKey])
}
