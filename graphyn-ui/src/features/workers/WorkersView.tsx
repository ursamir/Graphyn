import React from 'react'
import { ExternalLink, RefreshCw, Server, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { formatLocaleDateTime, formatRelativeTime } from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import { goView } from '../../routes/nav'
import {
  ConfirmButton,
  CopyableMono,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'

/** Same-host smoke command — see docs/SDK_AND_CLI.md `graphyn worker start`. */
const WORKER_START_CMD =
  'graphyn worker start --control-url http://127.0.0.1:8001/api/v1 --worker-id local-gpu --labels gpu --pool gpu-lab'

const DOCS_GETTING_STARTED_MODE_B =
  'https://github.com/ursamir/Graphyn/blob/main/docs/GETTING_STARTED.md#mode-b--multi-machine-control-plane--workers'

type WorkerRow = {
  worker_id: string
  status?: string
  labels?: string[]
  pools?: string[]
  plugins?: string[]
  heartbeat_at?: string
  active_jobs?: number
  resources?: {
    gpu?: boolean
    gpu_name?: string | null
    vram_mib_total?: number | null
    vram_mib_free?: number | null
    cpus?: number | null
  }
}

const STALE_AFTER_MS = 45_000

function isStale(heartbeatAt?: string): boolean {
  if (!heartbeatAt) return true
  const t = Date.parse(heartbeatAt)
  if (Number.isNaN(t)) return true
  return Date.now() - t > STALE_AFTER_MS
}

function gpuLabel(w: WorkerRow): string {
  const r = w.resources
  if (!r?.gpu) return 'CPU'
  const name = r.gpu_name ? String(r.gpu_name) : 'GPU'
  if (r.vram_mib_free != null && r.vram_mib_total != null) {
    return `${name} · ${r.vram_mib_free}/${r.vram_mib_total} MiB`
  }
  if (r.vram_mib_total != null) return `${name} · ${r.vram_mib_total} MiB`
  return name
}

function effectiveStatus(w: WorkerRow): string {
  if (isStale(w.heartbeat_at)) return 'stale'
  return String(w.status ?? 'idle').toLowerCase()
}

export default function WorkersView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const backendMode = useAppStore((s) => s.backendMode)
  const [workers, setWorkers] = React.useState<WorkerRow[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [lastRefresh, setLastRefresh] = React.useState<Date | null>(null)
  const [filterLabel, setFilterLabel] = React.useState('')
  const [filterPool, setFilterPool] = React.useState('')
  const [filterStatus, setFilterStatus] = React.useState('')
  const [selected, setSelected] = React.useState<WorkerRow | null>(null)
  const [fleetTab, setFleetTab] = React.useState<'workers' | 'queue'>('workers')
  const [recentRuns, setRecentRuns] = React.useState<
    Array<{ run_id: string; status?: string; created_at?: string; graph_name?: string }>
  >([])
  const [queueNote, setQueueNote] = React.useState<string | null>(null)

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const rows = await apiJson<WorkerRow[]>('/workers', {
        query: { include_stale: true },
      })
      setWorkers(Array.isArray(rows) ? rows : [])
      setLastRefresh(new Date())
      try {
        const runs = await apiJson<
          Array<{ run_id: string; status?: string; created_at?: string; graph_name?: string }>
        >('/runs', { query: { limit: 12 } })
        setRecentRuns(Array.isArray(runs) ? runs.slice(0, 12) : [])
        setQueueNote(null)
      } catch {
        setRecentRuns([])
        setQueueNote('Could not load recent runs as a queue proxy.')
      }
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
    const id = window.setInterval(() => void refresh(), 15_000)
    return () => window.clearInterval(id)
  }, [refresh])

  React.useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected])

  const filtered = React.useMemo(() => {
    if (!workers) return []
    const lbl = filterLabel.trim().toLowerCase()
    const pool = filterPool.trim().toLowerCase()
    const st = filterStatus.trim().toLowerCase()
    return workers.filter((w) => {
      if (lbl && !(w.labels ?? []).some((x) => x.toLowerCase().includes(lbl))) return false
      if (pool && !(w.pools ?? []).some((x) => x.toLowerCase().includes(pool))) return false
      if (st && !effectiveStatus(w).includes(st)) return false
      return true
    })
  }, [workers, filterLabel, filterPool, filterStatus])

  const modeHint =
    backendMode === 'distributed'
      ? 'Mode B (distributed) — workers register with this control plane.'
      : backendMode === 'local'
        ? 'Mode A (local) — pipelines run in-process; workers are optional.'
        : 'Set GRAPHYN_BACKEND=distributed on the control plane for Mode B.'

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6 space-y-5">
      <PageHeader
        title="Worker fleet"
        description={
          backendMode === 'distributed'
            ? 'Deploy — Mode B worker registry, labels, GPU, and heartbeats.'
            : 'Deploy — only needed when Mode is Distributed; local Mode A runs pipelines in-process.'
        }
        actions={
          <button type="button" className="btn-secondary" onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-ink-200 bg-white px-4 py-3 text-sm shadow-sm">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Summary</span>
        <span className="font-medium text-ink-900">
          {workers === null ? '…' : workers.length} {workers?.length === 1 ? 'worker' : 'workers'}
        </span>
        <span className="text-ink-500">{modeHint}</span>
        <span className="ml-auto text-[11px] text-ink-400">
          {lastRefresh ? `Refreshed ${formatRelativeTime(lastRefresh.toISOString())}` : 'Not refreshed yet'}
        </span>
        <button type="button" className="btn-secondary" onClick={() => void refresh()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}

      <div className="flex flex-wrap gap-1 rounded-xl bg-ink-100/70 p-1 w-fit">
        <button
          type="button"
          className={fleetTab === 'workers' ? 'tab-pill tab-pill-on' : 'tab-pill'}
          onClick={() => setFleetTab('workers')}
        >
          Workers
        </button>
        <button
          type="button"
          className={fleetTab === 'queue' ? 'tab-pill tab-pill-on' : 'tab-pill'}
          onClick={() => setFleetTab('queue')}
        >
          Queue
        </button>
      </div>

      {fleetTab === 'queue' ? (
        <section className="space-y-4 rounded-2xl border border-ink-200 bg-white p-4 shadow-sm">
          <div>
            <h3 className="text-sm font-semibold text-ink-900">Job queue</h3>
            <p className="mt-1 text-xs text-ink-500 max-w-2xl">
              There is no list-all jobs API — only <code className="font-mono text-[11px]">GET /jobs/{'{id}'}</code>{' '}
              plus claim/complete/cancel. Mode B (
              <code className="font-mono text-[11px]">GRAPHYN_BACKEND=distributed</code>): workers claim eligible
              jobs from this control plane by label/pool; this tab cannot show a live lease queue.
            </p>
            {backendMode === 'distributed' ? (
              <p className="text-xs text-accent-800 bg-accent-50/80 border border-accent-100 rounded-lg px-3 py-2">
                Mode B active — queue depth is worker-side. Use heartbeats on Workers and recent run statuses below as
                a proxy until a list-jobs API exists.
              </p>
            ) : (
              <p className="text-xs text-ink-500 bg-ink-50 border border-ink-100 rounded-lg px-3 py-2">
                Mode A (local) runs in-process — the claim queue is unused unless you switch the control plane to
                distributed.
              </p>
            )}
            <a
              href="https://github.com/ursamir/Graphyn/blob/main/docs/DISTRIBUTED_EXECUTION.md"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-accent-700 hover:text-accent-900"
            >
              <ExternalLink className="h-3 w-3" />
              Distributed execution · claim protocol
            </a>
          </div>
          {queueNote && <p className="text-sm text-amber-800">{queueNote}</p>}
          {recentRuns.length === 0 ? (
            <EmptyState
              title="No queue listing available"
              description="Use recent run statuses below as a rough proxy once runs exist, or inspect a job by id via the API."
              action={
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => goView('runs')}
                >
                  Open Runs
                </button>
              }
            />
          ) : (
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                Recent run statuses (proxy)
              </div>
              <div className="overflow-hidden rounded-xl border border-ink-100">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-ink-100 bg-ink-50/80 text-[11px] uppercase tracking-wide text-ink-500">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Run</th>
                      <th className="px-3 py-2 font-semibold">Status</th>
                      <th className="px-3 py-2 font-semibold">Graph</th>
                      <th className="px-3 py-2 font-semibold">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRuns.map((r) => (
                      <tr key={r.run_id} className="border-b border-ink-50 last:border-0">
                        <td className="px-3 py-1.5 font-mono text-xs">{r.run_id.slice(0, 10)}…</td>
                        <td className="px-3 py-1.5">
                          <StatusBadge status={String(r.status || 'unknown')} />
                        </td>
                        <td className="px-3 py-1.5 text-ink-600">{r.graph_name || '—'}</td>
                        <td className="px-3 py-1.5 text-xs text-ink-500 whitespace-nowrap">
                          {r.created_at ? formatRelativeTime(r.created_at) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      ) : loading && workers === null ? (
        <LoadingBlock label="Loading workers…" />
      ) : !workers || workers.length === 0 ? (
        <EmptyState
          title="No workers registered"
          description="Mode A needs no workers. For Mode B, set GRAPHYN_BACKEND=distributed on the control plane, start a worker, then refresh."
          action={
            <div className="flex flex-col items-center gap-3">
              <div className="w-full max-w-xl rounded-xl border border-ink-200 bg-ink-50/80 px-3 py-2 text-left">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  Control plane
                </div>
                <CopyableMono value="GRAPHYN_BACKEND=distributed" />
                <div className="mb-1 mt-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  Worker start
                </div>
                <CopyableMono value={WORKER_START_CMD} />
              </div>
              <a
                href={DOCS_GETTING_STARTED_MODE_B}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-accent-700 hover:text-accent-900"
              >
                <ExternalLink className="h-3 w-3" />
                Getting Started · Mode B
              </a>
            </div>
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <input
              value={filterLabel}
              onChange={(e) => setFilterLabel(e.target.value)}
              placeholder="Filter label"
              className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
            />
            <input
              value={filterPool}
              onChange={(e) => setFilterPool(e.target.value)}
              placeholder="Filter pool"
              className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
            />
            <input
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              placeholder="Filter status"
              className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm"
            />
            {(filterLabel || filterPool || filterStatus) && (
              <button
                type="button"
                className="btn-quiet"
                onClick={() => {
                  setFilterLabel('')
                  setFilterPool('')
                  setFilterStatus('')
                }}
              >
                Clear filters
              </button>
            )}
          </div>

          {filtered.length === 0 ? (
            <p className="py-6 text-center text-sm text-ink-500">No workers match these filters.</p>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-sm">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-ink-100 bg-ink-50/80 text-[11px] uppercase tracking-wide text-ink-500">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold">Worker</th>
                    <th className="px-4 py-2.5 font-semibold">Status</th>
                    <th className="px-4 py-2.5 font-semibold">Labels</th>
                    <th className="px-4 py-2.5 font-semibold">GPU / VRAM</th>
                    <th className="px-4 py-2.5 font-semibold">Last heartbeat</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((w) => {
                    const stale = isStale(w.heartbeat_at)
                    return (
                      <tr
                        key={w.worker_id}
                        className="cursor-pointer border-b border-ink-100/80 last:border-0 hover:bg-ink-50/60"
                        onClick={() => setSelected(w)}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Server className="h-3.5 w-3.5 text-ink-400" />
                            <span className="font-medium text-ink-900">{w.worker_id}</span>
                            {stale && (
                              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900">
                                Stale
                              </span>
                            )}
                          </div>
                          {w.plugins && w.plugins.length > 0 && (
                            <div className="mt-1 text-[11px] text-ink-400">
                              {w.plugins.slice(0, 6).join(', ')}
                              {w.plugins.length > 6 ? ` +${w.plugins.length - 6}` : ''}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={String(w.status ?? (stale ? 'offline' : 'idle'))} />
                          {typeof w.active_jobs === 'number' && w.active_jobs > 0 && (
                            <div className="mt-1 text-[11px] text-ink-500">{w.active_jobs} active</div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {(w.labels ?? []).map((lbl) => (
                              <span
                                key={lbl}
                                className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium text-ink-700"
                              >
                                {lbl}
                              </span>
                            ))}
                            {(w.pools ?? []).map((p) => (
                              <span
                                key={`pool-${p}`}
                                className="rounded-md bg-accent-50 px-1.5 py-0.5 text-[11px] font-medium text-accent-800"
                              >
                                pool:{p}
                              </span>
                            ))}
                            {(w.labels ?? []).length === 0 && (w.pools ?? []).length === 0 && (
                              <span className="text-ink-400">—</span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-ink-700">{gpuLabel(w)}</td>
                        <td className="px-4 py-3 text-ink-600" title={formatLocaleDateTime(w.heartbeat_at)}>
                          {w.heartbeat_at ? formatRelativeTime(w.heartbeat_at) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {selected && (
        <div className="fixed inset-0 z-[100] flex justify-end bg-ink-950/30" onClick={() => setSelected(null)}>
          <aside
            className="flex h-full w-full max-w-md flex-col border-l border-ink-200 bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={`Worker ${selected.worker_id}`}
          >
            <div className="flex items-start justify-between gap-2 border-b border-ink-100 px-4 py-3">
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Worker</div>
                <div className="mt-1">
                  <CopyableMono value={selected.worker_id} />
                </div>
              </div>
              <button type="button" className="btn-icon" aria-label="Close" onClick={() => setSelected(null)}>
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm">
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Status</div>
                <StatusBadge status={String(selected.status ?? (isStale(selected.heartbeat_at) ? 'offline' : 'idle'))} />
                {typeof selected.active_jobs === 'number' && (
                  <div className="mt-1 text-ink-600">{selected.active_jobs} active job(s)</div>
                )}
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                  Labels <span className="font-normal normal-case tracking-normal text-ink-400">(display-only)</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(selected.labels ?? []).length === 0 ? (
                    <span className="text-ink-400">—</span>
                  ) : (
                    (selected.labels ?? []).map((lbl) => (
                      <span key={lbl} className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium text-ink-700">
                        {lbl}
                      </span>
                    ))
                  )}
                </div>
                <p className="mt-1 text-[11px] text-ink-400">
                  Set at <code className="font-mono">graphyn worker start --labels</code> — no PATCH API yet.
                </p>
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                  Pools <span className="font-normal normal-case tracking-normal text-ink-400">(display-only)</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(selected.pools ?? []).length === 0 ? (
                    <span className="text-ink-400">—</span>
                  ) : (
                    (selected.pools ?? []).map((p) => (
                      <span key={p} className="rounded-md bg-accent-50 px-1.5 py-0.5 text-[11px] font-medium text-accent-800">
                        {p}
                      </span>
                    ))
                  )}
                </div>
                <p className="mt-1 text-[11px] text-ink-400">
                  Set with <code className="font-mono">--pool</code> on worker start.
                </p>
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Resources</div>
                <dl className="space-y-1 text-ink-800">
                  <div className="flex justify-between gap-2">
                    <dt className="text-ink-500">GPU</dt>
                    <dd>{gpuLabel(selected)}</dd>
                  </div>
                  {selected.resources?.cpus != null && (
                    <div className="flex justify-between gap-2">
                      <dt className="text-ink-500">CPUs</dt>
                      <dd>{selected.resources.cpus}</dd>
                    </div>
                  )}
                </dl>
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Heartbeat</div>
                <div title={formatLocaleDateTime(selected.heartbeat_at)}>
                  {selected.heartbeat_at ? formatRelativeTime(selected.heartbeat_at) : '—'}
                  {isStale(selected.heartbeat_at) ? (
                    <span className="ml-2 text-amber-800">stale</span>
                  ) : null}
                </div>
                {selected.heartbeat_at && (
                  <div className="mt-0.5 font-mono text-[11px] text-ink-400">
                    {formatLocaleDateTime(selected.heartbeat_at)}
                  </div>
                )}
              </div>
              {selected.plugins && selected.plugins.length > 0 && (
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">Plugins</div>
                  <p className="text-ink-700">{selected.plugins.join(', ')}</p>
                </div>
              )}
            </div>
            <div className="border-t border-ink-100 px-4 py-3">
              <ConfirmButton
                label="Deregister"
                confirmLabel="Confirm deregister"
                danger
                onConfirm={() => {
                  const id = selected.worker_id
                  void apiJson(`/workers/${encodeURIComponent(id)}`, { method: 'DELETE' })
                    .then(() => {
                      pushToast(`Deregistered ${id}`, 'success')
                      setSelected(null)
                      void refresh()
                    })
                    .catch((err) =>
                      pushToast(err instanceof Error ? err.message : String(err), 'error'),
                    )
                }}
              />
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
