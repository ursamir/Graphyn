import { apiFetch, apiJson } from '../api/client'
import type { GraphIR } from '../types/graph'

function looksLikeGraph(data: unknown): data is GraphIR {
  return (
    !!data &&
    typeof data === 'object' &&
    Array.isArray((data as GraphIR).nodes) &&
    Array.isArray((data as GraphIR).edges)
  )
}

/** Load a run's Graph IR for Builder — dedicated API, then journal file, then named template. */
export async function fetchRunGraph(
  runId: string,
  graphName?: string | null,
): Promise<GraphIR | null> {
  const rid = runId.trim()
  if (rid) {
    try {
      const data = await apiJson<GraphIR>(`/runs/${encodeURIComponent(rid)}/graph`)
      if (looksLikeGraph(data)) return data
    } catch {
      /* fall through to file / template */
    }
    for (const path of [`workspace/runs/${rid}/graph.json`, `runs/${rid}/graph.json`]) {
      try {
        const res = await apiFetch('/outputs/file', { query: { path } })
        if (!res.ok) continue
        const data: unknown = await res.json()
        if (looksLikeGraph(data)) return data
      } catch {
        /* try next */
      }
    }
  }
  const name = (graphName ?? '').trim()
  if (name) {
    try {
      const data = await apiJson<{ graph?: GraphIR }>(
        `/pipelines/templates/${encodeURIComponent(name)}`,
      )
      if (looksLikeGraph(data.graph)) return data.graph
      if (looksLikeGraph(data)) return data as unknown as GraphIR
    } catch {
      /* missing template */
    }
  }
  return null
}
