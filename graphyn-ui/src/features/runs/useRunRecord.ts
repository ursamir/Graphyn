/**
 * Run record loader: backend `record` on GET /runs/{id} (audit contract), else
 * the run journal's prove.json (+ meta.json) via GET /outputs/file.
 */
import React from 'react'
import { apiFetch } from '../../api/client'
import { pickProve } from './runRecord'

type Rec = Record<string, unknown>

/** Candidate journal paths for a run file (API lists `workspace/runs/<id>/…`). */
export function runJournalPaths(runId: string, file: string): string[] {
  return [`workspace/runs/${runId}/${file}`, `runs/${runId}/${file}`]
}

async function fetchJournalJson(runId: string, file: string): Promise<Rec | null> {
  for (const path of runJournalPaths(runId, file)) {
    try {
      const res = await apiFetch('/outputs/file', { query: { path }, retries: 0 })
      if (!res.ok) continue
      const data: unknown = await res.json()
      if (data && typeof data === 'object' && !Array.isArray(data)) return data as Rec
    } catch {
      /* try next */
    }
  }
  return null
}

/**
 * Load the run's record: backend `record` on the detail when present (new
 * API), else prove.json (+ meta.json when the detail has no meta) from the
 * run journal. `pending` when the backend says the record is not sealed yet.
 */
export function useRunRecord(
  runId: string | null,
  detail: Rec | null,
): { prove: Rec | null; meta: Rec | null; pending: boolean; loading: boolean } {
  const backendProve = pickProve(detail)
  const recordStatus = String(detail?.record_status ?? '').toLowerCase()
  const pending = recordStatus === 'pending'
  const detailMeta = detail?.meta && typeof detail.meta === 'object' ? (detail.meta as Rec) : null
  const needFile = Boolean(runId && detail && !backendProve && !pending)
  const [state, setState] = React.useState<{ runId: string | null; prove: Rec | null; meta: Rec | null; loading: boolean }>(
    { runId: null, prove: null, meta: null, loading: false },
  )
  React.useEffect(() => {
    if (!runId || !needFile) return
    let cancelled = false
    setState({ runId, prove: null, meta: null, loading: true })
    void (async () => {
      const [prove, meta] = await Promise.all([
        fetchJournalJson(runId, 'prove.json'),
        detailMeta ? Promise.resolve(null) : fetchJournalJson(runId, 'meta.json'),
      ])
      if (!cancelled) setState({ runId, prove, meta, loading: false })
    })()
    return () => {
      cancelled = true
    }
    // detailMeta presence only decides whether meta.json is needed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, needFile])
  if (backendProve) return { prove: backendProve, meta: detailMeta, pending: false, loading: false }
  const mine = state.runId === runId
  return {
    prove: mine ? state.prove : null,
    meta: detailMeta ?? (mine ? state.meta : null),
    pending,
    loading: needFile && (!mine || state.loading),
  }
}

