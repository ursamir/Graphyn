import React from 'react'
import { ExternalLink, RefreshCw, Server } from 'lucide-react'
import { apiJson } from '../../api/client'
import { formatLocaleDateTime, formatRelativeTime } from '../../lib/format'
import { useAppStore } from '../../store/appStore'
import {
  CopyableMono,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'

/** Same-host smoke command from docs/GETTING_STARTED.md + docs/SDK_AND_CLI.md */
const WORKER_START_CMD =
  'venv/bin/python -m app.cli.main worker start --control-url http://127.0.0.1:8001/api/v1 --worker-id local-gpu --labels gpu --pool gpu-lab'

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

export default function WorkersView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [workers, setWorkers] = React.useState<WorkerRow[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const rows = await apiJson<WorkerRow[]>('/workers', {
        query: { include_stale: true },
      })
      setWorkers(Array.isArray(rows) ? rows : [])
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

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Workers"
        description="Distributed compute placement (Mode B) — registered workers, labels, GPU, and heartbeats. For packaging models onto devices, use Edge deploy."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}
      {loading && workers === null ? (
        <LoadingBlock label="Loading workers…" />
      ) : !workers || workers.length === 0 ? (
        <EmptyState
          title="No workers registered"
          description="Mode B needs a distributed control plane plus at least one worker. Set GRAPHYN_BACKEND=distributed on the API host, start a worker with the CLI, then refresh. Packaging models onto devices is Edge deploy — different from workers."
          action={
            <div className="flex flex-col items-center gap-3">
              <div className="w-full max-w-xl rounded-xl border border-ink-200 bg-ink-50/80 px-3 py-2 text-left">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  Control plane env
                </div>
                <CopyableMono value="GRAPHYN_BACKEND=distributed" />
                <div className="mb-1 mt-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  Worker start (same-host smoke)
                </div>
                <CopyableMono value={WORKER_START_CMD} />
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    useAppStore.getState().setView('system')
                    window.history.replaceState(null, '', '#/system')
                  }}
                >
                  Open System
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    useAppStore.getState().openEdge()
                  }}
                >
                  Edge deploy instead
                </button>
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
              {workers.map((w) => {
                const stale = isStale(w.heartbeat_at)
                return (
                  <tr key={w.worker_id} className="border-b border-ink-100/80 last:border-0">
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
    </div>
  )
}
