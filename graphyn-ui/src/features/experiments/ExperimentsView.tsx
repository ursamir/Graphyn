import React from 'react'
import { FlaskConical, GitBranch, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import {
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  NeedProjectPrompt,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import {
  formatLocaleDateTime,
  humanizeTemplateName,
  prettyScalar,
  shortRunId,
} from '../../lib/format'
import { MetricBars } from '../../components/MetricBars'
import { paths } from '../../routes/paths'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'

type ExperimentRun = {
  run_id: string
  status?: string
  created_at?: string | null
  graph_name?: string | null
  parameters?: Record<string, unknown>
  metrics?: Record<string, unknown>
  tags?: unknown[]
  code_hash?: string | null
  data_version?: string | null
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

function csvEscape(v: unknown): string {
  const s = v == null ? '' : String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function downloadCompareCsv(compare: ComparePayload) {
  const runs = compare.runs
  const lines: string[] = []
  const hasKeys = (compare.param_keys?.length || 0) + (compare.metric_keys?.length || 0) > 0
  if (!hasKeys) {
    lines.push(['run_id', 'status', 'graph_name', 'created_at'].map(csvEscape).join(','))
    for (const r of runs) {
      lines.push(
        [r.run_id, r.status || '', r.graph_name || '', r.created_at || ''].map(csvEscape).join(','),
      )
    }
  } else {
    const header = ['section', 'key', ...runs.map((r) => r.run_id)]
    lines.push(header.map(csvEscape).join(','))
    for (const k of compare.param_keys || []) {
      lines.push(
        ['parameters', k, ...runs.map((r) => prettyScalar(r.parameters?.[k]))].map(csvEscape).join(','),
      )
    }
    for (const k of compare.metric_keys || []) {
      lines.push(['metrics', k, ...runs.map((r) => fmtMetric(r.metrics?.[k]))].map(csvEscape).join(','))
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `compare-${runs.map((r) => r.run_id.slice(0, 8)).join('-') || 'runs'}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function runMetaField(r: ExperimentRun, key: 'code_hash' | 'data_version'): string | null {
  const direct = r[key]
  if (typeof direct === 'string' && direct.trim()) return direct.trim()
  const fromParams = r.parameters?.[key]
  if (typeof fromParams === 'string' && fromParams.trim()) return fromParams.trim()
  if (fromParams != null && typeof fromParams !== 'object') return String(fromParams)
  return null
}

function hasMetaColumn(runs: ExperimentRun[], key: 'code_hash' | 'data_version'): boolean {
  return runs.some((r) => !!runMetaField(r, key))
}


function parseExperimentsLocation(): string[] {
  const params = readSearchParams()
  const collected: string[] = []
  for (const key of ['ids', 'run_id', 'run_ids']) {
    for (const val of params.getAll(key)) {
      for (const part of val.split(',')) {
        const id = part.trim()
        if (id && !collected.includes(id)) collected.push(id)
      }
    }
  }
  return collected
}

export default function ExperimentsView({ embedded = false }: { embedded?: boolean }) {
  const openRun = useAppStore((s) => s.openRun)
  const openExperiments = useAppStore((s) => s.openExperiments)
  const setFocusRunsTab = useAppStore((s) => s.setFocusRunsTab)
  const pushToast = useAppStore((s) => s.pushToast)
  const activeProject = useAppStore((s) => s.activeProject)
  const openProjects = useAppStore((s) => s.openProjects)

  const [blocks, setBlocks] = React.useState<ExperimentBlock[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [selectedExp, setSelectedExp] = React.useState<string | null>(null)
  const [selectedIds, setSelectedIds] = React.useState<string[]>(() => parseExperimentsLocation().slice(0, 5))
  const [compare, setCompare] = React.useState<ComparePayload | null>(null)
  const [compareLoading, setCompareLoading] = React.useState(false)
  const compareRef = React.useRef<HTMLDivElement | null>(null)
  const autoComparedKey = React.useRef<string>('')

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const query: Record<string, string> = {}
      if (activeProject) query.project = activeProject
      const data = await apiJson<ExperimentBlock[]>('/experiments', { query })
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
  }, [pushToast, activeProject])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  React.useEffect(() => {
    const apply = () => {
      const ids = parseExperimentsLocation().slice(0, 5)
      setSelectedIds((prev) => {
        if (ids.join(',') === prev.join(',')) return prev
        // External deep-link / Compare handoff — adopt path ids when present.
        if (ids.length) return ids
        return prev
      })
    }
    apply()
    return onPathChange(apply)
  }, [])

  // Write selection into /workspaces/:W/runs/compare?ids= (path search).
  React.useEffect(() => {
    const W = activeProject?.trim()
    if (!W) return
    const base = paths.runsCompare(W).split('?')[0]
    const params: Record<string, string | undefined> = {}
    if (selectedIds.length === 1) params.ids = selectedIds[0]
    else if (selectedIds.length > 1) params.ids = selectedIds.join(',')
    replacePathSearch(params, base)
  }, [selectedIds, activeProject])

  const active =
    blocks?.find((b) => b.experiment_name === selectedExp) ??
    (blocks && blocks.length === 1 ? blocks[0] : null)

  const flatFew = (blocks?.length ?? 0) <= 1
  const tableRuns: ExperimentRun[] = flatFew
    ? (blocks ?? []).flatMap((b) => b.runs)
    : active?.runs ?? []

  const columns = React.useMemo(() => metricColumns(tableRuns), [tableRuns])
  const showCodeHash = React.useMemo(() => hasMetaColumn(tableRuns, 'code_hash'), [tableRuns])
  const showDataVersion = React.useMemo(() => hasMetaColumn(tableRuns, 'data_version'), [tableRuns])
  const compareShowCodeHash = React.useMemo(
    () => (compare ? hasMetaColumn(compare.runs, 'code_hash') : false),
    [compare],
  )
  const compareShowDataVersion = React.useMemo(
    () => (compare ? hasMetaColumn(compare.runs, 'data_version') : false),
    [compare],
  )

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

  const runCompare = React.useCallback(async (ids?: string[]) => {
    const target = ids ?? selectedIds
    if (target.length < 2) {
      pushToast('Select 2–5 runs to compare', 'info')
      return
    }
    setCompareLoading(true)
    setError(null)
    try {
      const data = await apiJson<ComparePayload>('/experiments/compare', {
        query: { run_ids: target.join(',') },
      })
      setCompare(data)
      // Ensure the panel is visible even when the runs table is long.
      requestAnimationFrame(() => {
        compareRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      pushToast(msg, 'error')
    } finally {
      setCompareLoading(false)
    }
  }, [selectedIds, pushToast])

  const clearCompare = () => {
    setCompare(null)
    setSelectedIds([])
    autoComparedKey.current = ''
  }

  // Deep-link handoff: if the URL already has 2+ run ids, run compare once.
  React.useEffect(() => {
    if (loading || !blocks) return
    const ids = parseExperimentsLocation().slice(0, 5)
    if (ids.length < 2) return
    const key = ids.join(',')
    if (autoComparedKey.current === key) return
    autoComparedKey.current = key
    void runCompare(ids)
  }, [loading, blocks, runCompare])

  if (!activeProject) {
    return (
      <NeedProjectPrompt
        onOpenProjects={() => {
          openProjects()
        }}
      />
    )
  }

  return (
    <div className={`relative h-full overflow-y-auto space-y-6 ${embedded ? 'p-5' : 'p-6'}`}>
      {!embedded ? (
        <>
          <PageHeader
            title="Compare runs"
            description="Deep link for cross-run metrics. Prefer Runs → Compare tab when a workspace is open."
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
                <button type="button" className="btn-quiet" onClick={() => void refresh()}>
                  <RefreshCw className="h-3.5 w-3.5" /> Refresh
                </button>
              </div>
            }
          />
          <div role="status" className="rounded-xl border border-ink-200 bg-ink-50/80 px-3 py-2 text-sm text-ink-700">
            This view is a deep link. For day-to-day work, use{' '}
            <button
              type="button"
              className="font-medium text-accent-800 hover:underline"
              onClick={() => {
                openExperiments(selectedIds.length ? { runIds: selectedIds } : {})
              }}
            >
              Runs → Compare
            </button>
            .
          </div>
        </>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-2">
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
          <button type="button" className="btn-quiet" onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>
      )}

      {selectedIds.length >= 2 ? (
        <div className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur">
          <span className="text-[13px] text-ink-700">
            {selectedIds.length} runs selected
          </span>
          <div className="flex gap-2">
            <button type="button" className="btn-primary" onClick={() => void runCompare()} disabled={compareLoading}>
              {compareLoading ? 'Comparing…' : `Compare (${selectedIds.length})`}
            </button>
            <button type="button" className="btn-secondary" onClick={clearCompare}>
              Clear
            </button>
          </div>
        </div>
      ) : null}

      {error && (
        <ErrorBanner
          message={error}
          onRetry={() => void (selectedIds.length >= 2 ? runCompare() : refresh())}
        />
      )}

      {selectedIds.length === 0 && tableRuns.length > 0 && !compare ? (
        <div role="status" className="rounded-xl border border-ink-200 bg-ink-50/80 px-3 py-2 text-sm text-ink-700">
          Select two runs from Runs → History (or tick two rows below) to compare.
        </div>
      ) : null}
      {selectedIds.length === 1 ? (
        <div
          role="status"
          className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950"
        >
          One run is preselected ({selectedIds[0].slice(0, 8)}…). Tick one more row in the table below, then Compare.
        </div>
      ) : null}

      {loading && blocks === null ? (
        <LoadingBlock label="Loading runs…" />
      ) : !blocks || blocks.length === 0 || tableRuns.length === 0 ? (
        <EmptyState
          title="Select two runs from History"
          description="Pick 2–5 runs in Runs → History, then compare params and metrics."
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                clearCompare()
                setFocusRunsTab('history')
                goView('runs')
              }}
            >
              Open Runs history
            </button>
          }
        />
      ) : (
        <div className={`grid gap-4 ${flatFew ? 'grid-cols-1' : 'lg:grid-cols-[220px_1fr]'}`}>
          {!flatFew && (
            <aside className="rounded-2xl border border-ink-200/80 bg-white shadow-sm overflow-hidden h-fit">
              <div className="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-ink-500 border-b border-ink-100">
                Groups
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
                      {showCodeHash ? (
                        <th className="px-3 py-2.5 font-medium">code_hash</th>
                      ) : null}
                      {showDataVersion ? (
                        <th className="px-3 py-2.5 font-medium">data_version</th>
                      ) : null}
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
                          <td className="px-3 py-2 text-ink-600 truncate max-w-[10rem]" title={r.graph_name || undefined}>
                            {r.graph_name ? humanizeTemplateName(String(r.graph_name)) : '—'}
                          </td>
                          <td className="px-3 py-2 text-ink-500 whitespace-nowrap text-xs">
                            {formatLocaleDateTime(r.created_at)}
                          </td>
                          {showCodeHash ? (
                            <td
                              className="px-3 py-2 font-mono text-[11px] text-ink-600 max-w-[8rem] truncate"
                              title={runMetaField(r, 'code_hash') || undefined}
                            >
                              {runMetaField(r, 'code_hash') || '—'}
                            </td>
                          ) : null}
                          {showDataVersion ? (
                            <td
                              className="px-3 py-2 font-mono text-[11px] text-ink-600 max-w-[8rem] truncate"
                              title={runMetaField(r, 'data_version') || undefined}
                            >
                              {runMetaField(r, 'data_version') || '—'}
                            </td>
                          ) : null}
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
                                onClick={() => openRun(r.run_id, { panel: 'lineage' })}
                                title="Open Lineage"
                                aria-label="Open Lineage"
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
                Select 2–5 runs to Compare. Open goes to Runs; Lineage opens from Runs panels.
              </div>
            </div>

            {compare && (
              <div
                ref={compareRef}
                className="rounded-2xl border border-ink-200/80 bg-white shadow-sm overflow-hidden"
              >
                <div className="px-4 py-3 border-b border-ink-100 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-ink-900">Compare</div>
                    <div className="text-xs text-ink-500">
                      Side-by-side params & metrics — differing cells highlighted
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {compare.missing_run_ids && compare.missing_run_ids.length > 0 && (
                      <div className="text-xs text-amber-700">
                        Missing: {compare.missing_run_ids.join(', ')}
                      </div>
                    )}
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        downloadCompareCsv(compare)
                        pushToast('Compare CSV downloaded', 'success')
                      }}
                    >
                      Export CSV
                    </button>
                  </div>
                </div>
                {(!compare.param_keys?.length && !compare.metric_keys?.length) || compare.runs.length === 0 ? (
                  <div className="px-4 py-6 space-y-2">
                    <div className="text-sm font-medium text-ink-800">
                      No metrics recorded for these runs
                    </div>
                    <p className="text-xs text-ink-500 max-w-xl">
                      Compare needs params/metrics from experiment.json, metrics.json, or graph
                      parameters. Graph names still appear in the table above when available.
                      {compare.runs.length > 0
                        ? ` Loaded ${compare.runs.length} run${compare.runs.length === 1 ? '' : 's'} with empty params/metrics.`
                        : ''}
                    </p>
                    <div className="overflow-x-auto pt-2">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-[11px] text-ink-500 border-b border-ink-100">
                            <th className="px-2 py-1.5 font-medium">Run</th>
                            <th className="px-2 py-1.5 font-medium">Status</th>
                            <th className="px-2 py-1.5 font-medium">Graph</th>
                            <th className="px-2 py-1.5 font-medium">Created</th>
                          </tr>
                        </thead>
                        <tbody>
                          {compare.runs.map((r) => (
                            <tr key={r.run_id} className="border-b border-ink-50 last:border-0">
                              <td className="px-2 py-1.5 font-mono text-xs">
                                <button
                                  type="button"
                                  className="hover:underline"
                                  onClick={() => openRun(r.run_id)}
                                >
                                  {shortRunId(r.run_id)}
                                </button>
                              </td>
                              <td className="px-2 py-1.5">
                                <StatusBadge status={r.status || 'unknown'} />
                              </td>
                              <td className="px-2 py-1.5 text-ink-600">
                                {r.graph_name ? humanizeTemplateName(String(r.graph_name)) : '—'}
                              </td>
                              <td className="px-2 py-1.5 text-xs text-ink-500 whitespace-nowrap">
                                {formatLocaleDateTime(r.created_at)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <CompareTable
                      title="Parameters"
                      keys={compare.param_keys}
                      runs={compare.runs}
                      getter={(r, k) => r.parameters?.[k]}
                      emptyLabel="No parameters recorded for these runs"
                      onOpenRun={openRun}
                    />
                    <CompareTable
                      title="Metrics"
                      keys={compare.metric_keys}
                      runs={compare.runs}
                      getter={(r, k) => r.metrics?.[k]}
                      format={fmtMetric}
                      emptyLabel="No metrics recorded for these runs"
                      onOpenRun={openRun}
                    />
                    {(compareShowCodeHash || compareShowDataVersion) && (
                      <CompareTable
                        title="Repro metadata"
                        keys={[
                          ...(compareShowCodeHash ? ['code_hash'] : []),
                          ...(compareShowDataVersion ? ['data_version'] : []),
                        ]}
                        runs={compare.runs}
                        getter={(r, k) =>
                          runMetaField(r, k as 'code_hash' | 'data_version')
                        }
                        emptyLabel="No code_hash / data_version on these runs"
                        onOpenRun={openRun}
                      />
                    )}
                    {compare.metric_keys.length > 0 ? (
                      <div className="grid gap-3 border-t border-ink-100 p-4 sm:grid-cols-2">
                        {compare.metric_keys.map((key) => {
                          const series = compare.runs
                            .map((r) => {
                              const raw = r.metrics?.[key]
                              const n = typeof raw === 'number' ? raw : Number(raw)
                              if (!Number.isFinite(n)) return null
                              return { label: shortRunId(r.run_id), value: n }
                            })
                            .filter((s): s is { label: string; value: number } => !!s)
                          if (series.length === 0) return null
                          return <MetricBars key={key} title={key} series={series} />
                        })}
                      </div>
                    ) : null}
                  </div>
                )}
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
  emptyLabel,
  onOpenRun,
}: {
  title: string
  keys: string[]
  runs: Array<ExperimentRun & { experiment_name?: string }>
  getter: (r: ExperimentRun, key: string) => unknown
  format?: (v: unknown) => string
  emptyLabel?: string
  onOpenRun?: (runId: string) => void
}) {
  const fmt = format ?? ((v: unknown) => (v == null ? '—' : prettyScalar(v)))
  if (!keys.length) {
    return (
      <div className="px-4 py-3 text-xs text-ink-500 border-b border-ink-50 last:border-0">
        {emptyLabel || `No ${title.toLowerCase()} recorded for these runs`}
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
