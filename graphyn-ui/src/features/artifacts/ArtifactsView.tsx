import React from 'react'
import { Copy, Download, GitBranch, History, Play, RefreshCw, Workflow } from 'lucide-react'
import { apiJson, downloadOutputFile, fetchOutputBlobUrl } from '../../api/client'
import { fetchRunGraph } from '../../lib/runGraph'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader } from '../../components/ui'
import { formatLocaleDateTime, humanNodeLabel, humanizeTemplateName, shortRunId } from '../../lib/format'

interface Artifact {
  artifact_id?: string
  id?: string
  run_id?: string
  node_type?: string
  artifact_type?: string
  [key: string]: unknown
}


function artifactHumanTitle(a: Artifact | Record<string, unknown>): string {
  const o = a as Record<string, unknown>
  const meta = o.metadata && typeof o.metadata === 'object' && !Array.isArray(o.metadata)
    ? (o.metadata as Record<string, unknown>)
    : {}
  for (const key of ['name', 'title', 'display_name', 'filename']) {
    const v = o[key]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  for (const key of ['title', 'display_name', 'filename', 'name', 'model_name']) {
    const v = meta[key]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  const path = typeof o.path === 'string' ? o.path : typeof meta.path === 'string' ? meta.path : ''
  if (path.trim()) {
    const base = path.trim().split(/[/\\]/).filter(Boolean).pop()
    if (base) return base
  }
  const nodeType = String(o.node_type ?? '').trim()
  return nodeType ? humanNodeLabel(nodeType) : 'Artifact'
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
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)
  const focusArtifactId = useAppStore((s) => s.focusArtifactId)
  const initialHash = React.useMemo(() => parseArtifactsHash(), [])
  const [items, setItems] = React.useState<Artifact[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(
    () => initialHash.artifactId || null,
  )
  const [detail, setDetail] = React.useState<unknown>(null)
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

  React.useEffect(() => {
    const rid = runFilter.trim()
    if (!rid) return
    let cancelled = false
    void (async () => {
      try {
        const d = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(rid)}`)
        if (cancelled) return
        const meta = d?.meta && typeof d.meta === 'object' ? (d.meta as Record<string, unknown>) : null
        const proj = String(meta?.project ?? d?.project ?? '').trim()
        if (proj && useAppStore.getState().activeProject !== proj) {
          setActiveProject(proj)
        }
      } catch {
        /* optional sync */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runFilter, setActiveProject])


  const open = React.useCallback(async (id: string) => {
    const aid = id.trim()
    if (!aid) return
    setSelected(aid)
    try {
      const d = await apiJson(`/artifacts/${aid}`)
      setDetail(d)
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
              title={
                initialHash.runId && runFilter === initialHash.runId
                  ? 'Prefilled from Runs — edit to broaden filter'
                  : undefined
              }
              className={`mt-0.5 block rounded-lg border border-ink-200 px-2 py-1 text-sm ${
                initialHash.runId && runFilter === initialHash.runId
                  ? 'bg-ink-50 font-mono text-[11px] text-ink-500'
                  : ''
              }`}
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
            title={runFilter.trim() ? 'This run produced no artifacts' : 'No artifacts yet'}
            description={
              runFilter.trim()
                ? 'The filtered run has no stored artifacts (common for failed or cancelled runs). Open the run for logs, or recover in the Editor.'
                : 'Run a pipeline from the Editor that produces node outputs, then refresh. Trace is the backtrack surface; this page is the library.'
            }
            action={
              <div className="flex flex-wrap justify-center gap-2">
                {runFilter.trim() ? (
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => openRun(runFilter.trim())}
                  >
                    Open Run
                  </button>
                ) : null}
                <button
                  type="button"
                  className={runFilter.trim() ? 'btn-secondary' : 'btn-primary'}
                  onClick={() => {
                    useAppStore.getState().setView('builder')
                    window.history.replaceState(null, '', '#/builder')
                  }}
                >
                  Open Editor
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
                    <div className="font-medium" title={String(a.node_type ?? '') || undefined}>
                      {artifactHumanTitle(a)}
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
              const artifactType = String(rec.artifact_type ?? '').trim()
              const runId = String(rec.run_id ?? '').trim()
              const created = String(rec.created_at ?? rec.ts ?? '').trim()
              const graphName = String(rec.graph_name ?? '').trim()
              return (
                <div className="rounded-2xl border border-ink-200/80 bg-white px-4 py-3 shadow-sm space-y-1">
                  <div className="text-base font-semibold text-ink-900">
                    {artifactHumanTitle(rec)}
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
                  openTrace({ artifactId: selected, runId: runId || undefined, project: useAppStore.getState().activeProject || undefined })
                }}
              >
                <GitBranch className="h-3.5 w-3.5" /> Trace lineage
              </button>
              <button type="button" className="btn-primary" onClick={() => void replay(selected)}>
                <Play className="h-3.5 w-3.5" /> Replay
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
                    title="Optional — rebuild canvas from this artifact run"
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
                    <Workflow className="h-3.5 w-3.5" /> Builder
                  </button>
                )
              })()}
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
            <p className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-600">
              Provenance and upstream inputs live in Trace — use{' '}
              <button
                type="button"
                className="font-medium text-accent-700 hover:underline"
                onClick={() => {
                  const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
                  const runId = String(rec.run_id ?? '').trim()
                  openTrace({ artifactId: selected, runId: runId || undefined, project: useAppStore.getState().activeProject || undefined })
                }}
              >
                Trace lineage
              </button>{' '}
              instead of dumping full metadata here.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
