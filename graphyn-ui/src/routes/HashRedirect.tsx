import { useEffect } from 'react'
import { resolveLegacyHash, type LegacyHashContext } from './legacyHash'
import { navigatePath } from './parsePath'

type Props = LegacyHashContext & {
  /** When true (default), replace history so Back skips the hash URL. */
  replace?: boolean
}

/**
 * On mount (and hashchange), if `location.hash` is a legacy `#/...` route,
 * navigate via navigatePath (Zustand + synthetic popstate) and clear the hash.
 * Cold-load `#/…` must set the view correctly — RR navigate alone does not sync the store.
 */
export function HashRedirect({ activeProject, replace = true }: Props) {
  useEffect(() => {
    const apply = () => {
      const { hash } = window.location
      if (!hash || hash === '#' || hash === '#/') return
      // Only redirect app-style hashes (`#/…`).
      if (!/^#\//.test(hash)) return

      const target = resolveLegacyHash(hash, { activeProject })
      if (!target) return

      const pathOnly = window.location.pathname + window.location.search
      // Clear hash first so a later sync effect does not re-read it.
      if (window.location.hash) {
        window.history.replaceState(null, '', pathOnly)
      }
      navigatePath(target, replace)
    }

    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [activeProject, replace])

  return null
}
