import React from 'react'
import { FlaskConical, GitBranch, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import {
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatLocaleDateTime, prettyScalar, shortRunId } from '../../lib/format'

type ExperimentRun = {
  run_id: string
  status?: string
  created_at?: string | null
  graph_name?: string | null
  parameters?: Record<string, unknown>
  metrics?: Record<string, unknown>
  tags?: unknown[]
}

type ExperimentBlock = {
  experiment_name: string
  runs: ExperimentRun[]
}

type ComparePayload = {
  run_ids: string[]
  missing_run_ids?: string[]
  param_keys: string[]
  metric_keys: string[]
  runs: Array<ExperimentRun & { experiment_name?: string }>
}

const PREFERRED_METRICS = ['accuracy', 'loss', 'val_accuracy', 'val_loss', 'f1', 'precision', 'recall']

function metricColumns(runs: ExperimentRun[]): string[] {
  const keys = new Set<string>()
  for (const r of runs) {
    Object.keys(r.metrics || {}).forEach((k) => keys.add(k))
  }
  const preferred = PREFERRED_METRICS.filter((k) => keys.has(k))
  const rest = [...keys].filter((k) => !preferred.includes(k)).sort()
  const ordered = [...preferred, ...rest]
  return ordered.filter((k) =>
    runs.some((r) => {
      const v = r.metrics?.[k]
      if (v == null) return false
      if (typeof v === 'string' && !v.trim()) return false
      if (Array.isArray(v) && v.length === 0) return false
      return true
    }),
  )
}

function fmtMetric(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (Number.isInteger(value)) return String(value)
    const s = value.toFixed(4)
    return s.replace(/0+$/, '').replace(/\.$/, '')
  }
  if (Array.isArray(value) && value.length && typeof value[value.length - 1] === 'number') {
    return fmtMetric(value[value.length - 1])
  }
  return prettyScalar(value)
}

function valuesDiffer(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) !== JSON.stringify(b)
}


function parseExperimentsHash(): string[] {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return []
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  const collected: string[] = []
  for (const key of ['run_id', 'run_ids']) {
    for (const val of params.getAll(key)) {
      for (const part of val.split(',')) {
        const id = part.trim()
        if (id && !collected.includes(id)) collected.push(id)
      }
    }
  }
  return collected
}

export default function ExperimentsView() {
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const setView = useAppStore((s) => s.setView)
  const pushToast = useAppStore((s) => s.pushToast)

  const [blocks, setBlocks] = React.useState<ExperimentBlock[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [selectedExp, setSelectedExp] = React.useState<string | null>(null)
  const [selectedIds, setSelectedIds] = React.useState<string[]>(() => parseExperimentsHash().slice(0, 5))
  const [compare, setCompare] = React.useState<ComparePayload | null>(null)
  const [compareLoading, setCompareLoading] = React.useState(false)

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const data = await apiJson<ExperimentBlock[]>('/experiments')
      const list = Array.isArray(data) ? data : []
      setBlocks(list)
      setSelectedExp((prev) => {
        if (prev && list.some((b) => b.experiment_name === prev)) return prev
        return list[0]?.experiment_name ?? null
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      pushToast(msg, 'error')
    } finally {
      setLoading(false)
    }
  }, [pushToast])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  React.useEffect(() => {
    const apply = () => {
      const ids = parseExperimentsHash().slice(0, 5)
      setSelectedIds((prev) => {
        if (ids.join(',') === prev.join(',')) return prev
        // External deep-link / Compare handoff — adopt hash ids when present.
        if (ids.length) return ids
        return prev
      })
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])

  // Write selection into the hash without dispatching hashchange (avoid echo loops).
  React.useEffect(() => {
    const params = new URLSearchParams()
    if (selectedIds.length === 1) params.set('run_id', selectedIds[0])
    else if (selectedIds.length > 1) params.set('run_id', selectedIds.join(','))
    const qs = params.toString()
    const next = qs ? `#/experiments?${qs}` : '#/experiments'
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [selectedIds])

  const active =
    blocks?.find((b) => b.experiment_name === selectedExp) ??
    (blocks && blocks.length === 1 ? blocks[0] : null)

  const flatFew = (blocks?.length ?? 0) <= 1
  const tableRuns: ExperimentRun[] = flatFew
    ? (blocks ?? []).flatMap((b) => b.runs)
    : active?.runs ?? []

  const columns = React.useMemo(() => metricColumns(tableRuns), [tableRuns])

  const toggleSelect = (runId: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(runId)) return prev.filter((id) => id !== runId)
      if (prev.length >= 5) {
        pushToast('Select at most 5 runs to compare', 'info')
        return prev
      }
      return [...prev, runId]
    })
  }

  const runCompare = async () => {
    if (selectedIds.length < 2) {
      pushToast('Select 2–5 runs to compare', 'info')
      return
    }
    setCompareLoading(true)
    setError(null)
    try {
      const data = await apiJson<ComparePayload>('/experiments/compare', {
        query: { run_ids: selectedIds.join(',') },
      })
      setCompare(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      pushToast(msg, 'error')
    } finally {
      setCompareLoading(false)
    }
  }

  const clearCompare = () => {
    setCompare(null)
    setSelectedIds([])
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Experiments"
        description="Compare params and metrics across runs."
        actions={
          <div className="flex items-center gap-2">
            {selectedIds.length >= 2 && (
              <button type="button" className="btn-primary" onClick={() => void runCompare()} disabled={compareLoading}>
                Compare ({selectedIds.length})
              </button>
            )}
            {compare && (
              <button type="button" className="btn-secondary" onClick={clearCompare}>
                Clear
              </button>
            )}
            <button type="button" className="btn-secondary" onClick={() => void refresh()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}

      {loading && blocks === null ? (
        <LoadingBlock label="Loading experiments…" />
      ) : !blocks || blocks.length === 0 || tableRuns.length === 0 ? (
        <EmptyState
          title="No experiments yet"
          description="Compare starts from Runs — execute a pipeline, then return here to pick runs and diff params/metrics."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  setView('runs')
                  window.history.replaceState(null, '', '#/runs')
                }}
              >
                Open Runs
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setView('builder')
                  window.history.replaceState(null, '', '#/builder')
                }}
              >
                Open Builder
              </button>
            </div>
          }
        />
      ) : (
        <div className={`grid gap-4 ${flatFew ? 'grid-cols-1' : 'lg:grid-cols-[220px_1fr]'}`}>
          {!flatFew && (
            <aside className="rounded-2xl border border-ink-200/80 bg-white shadow-sm overflow-hidden h-fit">
              <div className="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-ink-500 border-b border-ink-100">
                Experiments
              </div>
              <ul className="py-1">
                {blocks.map((b) => {
                  const activeRow = b.experiment_name === selectedExp
                  return (
                    <li key={b.experiment_name}>
                      <button
                        type="button"
                        onClick={() => setSelectedExp(b.experiment_name)}
                        className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2 ${
                          activeRow ? 'bg-ink-50 text-ink-900 font-medium' : 'text-ink-600 hover:bg-ink-50/70'
                        }`}
                      >
                        <span className="truncate flex items-center gap-2">
                          <FlaskConical className="h-3.5 w-3.5 shrink-0 opacity-60" />
                          {b.experiment_name}
                        </span>
                        <span className="text-[11px] text-ink-400 tabular-nums">{b.runs.length}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </aside>
          )}

          <div className="space-y-4 min-w-0">
            <div className="overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-ink-100 text-left text-[11px] uppercase tracking-wide text-ink-500">
                      <th className="px-3 py-2.5 w-8" />
                      <th className="px-3 py-2.5 font-medium">Run</th>
                      <th className="px-3 py-2.5 font-medium">Status</th>
                      <th className="px-3 py-2.5 font-medium">Graph</th>
                      <th className="px-3 py-2.5 font-medium">Created</th>
                      {columns.map((k) => (
                        <th key={k} className="px-3 py-2.5 font-medium tabular-nums">
                          {k}
                        </th>
                      ))}
                      <th className="px-3 py-2.5 font-medium">Open</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRuns.map((r) => {
                      const checked = selectedIds.includes(r.run_id)
                      return (
                        <tr
                          key={r.run_id}
                          className={`border-b border-ink-50 last:border-0 hover:bg-ink-50/50 ${
                            checked ? 'bg-amber-50/40' : ''
                          }`}
                        >
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleSelect(r.run_id)}
                              aria-label={`Select ${r.run_id}`}
                              className="rounded border-ink-300"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              className="font-mono text-xs text-ink-800 hover:underline"
                              onClick={() => openRun(r.run_id)}
                              title={r.run_id}
                            >
                              {shortRunId(r.run_id)}
                            </button>
                          </td>
                          <td className="px-3 py-2">
                            <StatusBadge status={r.status || 'unknown'} />
                          </td>
                          <td className="px-3 py-2 text-ink-600 truncate max-w-[10rem]">
                            {r.graph_name || '—'}
                          </td>
                          <td className="px-3 py-2 text-ink-500 whitespace-nowrap text-xs">
                            {formatLocaleDateTime(r.created_at)}
                          </td>
                          {columns.map((k) => (
                            <td key={k} className="px-3 py-2 tabular-nums text-ink-800">
                              {fmtMetric(r.metrics?.[k])}
                            </td>
                          ))}
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                className="btn-primary !px-2 !py-1 text-xs"
                                onClick={() => openRun(r.run_id)}
                              >
                                Open
                              </button>
                              <button
                                type="button"
                                className="btn-quiet !px-2 !py-1"
                                onClick={() => openTrace({ runId: r.run_id })}
                                title="Trace lineage"
                                aria-label="Trace lineage"
                              >
                                <GitBranch className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="px-3 py-2 text-[11px] text-ink-400 border-t border-ink-50">
                Select 2–5 runs to Compare. Open goes to Runs; Trace is secondary.
              </div>
            </div>

            {compare && (
              <div className="rounded-2xl border border-ink-200/80 bg-white shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-ink-100 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-ink-900">Compare</div>
                    <div className="text-xs text-ink-500">
                      Side-by-side params & metrics — differing cells highlighted
                    </div>
                  </div>
                  {compare.missing_run_ids && compare.missing_run_ids.length > 0 && (
                    <div className="text-xs text-amber-700">
                      Missing: {compare.missing_run_ids.join(', ')}
                    </div>
                  )}
                </div>
                <div className="overflow-x-auto">
                  <CompareTable
                    title="Parameters"
                    keys={compare.param_keys}
                    runs={compare.runs}
                    getter={(r, k) => r.parameters?.[k]}
                    onOpenRun={openRun}
                  />
                  <CompareTable
                    title="Metrics"
                    keys={compare.metric_keys}
                    runs={compare.runs}
                    getter={(r, k) => r.metrics?.[k]}
                    format={fmtMetric}
                    onOpenRun={openRun}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function CompareTable({
  title,
  keys,
  runs,
  getter,
  format,
  onOpenRun,
}: {
  title: string
  keys: string[]
  runs: Array<ExperimentRun & { experiment_name?: string }>
  getter: (r: ExperimentRun, key: string) => unknown
  format?: (v: unknown) => string
  onOpenRun?: (runId: string) => void
}) {
  const fmt = format ?? ((v: unknown) => (v == null ? '—' : prettyScalar(v)))
  if (!keys.length) {
    return (
      <div className="px-4 py-3 text-xs text-ink-400 border-b border-ink-50 last:border-0">
        No {title.toLowerCase()} logged for selected runs.
      </div>
    )
  }
  return (
    <div className="border-b border-ink-50 last:border-0">
      <div className="px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-ink-500 bg-ink-50/40">
        {title}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] text-ink-500">
            <th className="px-4 py-2 font-medium w-40">Key</th>
            {runs.map((r) => (
              <th key={r.run_id} className="px-3 py-2 font-mono font-normal text-xs" title={r.run_id}>
                {onOpenRun ? (
                  <button
                    type="button"
                    className="hover:underline hover:text-accent-800"
                    onClick={() => onOpenRun(r.run_id)}
                  >
                    {shortRunId(r.run_id)}
                  </button>
                ) : (
                  shortRunId(r.run_id)
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const vals = runs.map((r) => getter(r, k))
            const differs = vals.some((v) => valuesDiffer(v, vals[0]))
            return (
              <tr key={k} className="border-t border-ink-50">
                <td className="px-4 py-1.5 text-ink-600 font-mono text-xs">{k}</td>
                {vals.map((v, i) => (
                  <td
                    key={runs[i].run_id}
                    className={`px-3 py-1.5 tabular-nums ${
                      differs ? 'bg-amber-50 text-amber-950' : 'text-ink-800'
                    }`}
                  >
                    {fmt(v)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
