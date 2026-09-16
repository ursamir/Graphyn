import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { resolveLegacyHash, type LegacyHashContext } from './legacyHash'

type Props = LegacyHashContext & {
  /** When true (default), replace history so Back skips the hash URL. */
  replace?: boolean
}

/**
 * On mount (and hashchange), if `location.hash` is a legacy `#/...` route,
 * navigate to the path equivalent and clear the hash fragment.
 */
export function HashRedirect({ activeProject, replace = true }: Props) {
  const navigate = useNavigate()

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
      navigate(target, { replace })
    }

    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [activeProject, navigate, replace])

  return null
}
