/**
 * App-level navigation guard registry (e.g. Editor unsaved changes).
 *
 * A guard returns `false` / `''` when it is clean, or `true` / a message string
 * when leaving would lose work. `confirmNavigation()` is consulted by app-level
 * navigation entry points (sidebar, command palette, header workspace switch,
 * jump keys, `goView`) before they change route.
 *
 *   const off = registerNavigationGuard(() => dirty)   // in an effect
 *   return off                                         // unregister on unmount
 */

export type NavigationGuard = () => boolean | string

export const DEFAULT_NAVIGATION_GUARD_MESSAGE =
  'You have unsaved changes in the Editor — leave anyway?'

const guards = new Set<NavigationGuard>()

/** Register a guard; returns an unregister function. */
export function registerNavigationGuard(fn: NavigationGuard): () => void {
  guards.add(fn)
  return () => {
    guards.delete(fn)
  }
}

/**
 * First blocking message from the registered guards, or null when every guard
 * is clean. A throwing guard is treated as clean (never trap the user).
 */
export function pendingNavigationBlock(): string | null {
  for (const g of guards) {
    let r: boolean | string
    try {
      r = g()
    } catch {
      continue
    }
    if (r === true) return DEFAULT_NAVIGATION_GUARD_MESSAGE
    if (typeof r === 'string' && r.trim()) return r
  }
  return null
}

/**
 * True when navigation may proceed: no guard blocks, or the user confirmed.
 * `confirmFn` is injectable for tests (defaults to window.confirm).
 */
export function confirmNavigation(
  confirmFn: (message: string) => boolean = (m) =>
    typeof window !== 'undefined' && typeof window.confirm === 'function' ? window.confirm(m) : true,
): boolean {
  const msg = pendingNavigationBlock()
  if (!msg) return true
  return confirmFn(msg)
}

/** Test helper — drop all guards. */
export function clearNavigationGuards(): void {
  guards.clear()
}
