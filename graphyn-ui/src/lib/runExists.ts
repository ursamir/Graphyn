/**
 * Does a run still exist? `GET /runs/{id}` 404s for deleted runs (the
 * `/status` endpoint answers 200 `unknown` instead, so it cannot tell).
 * Results are shared/cached briefly so several callers do not stampede.
 */
import { ApiError, apiJson } from '../api/client'
import { sharedFetch } from './sharedFetch'

export type RunExistence = { exists: boolean; project?: string | null }

export async function checkRunExists(runId: string): Promise<RunExistence> {
  const id = runId.trim()
  if (!id) return { exists: false }
  return sharedFetch<RunExistence>(
    `run-exists:${id}`,
    async () => {
      try {
        const data = await apiJson<{ meta?: { project?: string | null } }>(`/runs/${encodeURIComponent(id)}`)
        return { exists: true, project: data?.meta?.project ?? null }
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 400)) return { exists: false }
        throw err
      }
    },
    { maxAgeMs: 30_000 },
  )
}
