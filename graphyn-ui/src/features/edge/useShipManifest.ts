/** Fetch + parse a package's deployment_packager sidecar (`<package>.manifest.json`). */
import React from 'react'
import { apiFetch } from '../../api/client'
import { manifestPathFor, parseShipManifest, type ShipManifest } from './shipManifest'

export function useShipManifest(packagePath: string | null | undefined, refreshKey?: unknown) {
  const [manifest, setManifest] = React.useState<ShipManifest | null>(null)
  const [loading, setLoading] = React.useState(false)
  React.useEffect(() => {
    const p = (packagePath || '').trim()
    if (!p) {
      setManifest(null)
      return
    }
    let cancelled = false
    setLoading(true)
    void apiFetch('/outputs/file', { query: { path: manifestPathFor(p) }, retries: 0 })
      .then(async (res) => {
        if (cancelled) return
        if (!res.ok) {
          setManifest(null)
          return
        }
        setManifest(parseShipManifest(await res.json().catch(() => null)))
      })
      .catch(() => {
        if (!cancelled) setManifest(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [packagePath, refreshKey])
  return { manifest, loading }
}
