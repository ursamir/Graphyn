/**
 * Fetches evaluator `metrics.json` (and notes `confusion_matrix.png`) from a
 * run's outputs so Runs can show results even when the API has no `summary`
 * (old container). Results are cached per run + path; stale runs are dropped.
 */
import React from 'react'
import { apiFetch } from '../../api/client'
import { isMetricsFile } from './runResults'

type FileLike = { name: string; path: string; node_id?: string | null }

export type EvaluatorOutputs = {
  /** node id → parsed metrics.json */
  metricsByNode: Record<string, unknown>
  /** node id → confusion-matrix image path */
  confusionImageByNode: Record<string, string>
  /** node id → metrics.json path (for "open file") */
  metricsPathByNode: Record<string, string>
}

const CACHE = new Map<string, unknown>()
const MAX_FILES = 8

function nodeOfFile(f: FileLike): string {
  const nid = String(f.node_id || '').trim()
  if (nid) return nid
  // artifacts/<pack>/runs/<run>/<node_id>/metrics.json → parent dir
  const parts = f.path.replace(/\\/g, '/').split('/')
  return parts.length >= 2 ? parts[parts.length - 2] : ''
}

export function useEvaluatorOutputs(runId: string | null, files: FileLike[]): EvaluatorOutputs {
  const [metricsByNode, setMetricsByNode] = React.useState<Record<string, unknown>>({})
  const metricFiles = React.useMemo(
    () => files.filter((f) => isMetricsFile(f.name) && nodeOfFile(f)).slice(0, MAX_FILES),
    [files],
  )
  const key = `${runId}|${metricFiles.map((f) => f.path).join('|')}`

  React.useEffect(() => {
    if (!runId || metricFiles.length === 0) {
      setMetricsByNode({})
      return
    }
    let cancelled = false
    void (async () => {
      const out: Record<string, unknown> = {}
      await Promise.all(
        metricFiles.map(async (f) => {
          const cacheKey = `${runId}|${f.path}`
          if (CACHE.has(cacheKey)) {
            out[nodeOfFile(f)] = CACHE.get(cacheKey)
            return
          }
          try {
            const res = await apiFetch('/outputs/file', { query: { path: f.path }, retries: 1 })
            if (!res.ok) return
            const data: unknown = await res.json()
            if (data && typeof data === 'object') {
              CACHE.set(cacheKey, data)
              out[nodeOfFile(f)] = data
            }
          } catch {
            /* best-effort */
          }
        }),
      )
      if (!cancelled) setMetricsByNode(out)
    })()
    return () => {
      cancelled = true
    }
    // key captures runId + file paths
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const confusionImageByNode = React.useMemo(() => {
    const m: Record<string, string> = {}
    for (const f of files) {
      if (!/confusion[_-]?matrix.*\.(png|jpe?g|svg)$/i.test(f.name)) continue
      const nid = nodeOfFile(f)
      if (nid && !m[nid]) m[nid] = f.path
    }
    return m
  }, [files])

  const metricsPathByNode = React.useMemo(() => {
    const m: Record<string, string> = {}
    for (const f of metricFiles) m[nodeOfFile(f)] = f.path
    return m
  }, [metricFiles])

  return { metricsByNode, confusionImageByNode, metricsPathByNode }
}
