/**
 * Resolve a registry artifact id → producing run id (Library Artifacts removed).
 */
import { apiJson } from '../api/client'

/** GET /artifacts/{id} → run_id, or null if missing / unreadable. */
export async function resolveArtifactRunId(artifactId: string): Promise<string | null> {
  const aid = artifactId.trim()
  if (!aid) return null
  try {
    const rec = await apiJson<{ run_id?: string }>(`/artifacts/${encodeURIComponent(aid)}`)
    const rid = String(rec?.run_id || '').trim()
    return rid || null
  } catch {
    return null
  }
}
