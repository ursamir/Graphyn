import React from 'react'
import { Pause, Play, Square, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { CollapsibleJson, EmptyState, ErrorBanner, KeyValue, LoadingBlock, PageHeader, StatusBadge } from '../../components/ui'
import { formatExecutionLine } from '../../lib/format'

interface RunSummary {
  run_id: string
  status?: string
  created_at?: string
  [key: string]: unknown
}

export default function RunsView() {
  const focusRunId = useAppStore((s) => s.focusRunId)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const pushToast = useAppStore((s) => s.pushToast)

  const [runs, setRuns] = React.useState<RunSummary[] | null>(null)
  const [offset, setOffset] = React.useState(0)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<Record<string, unknown> | null>(null)
  const [status, setStatus] = React.useState<Record<string, unknown> | null>(null)
  const [debug, setDebug] = React.useState<Record<string, unknown> | null>(null)
  const [checkpoints, setCheckpoints] = React.useState<string[]>([])
  const [samples, setSamples] = React.useState<unknown>(null)
  const [artifacts, setArtifacts] = React.useState<unknown>(null)
  const [provenance, setProvenance] = React.useState<unknown>(null)
  const [panel, setPanel] = React.useState<'logs' | 'debug' | 'checkpoints' | 'artifacts' | 'provenance'>('logs')
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
    setArtifacts(null)
    setProvenance(null)
    setError(null)
    try {
      const [d, st, dbg, cps, arts, prov] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${id}`),
        apiJson<Record<string, unknown>>(`/runs/${id}/status`).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${id}/debug-report`).catch(() => null),
        apiJson<string[]>(`/runs/${id}/checkpoints`).catch(() => []),
        apiJson(`/runs/${id}/artifacts`).catch(() => []),
        apiJson(`/runs/${id}/provenance`).catch(() => null),
      ])
      setDetail(d)
      setStatus(st)
      setDebug(dbg)
      setCheckpoints(Array.isArray(cps) ? cps : [])
      setArtifacts(arts)
      setProvenance(prov)
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

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-200 p-4">
        <PageHeader
          title="Runs"
          description="History, live status, and logs for pipeline executions."
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
            description="Execute a graph from Builder to see history here."
            action={
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
            }
          />
        ) : (
          <ul className="space-y-2">
            {runs.map((r) => (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => void open(r.run_id)}
                  className={`w-full rounded-xl border px-3 py-2 text-left ${
                    selected === r.run_id
                      ? 'border-accent-400 bg-accent-50'
                      : 'border-ink-200 bg-white hover:bg-ink-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-mono text-xs">{r.run_id}</div>
                    <StatusBadge status={String(r.status ?? 'unknown')} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-500">{r.created_at ?? '—'}</div>
                </button>
              </li>
            ))}
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

      <div className="overflow-y-auto p-4 space-y-3">
        {!selected ? (
          <EmptyState title="Select a run" description="Inspect logs, checkpoints, artifacts, and control active runs." />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={runStatus} />
              {status?.progress_pct != null && (
                <span className="text-xs text-ink-500">{String(status.progress_pct)}%</span>
              )}
              {status?.current_node != null && (
                <span className="font-mono text-xs text-ink-500">{String(status.current_node)}</span>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
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
                <button type="button" className="btn-danger" onClick={() => void control(selected, 'cancel')}>
                  <Square className="h-3.5 w-3.5" /> Cancel
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1">
              {(['logs', 'debug', 'checkpoints', 'artifacts', 'provenance'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  className={panel === p ? 'btn-primary' : 'btn-secondary'}
                  onClick={() => setPanel(p)}
                >
                  {p}
                </button>
              ))}
            </div>
            {panel === 'logs' && (
              <div className="max-h-[28rem] overflow-auto rounded-xl bg-ink-950 p-3 font-mono text-[11px] text-ink-100">
                {logs.length === 0 ? (
                  <div className="text-ink-500">No logs.</div>
                ) : (
                  logs.map((l, i) => {
                    const raw = typeof l.message === 'string' ? l.message : JSON.stringify(l)
                    const line = formatExecutionLine(raw)
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
            {panel === 'artifacts' && <KeyValue data={artifacts} empty="No artifacts for this run." />}
            {panel === 'provenance' && <KeyValue data={provenance} empty="No provenance." />}
          </>
        )}
      </div>
    </div>
  )
}
