import React from 'react'
import { Copy, Download, GitBranch, History, Play, RefreshCw, Workflow } from 'lucide-react'
import { apiJson, downloadOutputFile, fetchOutputBlobUrl } from '../../api/client'
import { fetchRunGraph } from '../../lib/runGraph'
import { useAppStore } from '../../store/appStore'
import { CopyableMono, EmptyState, ErrorBanner, KeyValue, LoadingBlock, PageHeader } from '../../components/ui'
import { formatLocaleDateTime, humanNodeLabel, humanizeTemplateName, shortRunId } from '../../lib/format'

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


function lineageInputIds(lineage: unknown): Array<{ id: string; label: string }> {
  if (!lineage || typeof lineage !== 'object') return []
  const rec = lineage as Record<string, unknown>
  const raw = rec.inputs
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item) => {
    if (typeof item === 'string' && item.trim()) {
      return [{ id: item, label: item }]
    }
    if (item && typeof item === 'object') {
      const o = item as Record<string, unknown>
      const id = String(o.artifact_id ?? o.id ?? '').trim()
      if (!id) return []
      const label = String(o.node_type ?? o.artifact_type ?? o.name ?? id)
      return [{ id, label }]
    }
    return []
  })
}

function LineageList({
  lineage,
  onOpen,
}: {
  lineage: unknown
  onOpen: (id: string) => void
}) {
  if (lineage == null) return <p className="text-sm text-ink-500">No lineage.</p>
  const inputs = lineageInputIds(lineage)
  const rest =
    lineage && typeof lineage === 'object' && !Array.isArray(lineage)
      ? Object.fromEntries(
          Object.entries(lineage as Record<string, unknown>).filter(([k]) => k !== 'inputs'),
        )
      : lineage
  return (
    <div className="space-y-3">
      {inputs.length > 0 ? (
        <ul className="space-y-1.5">
          {inputs.map((item) => (
            <li
              key={item.id}
              className="flex items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2"
            >
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left text-sm font-medium text-ink-900 hover:text-accent-700"
                onClick={() => onOpen(item.id)}
              >
                {item.label}
              </button>
              <CopyableMono value={item.id} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-400">No input artifacts.</p>
      )}
      {rest && typeof rest === 'object' && Object.keys(rest as object).length > 0 && (
        <KeyValue data={rest} empty="No other lineage fields." />
      )}
    </div>
  )
}


function parseArtifactsHash(): { runId: string; artifactId: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return { runId: '', artifactId: '' }
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  return {
    runId: (params.get('run_id') || '').trim(),
    artifactId: (params.get('artifact_id') || '').trim(),
  }
}

function writeArtifactsHash(runId: string, artifactId: string) {
  const params = new URLSearchParams()
  if (runId.trim()) params.set('run_id', runId.trim())
  if (artifactId.trim()) params.set('artifact_id', artifactId.trim())
  const qs = params.toString()
  const next = qs ? `#/artifacts?${qs}` : '#/artifacts'
  if (window.location.hash !== next) {
    window.history.replaceState(null, '', next)
  }
}

export default function ArtifactsView() {
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)
  const focusArtifactId = useAppStore((s) => s.focusArtifactId)
  const initialHash = React.useMemo(() => parseArtifactsHash(), [])
  const [items, setItems] = React.useState<Artifact[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(
    () => initialHash.artifactId || null,
  )
  const [detail, setDetail] = React.useState<unknown>(null)
  const [lineage, setLineage] = React.useState<unknown>(null)
  const [runFilter, setRunFilter] = React.useState(() => initialHash.runId)
  const [nodeTypeFilter, setNodeTypeFilter] = React.useState('')
  const [artifactTypeFilter, setArtifactTypeFilter] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)

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

  const open = React.useCallback(async (id: string) => {
    const aid = id.trim()
    if (!aid) return
    setSelected(aid)
    try {
      const [d, l] = await Promise.all([
        apiJson(`/artifacts/${aid}`),
        apiJson(`/artifacts/${aid}/lineage`),
      ])
      setDetail(d)
      setLineage(l)
      // If deep-linked by artifact_id alone, adopt run_id from the record.
      if (d && typeof d === 'object') {
        const rid = String((d as Artifact).run_id ?? '').trim()
        if (rid) {
          setRunFilter((prev) => (prev ? prev : rid))
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  React.useEffect(() => {
    const apply = () => {
      const { runId, artifactId } = parseArtifactsHash()
      setRunFilter((prev) => (prev === runId ? prev : runId))
      if (artifactId) void open(artifactId)
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [open])

  React.useEffect(() => {
    writeArtifactsHash(runFilter, selected ?? '')
  }, [runFilter, selected])

  React.useEffect(() => {
    const aid = (focusArtifactId || '').trim()
    if (!aid) return
    void open(aid)
    useAppStore.setState({ focusArtifactId: null })
  }, [focusArtifactId, open])


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

  React.useEffect(() => {
    if (!path || !/\.(png|jpe?g|gif|webp)$/i.test(path)) {
      setPreviewUrl(null)
      return
    }
    let cancelled = false
    let created: string | null = null
    void fetchOutputBlobUrl(path)
      .then((url) => {
        created = url
        if (!cancelled) setPreviewUrl(url)
        else URL.revokeObjectURL(url)
      })
      .catch(() => {
        if (!cancelled) setPreviewUrl(null)
      })
    return () => {
      cancelled = true
      if (created) URL.revokeObjectURL(created)
    }
  }, [path])

  const download = async (filePath: string) => {
    try {
      await downloadOutputFile(filePath)
      pushToast('Download started', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-300 bg-white p-4">
        <PageHeader
          title="Artifacts"
          description="Browse pipeline outputs across runs."
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
            title="No artifacts yet"
            description="Run a pipeline from Builder that produces node outputs, then refresh. Trace is the backtrack surface; this page is the library."
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
                    useAppStore.getState().setView('runs')
                    window.history.replaceState(null, '', '#/runs')
                  }}
                >
                  Open Runs
                </button>
              </div>
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
      <div className="overflow-y-auto border-l border-ink-200/80 bg-ink-50/40 p-4 space-y-3">
        {!selected ? (
          <EmptyState
            title="Select an artifact"
            description="Inspect this output, replay its run, or open Trace for the accountability chain."
            action={
              items && items.length > 0 ? (
                <button type="button" className="btn-secondary" onClick={() => void open(idOf(items[0]))}>
                  Open first artifact
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
            {(() => {
              const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
              const nodeType = String(rec.node_type ?? '').trim()
              const artifactType = String(rec.artifact_type ?? '').trim()
              const runId = String(rec.run_id ?? '').trim()
              const created = String(rec.created_at ?? rec.ts ?? '').trim()
              const graphName = String(rec.graph_name ?? '').trim()
              return (
                <div className="rounded-2xl border border-ink-200/80 bg-white px-4 py-3 shadow-sm space-y-1">
                  <div className="text-base font-semibold text-ink-900">
                    {nodeType ? humanNodeLabel(nodeType) : 'Artifact'}
                    {artifactType ? (
                      <span className="ml-2 text-sm font-normal text-ink-500">{artifactType}</span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm text-ink-600">
                    {runId ? (
                      <button
                        type="button"
                        className="inline-flex items-center rounded-full border border-ink-200 bg-ink-50 px-2.5 py-0.5 font-mono text-xs text-accent-800 hover:border-accent-300 hover:bg-accent-50"
                        onClick={() => openRun(runId)}
                        title={runId}
                      >
                        run {shortRunId(runId)}
                      </button>
                    ) : (
                      <span className="text-ink-400">No linked run</span>
                    )}
                    {graphName ? (
                      <span className="text-xs text-ink-500">{humanizeTemplateName(graphName)}</span>
                    ) : null}
                    {created ? (
                      <span className="text-xs text-ink-400">{formatLocaleDateTime(created)}</span>
                    ) : null}
                  </div>
                  <div className="font-mono text-[11px] text-ink-400">{selected}</div>
                </div>
              )
            })()}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
                  const runId = String(rec.run_id ?? '').trim()
                  openTrace({ artifactId: selected, runId: runId || undefined })
                }}
              >
                <GitBranch className="h-3.5 w-3.5" /> Trace lineage
              </button>
              {(() => {
                const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
                const runId = String(rec.run_id ?? '').trim()
                if (!runId) return null
                return (
                  <button type="button" className="btn-secondary" onClick={() => openRun(runId)}>
                    <History className="h-3.5 w-3.5" /> Open run
                  </button>
                )
              })()}
              {(() => {
                const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
                const runId = String(rec.run_id ?? '').trim()
                const graphName = String(rec.graph_name ?? '').trim()
                if (!runId && !graphName) return null
                return (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      void (async () => {
                        try {
                          const graph = await fetchRunGraph(runId, graphName || null)
                          if (!graph) {
                            pushToast('Graph not available for this artifact', 'info')
                            return
                          }
                          loadGraphIntoBuilder(graph)
                          pushToast('Opened graph in Builder', 'success')
                        } catch (err) {
                          pushToast(err instanceof Error ? err.message : String(err), 'error')
                        }
                      })()
                    }}
                  >
                    <Workflow className="h-3.5 w-3.5" /> Open in Builder
                  </button>
                )
              })()}
              <button type="button" className="btn-primary" onClick={() => void replay(selected)}>
                <Play className="h-3.5 w-3.5" /> Replay
              </button>
            </div>
            {path && (
              <div className="space-y-2">
                <div className="flex items-start gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2">
                  <code className="min-w-0 flex-1 break-all font-mono text-[11px] text-ink-800">{path}</code>
                  <button type="button" className="btn-secondary shrink-0" onClick={() => void copyPath(path)}>
                    <Copy className="h-3.5 w-3.5" /> Copy path
                  </button>
                  <button type="button" className="btn-primary shrink-0" onClick={() => void download(path)}>
                    <Download className="h-3.5 w-3.5" /> Download
                  </button>
                </div>
                {previewUrl && (
                  <img
                    src={previewUrl}
                    alt={path.split(/[\\/]/).pop() || 'preview'}
                    className="max-h-80 w-full rounded-xl border border-ink-200 object-contain bg-white"
                  />
                )}
              </div>
            )}
            <h3 className="text-sm font-semibold">Artifact</h3>
            <KeyValue
              data={(() => {
                if (!detail || typeof detail !== 'object') return detail
                const omit = new Set(['run', 'run_meta', 'run_detail', 'graph', 'logs', 'status_detail'])
                return Object.fromEntries(
                  Object.entries(detail as Record<string, unknown>).filter(([k]) => !omit.has(k)),
                )
              })()}
            />
            <h3 className="text-sm font-semibold">Lineage</h3>
            <LineageList lineage={lineage} onOpen={(id) => void open(id)} />
          </>
        )}
      </div>
    </div>
  )
}
