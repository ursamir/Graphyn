import React from 'react'
import { Archive, Database, FlaskConical, FolderKanban, GitBranch, Download, Pause, Play, RefreshCw, Workflow } from 'lucide-react'
import { apiJson, apiUrl, downloadOutputFile, fetchOutputBlobUrl, getApiToken } from '../../api/client'
import type { GraphIR } from '../../types/graph'
import { fetchRunGraph } from '../../lib/runGraph'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, CollapsibleJson, EmptyState, ErrorBanner, KeyValue, LoadingBlock, PageHeader, SlimProgress, StatusBadge } from '../../components/ui'
import {
  formatExecutionLine,
  formatLocaleDateTime,
  formatRelativeTime,
  formatRunMetric,
  humanizeTemplateName,
  humanNodeLabel,
  shortRunId,
  skipConsecutiveByText,
} from '../../lib/format'

interface RunSummary {
  run_id: string
  status?: string
  created_at?: string
  graph_name?: string
  artifacts_dir?: string
  metrics?: Record<string, unknown>
  [key: string]: unknown
}

interface OutputFile {
  name: string
  path: string
  size: number
  kind: string
}

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function isPreviewPlot(file: OutputFile): boolean {
  if (file.kind === "dir") return false
  const n = file.name.toLowerCase()
  return (
    n.endsWith(".png") &&
    (n.includes("confusion_matrix") || n.includes("roc") || n.includes("training_curves"))
  )
}

/** Runs stuck in RUNNING with no process heartbeat — warn after this age. */
const STALE_RUNNING_MS = 60 * 60 * 1000 // 1 hour

function runningAgeMs(createdAt?: string | null): number | null {
  if (!createdAt) return null
  const t = Date.parse(createdAt)
  if (!Number.isFinite(t)) return null
  return Date.now() - t
}

function isStaleRunning(status?: string | null, createdAt?: string | null): boolean {
  if (String(status || '').toLowerCase() !== 'running') return false
  const age = runningAgeMs(createdAt)
  return age != null && age >= STALE_RUNNING_MS
}

const PANEL_LABELS: Record<string, string> = {
  logs: 'Logs',
  debug: 'Debug',
  checkpoints: 'Checkpoints',
  artifacts: 'Files',
}



export default function RunsView() {
  const focusRunId = useAppStore((s) => s.focusRunId)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const pushToast = useAppStore((s) => s.pushToast)
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openExperiments = useAppStore((s) => s.openExperiments)
  const openProjects = useAppStore((s) => s.openProjects)
  const openData = useAppStore((s) => s.openData)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)

  const [runs, setRuns] = React.useState<RunSummary[] | null>(null)
  const [offset, setOffset] = React.useState(0)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<Record<string, unknown> | null>(null)
  const [status, setStatus] = React.useState<Record<string, unknown> | null>(null)
  const [debug, setDebug] = React.useState<Record<string, unknown> | null>(null)
  const [checkpoints, setCheckpoints] = React.useState<string[]>([])
  const [samples, setSamples] = React.useState<unknown>(null)
  const [outputFiles, setOutputFiles] = React.useState<OutputFile[]>([])
  const [previewUrls, setPreviewUrls] = React.useState<Record<string, string>>({})
  const [panel, setPanel] = React.useState<'logs' | 'debug' | 'checkpoints' | 'artifacts'>('logs')
  const [error, setError] = React.useState<string | null>(null)
  const limit = 50

  const load = React.useCallback(async () => {
    setError(null)
    try {
      setRuns(await apiJson<RunSummary[]>('/runs', { query: { limit, offset } }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setRuns([])
    }
  }, [offset])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    const id = focusRunId || lastRunId
    if (id) void open(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRunId])

  const open = async (id: string) => {
    setSelected(id)
    setDetail(null)
    setDebug(null)
    setSamples(null)
    setOutputFiles([])
    setError(null)
    try {
      const [d, st, dbg, cps, outs] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${id}`),
        apiJson<Record<string, unknown>>(`/runs/${id}/status`).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${id}/debug-report`).catch(() => null),
        apiJson<string[]>(`/runs/${id}/checkpoints`).catch(() => []),
        apiJson<OutputFile[]>(`/runs/${id}/outputs`).catch(() => []),
      ])
      setDetail(d)
      setStatus(st)
      setDebug(dbg)
      setCheckpoints(Array.isArray(cps) ? cps : [])
      setOutputFiles(Array.isArray(outs) ? outs : [])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  React.useEffect(() => {
    if (!selected) return
    const metaStatus = (detail?.meta as { status?: string } | undefined)?.status
    const s = String(status?.status ?? metaStatus ?? '')
    if (!['running', 'paused'].includes(s.toLowerCase())) return
    const t = setInterval(() => {
      void apiJson<Record<string, unknown>>(`/runs/${selected}/status`)
        .then(setStatus)
        .catch(() => undefined)
    }, 2000)
    return () => clearInterval(t)
  }, [selected, status?.status, detail])

  React.useEffect(() => {
    const plots = outputFiles.filter(isPreviewPlot)
    let cancelled = false
    const created: string[] = []
    void (async () => {
      const next: Record<string, string> = {}
      for (const file of plots) {
        try {
          const url = await fetchOutputBlobUrl(file.path)
          created.push(url)
          if (cancelled) {
            URL.revokeObjectURL(url)
            continue
          }
          next[file.path] = url
        } catch {
          /* preview is optional */
        }
      }
      if (!cancelled) setPreviewUrls(next)
    })()
    return () => {
      cancelled = true
      created.forEach((u) => URL.revokeObjectURL(u))
    }
  }, [outputFiles])

  const downloadFile = async (file: OutputFile) => {
    try {
      await downloadOutputFile(file.path, file.name)
      pushToast(`Downloading ${file.name}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const downloadZip = async () => {
    if (!selected) return
    try {
      const url = apiUrl(`/runs/${selected}/outputs/zip`)
      const token = getApiToken()
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error(`Download failed (${res.status})`)
      const blob = await res.blob()
      const obj = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = obj
      a.download = `${selected}-outputs.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(obj)
      pushToast('Zip download started', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const control = async (id: string, action: 'pause' | 'resume' | 'cancel') => {
    try {
      await apiJson(`/runs/${id}/${action}`, { method: 'POST' })
      pushToast(`${action} requested`, 'success')
      await load()
      await open(id)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const promote = async () => {
    if (!selected) return
    try {
      await apiJson(`/runs/${selected}/promote`, { method: 'POST' })
      pushToast('This run is now latest', 'success')
      await load()
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const deleteRun = async () => {
    if (!selected) return
    try {
      await apiJson(`/runs/${selected}`, { method: 'DELETE' })
      pushToast(`Deleted run ${selected}`, 'success')
      setSelected(null)
      setDetail(null)
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const loadCheckpointSamples = async (nodeId: string) => {
    if (!selected) return
    try {
      setSamples(
        await apiJson(`/runs/${selected}/checkpoints/${encodeURIComponent(nodeId)}/samples`, {
          query: { n: 10 },
        }),
      )
      setPanel('checkpoints')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const runStatus = String(
    status?.status ??
      (detail?.meta as { status?: string } | undefined)?.status ??
      runs?.find((r) => r.run_id === selected)?.status ??
      'unknown',
  )
  const logs = Array.isArray(detail?.logs) ? (detail!.logs as Array<Record<string, unknown>>) : []
  const formattedLogs = skipConsecutiveByText(
    logs.map((l, i) => {
      const raw = typeof l.message === 'string' ? l.message : JSON.stringify(l)
      const line = formatExecutionLine(raw)
      return { i, l, line }
    }),
    (row) => row.line.text,
  )

  const selectedSummary = runs?.find((r) => r.run_id === selected)
  const graphName = String(
    selectedSummary?.graph_name ??
      (detail?.meta as { graph_name?: string } | undefined)?.graph_name ??
      detail?.graph_name ??
      '',
  ).trim()
  const embeddedGraph = (detail?.graph ?? (detail?.meta as { graph?: unknown } | undefined)?.graph) as
    | GraphIR
    | undefined
  const canOpenGraph = Boolean(
    selected &&
      (graphName ||
        (embeddedGraph && Array.isArray(embeddedGraph.nodes) && Array.isArray(embeddedGraph.edges))),
  )

  const openGraphInBuilder = async () => {
    if (!selected) return
    try {
      if (embeddedGraph && Array.isArray(embeddedGraph.nodes) && Array.isArray(embeddedGraph.edges)) {
        loadGraphIntoBuilder(embeddedGraph)
        pushToast('Opened graph in Builder', 'success')
        return
      }
      const graph = await fetchRunGraph(selected, graphName || null)
      if (!graph) {
        pushToast(graphName ? `Graph not found for ${graphName}` : 'Graph not available for this run', 'info')
        return
      }
      loadGraphIntoBuilder(graph)
      pushToast(
        graphName ? `Opened ${humanizeTemplateName(graphName)} in Builder` : 'Opened graph in Builder',
        'success',
      )
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-200/70 bg-white/40 p-5">
        <PageHeader
          title="Runs"
          description="Execution history, logs, and ops controls."
          actions={
            <button type="button" onClick={() => void load()} className="btn-secondary">
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          }
        />
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {runs === null ? (
          <LoadingBlock />
        ) : runs.length === 0 ? (
          <EmptyState
            title="No runs yet"
            description="Run a graph from Builder to create an execution session here. Trace is for lineage/provenance deep-dive; Experiments compares metrics."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    useAppStore.getState().setView('builder')
                    window.history.replaceState(null, '', '#/builder')
                  }}
                >
                  Open Builder
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    useAppStore.getState().setView('templates')
                    window.history.replaceState(null, '', '#/templates')
                  }}
                >
                  Browse Templates
                </button>
              </div>
            }
          />
        ) : (
          <ul className="space-y-1.5">
            {runs.map((r) => {
              const metric = formatRunMetric(r.metrics)
              return (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => void open(r.run_id)}
                  className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 rounded-xl border px-3 py-2.5 text-left shadow-sm transition sm:grid-cols-[minmax(0,1.4fr)_auto_minmax(4rem,auto)_auto_auto] ${
                    selected === r.run_id
                      ? 'border-accent-200 bg-accent-50/80 shadow-soft'
                      : 'border-ink-200/70 bg-white hover:border-ink-300 hover:bg-ink-50/80'
                  }`}
                >
                  <div className="truncate text-sm font-medium text-ink-900">
                    {r.graph_name ? humanizeTemplateName(String(r.graph_name)) : 'Pipeline'}
                  </div>
                  <div className="flex items-center gap-1.5 justify-self-end">
                    <StatusBadge status={String(r.status ?? 'unknown')} />
                    {isStaleRunning(r.status, r.created_at) && (
                      <span
                        className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900"
                        title={`Still RUNNING after ${formatRelativeTime(r.created_at)} — may be a zombie journal`}
                      >
                        Stale
                      </span>
                    )}
                  </div>
                  <div className="hidden truncate text-[11px] text-ink-600 sm:block">
                    {metric ?? ''}
                  </div>
                  <div
                    className="hidden text-[11px] text-ink-500 sm:block"
                    title={formatLocaleDateTime(r.created_at)}
                  >
                    {formatRelativeTime(r.created_at)}
                  </div>
                  <div className="font-mono text-[11px] text-ink-400" title={r.run_id}>
                    {shortRunId(r.run_id)}
                  </div>
                  <div className="col-span-2 flex items-center gap-2 text-[11px] text-ink-500 sm:hidden">
                    {metric ? <span>{metric}</span> : null}
                    <span title={formatLocaleDateTime(r.created_at)}>{formatRelativeTime(r.created_at)}</span>
                  </div>
                </button>
              </li>
            )})}
          </ul>
        )}
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - limit))}
          >
            Prev
          </button>
          <button type="button" className="btn-secondary" onClick={() => setOffset((o) => o + limit)}>
            Next
          </button>
        </div>
      </div>

      <div className="overflow-y-auto space-y-4 p-5">
        {!selected ? (
          <EmptyState
            title="Select a run"
            description="This run's logs, files, and ops controls. Open View lineage for provenance deep-dive."
            action={
              runs && runs.length > 0 ? (
                <button type="button" className="btn-secondary" onClick={() => void open(runs[0].run_id)}>
                  Open latest run
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    useAppStore.getState().setView('builder')
                    window.history.replaceState(null, '', '#/builder')
                  }}
                >
                  Open Builder
                </button>
              )
            }
          />
        ) : (
          <>
            <div className="rounded-2xl border border-ink-200/80 bg-white px-4 py-3 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge status={runStatus} />
                {isStaleRunning(runStatus, selectedSummary?.created_at ?? (detail?.meta as { created_at?: string } | undefined)?.created_at) && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-900">
                    Stale RUNNING
                  </span>
                )}
                {status?.progress_pct != null && (
                  <SlimProgress pct={Number(status.progress_pct)} />
                )}
                {status?.current_node != null && (
                  <span className="text-sm text-ink-600">
                    Current node{' '}
                    <span className="font-medium text-ink-900">{humanNodeLabel(String(status.current_node))}</span>
                  </span>
                )}
              </div>
              {(() => {
                const place = (detail?.meta as { distributed_node_workers?: Record<string, string> } | undefined)
                  ?.distributed_node_workers
                if (!place || typeof place !== 'object') return null
                const entries = Object.entries(place)
                if (entries.length === 0) return null
                return (
                  <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-ink-600">
                    <span className="font-medium text-ink-500">Workers</span>
                    {entries.map(([nid, wid]) => (
                      <span
                        key={nid}
                        className="rounded-md bg-ink-100 px-1.5 py-0.5 font-mono text-ink-800"
                        title={`Node ${nid}`}
                      >
                        {humanNodeLabel(nid)} → {wid}
                      </span>
                    ))}
                  </div>
                )
              })()}
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openTrace({ runId: selected })}
              >
                <GitBranch className="h-3.5 w-3.5" /> View lineage
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openArtifacts({ runId: selected })}
              >
                <Archive className="h-3.5 w-3.5" /> Browse artifacts
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openExperiments({ runIds: [selected] })}
              >
                <FlaskConical className="h-3.5 w-3.5" /> Compare
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openProjects()}
              >
                <FolderKanban className="h-3.5 w-3.5" /> Projects
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openData({ mode: 'outputs' })}
              >
                <Database className="h-3.5 w-3.5" /> Data
              </button>
              {canOpenGraph && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => void openGraphInBuilder()}
                >
                  <Workflow className="h-3.5 w-3.5" /> Open in Builder
                </button>
              )}
              {['running'].includes(runStatus.toLowerCase()) && (
                <button type="button" className="btn-secondary" onClick={() => void control(selected, 'pause')}>
                  <Pause className="h-3.5 w-3.5" /> Pause
                </button>
              )}
              {['paused'].includes(runStatus.toLowerCase()) && (
                <button type="button" className="btn-secondary" onClick={() => void control(selected, 'resume')}>
                  <Play className="h-3.5 w-3.5" /> Resume
                </button>
              )}
              {['running', 'paused'].includes(runStatus.toLowerCase()) && (
                <ConfirmButton
                  label={
                    isStaleRunning(
                      runStatus,
                      selectedSummary?.created_at ??
                        (detail?.meta as { created_at?: string } | undefined)?.created_at,
                    )
                      ? 'Cancel stale run'
                      : 'Cancel run'
                  }
                  confirmLabel="Confirm cancel"
                  danger
                  onConfirm={() => void control(selected, 'cancel')}
                />
              )}
              {!['running', 'paused'].includes(runStatus.toLowerCase()) && (
                <ConfirmButton
                  label="Delete run"
                  confirmLabel={`Delete ${selected}?`}
                  danger
                  onConfirm={() => void deleteRun()}
                />
              )}
            </div>
            {isStaleRunning(
              runStatus,
              selectedSummary?.created_at ??
                (detail?.meta as { created_at?: string } | undefined)?.created_at,
            ) && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-950">
                <div className="font-medium">This run has been RUNNING for a long time</div>
                <p className="mt-1 text-xs text-amber-900/90">
                  Started {formatRelativeTime(selectedSummary?.created_at ?? (detail?.meta as { created_at?: string } | undefined)?.created_at)}
                  {logs.length === 0 ? ' and has no logs' : ''}. The API still reports{' '}
                  <span className="font-semibold">running</span> — often a zombie journal after a
                  crashed worker. Use <span className="font-semibold">Cancel run</span> (click
                  twice to confirm) to mark it terminal, or delete after it leaves RUNNING.
                </p>
              </div>
            )}
            <div className="flex flex-wrap gap-1 rounded-xl bg-ink-100/70 p-1">
              {(['logs', 'debug', 'checkpoints', 'artifacts'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  className={panel === p ? 'tab-pill tab-pill-on' : 'tab-pill'}
                  onClick={() => setPanel(p)}
                >
                  {PANEL_LABELS[p]}
                </button>
              ))}
            </div>
            {panel === 'logs' && (
              <div className="max-h-[28rem] overflow-auto rounded-2xl bg-ink-950 p-4 font-mono text-[11px] leading-5 text-ink-100 shadow-soft">
                {logs.length === 0 ? (
                  <div className="text-ink-500">No logs.</div>
                ) : (
                  formattedLogs.map(({ i, l, line }) => {
                    const failed = line.level === 'error' || String(l.level).toUpperCase() === 'ERROR'
                    return (
                      <div key={i} className={failed ? 'text-rose-300' : ''}>
                        {line.text}
                      </div>
                    )
                  })
                )}
              </div>
            )}
            {panel === 'debug' && <KeyValue data={debug} empty="No debug report." />}
            {panel === 'checkpoints' && (
              <div className="space-y-2">
                {checkpoints.length === 0 ? (
                  <div className="text-sm text-ink-500">No checkpoints.</div>
                ) : (
                  checkpoints.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className="block w-full rounded-lg border border-ink-200 px-3 py-2 text-left text-sm hover:bg-ink-50"
                      onClick={() => void loadCheckpointSamples(c)}
                    >
                      {c}
                    </button>
                  ))
                )}
                {samples != null && <CollapsibleJson value={samples} label="Samples" />}
              </div>
            )}
            {panel === 'artifacts' && (
              <div className="space-y-3">
                <p className="text-xs text-ink-500">
                  This run&apos;s downloadable outputs. Browse the Artifacts library for cross-run search; open Trace for backtrack.
                </p>
                {(() => {
                  const artifactsDir =
                    (typeof detail?.artifacts_dir === 'string' && detail.artifacts_dir) ||
                    ((detail?.meta as { artifacts_dir?: string } | undefined)?.artifacts_dir)
                  const displayPath = typeof artifactsDir === 'string'
                    ? artifactsDir.replace(/^workspace\//, '')
                    : null
                  const isLatest = detail?.is_latest === true
                  return (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        {displayPath ? (
                          <div className="truncate font-mono text-[11px] text-ink-500">{displayPath}</div>
                        ) : null}
                        {isLatest ? (
                          <span className="mt-1 inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                            Latest
                          </span>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {!isLatest && (
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => void promote()}
                          >
                            Use as latest
                          </button>
                        )}
                        {outputFiles.length > 0 && (
                          <button type="button" className="btn-secondary" onClick={() => void downloadZip()}>
                            <Download className="h-3.5 w-3.5" /> Download all
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })()}
                {outputFiles.length === 0 ? (
                  <div className="text-sm text-ink-500">No downloadable files for this run.</div>
                ) : (
                  <ul className="space-y-2">
                    {outputFiles.map((f) => (
                      <li key={`${f.path}-${f.name}`} className="rounded-xl border border-ink-200 bg-white px-3 py-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-ink-900">{f.name}</div>
                            <div className="truncate font-mono text-[10px] text-ink-400">{f.path}</div>
                            <div className="text-[11px] text-ink-500">
                              {f.kind} · {formatBytes(f.size)}
                            </div>
                          </div>
                          {f.kind !== 'dir' && (
                            <button type="button" className="btn-primary shrink-0" onClick={() => void downloadFile(f)}>
                              <Download className="h-3.5 w-3.5" /> Download
                            </button>
                          )}
                        </div>
                        {previewUrls[f.path] && (
                          <img
                            src={previewUrls[f.path]}
                            alt={f.name}
                            className="mt-2 max-h-64 w-full rounded-lg border border-ink-100 object-contain bg-ink-50"
                          />
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => openArtifacts({ runId: selected })}
                  >
                    <Archive className="h-3.5 w-3.5" /> Open in Artifacts
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => openTrace({ runId: selected })}
                  >
                    <GitBranch className="h-3.5 w-3.5" /> Trace lineage
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
