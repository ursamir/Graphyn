import React from 'react'
import { Copy, Play, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, KeyValue, LoadingBlock, PageHeader } from '../../components/ui'
import { humanNodeLabel, shortRunId } from '../../lib/format'

interface Artifact {
  artifact_id?: string
  id?: string
  run_id?: string
  node_type?: string
  artifact_type?: string
  [key: string]: unknown
}

function findCopyablePath(data: unknown, depth = 0): string | null {
  if (!data || typeof data !== 'object' || depth > 2) return null
  const o = data as Record<string, unknown>
  for (const k of ['model_path', 'path']) {
    if (typeof o[k] === 'string' && o[k].trim()) return o[k]
  }
  for (const v of Object.values(o)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const nested = findCopyablePath(v, depth + 1)
      if (nested) return nested
    }
  }
  return null
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

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path)
      pushToast('Path copied', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const path = findCopyablePath(detail)

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-200 p-4">
        <PageHeader
          title="Artifacts"
          description="Outputs from completed nodes — inspect lineage and replay a producing run."
        />
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <label className="text-[11px] font-medium text-ink-500">
            Run ID
            <input
              value={runFilter}
              onChange={(e) => setRunFilter(e.target.value)}
              placeholder="run id"
              className="mt-0.5 block rounded-lg border border-ink-200 px-2 py-1 text-sm"
            />
          </label>
          <label className="text-[11px] font-medium text-ink-500">
            Node
            <input
              value={nodeTypeFilter}
              onChange={(e) => setNodeTypeFilter(e.target.value)}
              placeholder="node type"
              className="mt-0.5 block rounded-lg border border-ink-200 px-2 py-1 text-sm"
            />
          </label>
          <label className="text-[11px] font-medium text-ink-500">
            Type
            <input
              value={artifactTypeFilter}
              onChange={(e) => setArtifactTypeFilter(e.target.value)}
              placeholder="artifact type"
              className="mt-0.5 block rounded-lg border border-ink-200 px-2 py-1 text-sm"
            />
          </label>
          <button type="button" onClick={() => void load()} className="btn-secondary">
            <RefreshCw className="h-3.5 w-3.5" /> Apply
          </button>
        </div>
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {items === null ? (
          <LoadingBlock />
        ) : items.length === 0 ? (
          <EmptyState
            title="No artifacts"
            description="Run a pipeline that produces artifacts, then refresh."
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
                    <div className="font-medium">
                      {a.node_type ? humanNodeLabel(String(a.node_type)) : 'Artifact'}
                    </div>
                    <div className="text-[11px] text-ink-500">
                      {shortRunId(String(a.run_id ?? ''))} · {String(a.artifact_type ?? '—')}
                    </div>
                    <div className="font-mono text-[10px] text-ink-400">{id}</div>
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
            {path && (
              <div className="flex items-start gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2">
                <code className="min-w-0 flex-1 break-all font-mono text-[11px] text-ink-800">{path}</code>
                <button type="button" className="btn-secondary shrink-0" onClick={() => void copyPath(path)}>
                  <Copy className="h-3.5 w-3.5" /> Copy path
                </button>
              </div>
            )}
            <h3 className="text-sm font-semibold">Detail</h3>
            <KeyValue data={detail} />
            <h3 className="text-sm font-semibold">Lineage</h3>
            <KeyValue data={lineage} />
          </>
        )}
      </div>
    </div>
  )
}
