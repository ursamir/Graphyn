import React from 'react'
import { Play, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, LoadingBlock, StatusBadge } from '../../components/ui'

interface Artifact {
  artifact_id?: string
  id?: string
  run_id?: string
  node_type?: string
  artifact_type?: string
  [key: string]: unknown
}

export default function ArtifactsView() {
  const openRun = useAppStore((s) => s.openRun)
  const pushToast = useAppStore((s) => s.pushToast)
  const [items, setItems] = React.useState<Artifact[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<unknown>(null)
  const [lineage, setLineage] = React.useState<unknown>(null)
  const [runFilter, setRunFilter] = React.useState('')
  const [nodeTypeFilter, setNodeTypeFilter] = React.useState('')
  const [artifactTypeFilter, setArtifactTypeFilter] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)

  const idOf = (a: Artifact) => String(a.artifact_id ?? a.id ?? '')

  const load = React.useCallback(async () => {
    setError(null)
    try {
      setItems(
        await apiJson<Artifact[]>('/artifacts', {
          query: {
            run_id: runFilter || undefined,
            node_type: nodeTypeFilter || undefined,
            artifact_type: artifactTypeFilter || undefined,
          },
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setItems([])
    }
  }, [runFilter, nodeTypeFilter, artifactTypeFilter])

  React.useEffect(() => {
    void load()
  }, [load])

  const open = async (id: string) => {
    setSelected(id)
    try {
      const [d, l] = await Promise.all([
        apiJson(`/artifacts/${id}`),
        apiJson(`/artifacts/${id}/lineage`),
      ])
      setDetail(d)
      setLineage(l)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const replay = async (id: string) => {
    try {
      const res = await apiJson<{ run_id: string }>(`/artifacts/${id}/replay`, { method: 'POST' })
      pushToast(`Replay started: ${res.run_id}`, 'success')
      openRun(res.run_id)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-200 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="font-display text-lg font-bold">Artifacts</h2>
          <input value={runFilter} onChange={(e) => setRunFilter(e.target.value)} placeholder="run_id" className="rounded-lg border border-ink-200 px-2 py-1 text-sm" />
          <input value={nodeTypeFilter} onChange={(e) => setNodeTypeFilter(e.target.value)} placeholder="node_type" className="rounded-lg border border-ink-200 px-2 py-1 text-sm" />
          <input value={artifactTypeFilter} onChange={(e) => setArtifactTypeFilter(e.target.value)} placeholder="artifact_type" className="rounded-lg border border-ink-200 px-2 py-1 text-sm" />
          <button type="button" onClick={() => void load()} className="btn-secondary">
            <RefreshCw className="h-3.5 w-3.5" /> Apply
          </button>
        </div>
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {items === null ? (
          <LoadingBlock />
        ) : items.length === 0 ? (
          <EmptyState title="No artifacts" description="Run a pipeline that produces artifacts, then refresh." />
        ) : (
          <ul className="space-y-2">
            {items.map((a) => {
              const id = idOf(a)
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() => void open(id)}
                    className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                      selected === id ? 'border-accent-400 bg-accent-50' : 'border-ink-200 bg-white'
                    }`}
                  >
                    <div className="font-mono text-xs">{id}</div>
                    <div className="text-[11px] text-ink-500">
                      {a.node_type ?? '?'} · {a.artifact_type ?? '?'} · {a.run_id ?? '?'}
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
      <div className="overflow-y-auto p-4 space-y-3">
        {!selected ? (
          <EmptyState title="Select an artifact" description="Inspect lineage and replay producing runs." />
        ) : (
          <>
            <button type="button" className="btn-primary" onClick={() => void replay(selected)}>
              <Play className="h-3.5 w-3.5" /> Replay
            </button>
            <h3 className="text-sm font-semibold">Detail</h3>
            <pre className="max-h-56 overflow-auto rounded-xl bg-ink-950 p-3 font-mono text-[11px] text-ink-100">
              {JSON.stringify(detail, null, 2)}
            </pre>
            <h3 className="text-sm font-semibold">Lineage</h3>
            <pre className="max-h-80 overflow-auto rounded-xl bg-ink-100 p-3 font-mono text-[11px]">
              {JSON.stringify(lineage, null, 2)}
            </pre>
            <StatusBadge status="lineage" />
          </>
        )}
      </div>
    </div>
  )
}
