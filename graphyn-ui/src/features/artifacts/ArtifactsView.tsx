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

type RecentRun = {
  run_id: string
  status?: string
  graph_name?: string
  created_at?: string
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

function formatBytes(n: unknown): string | null {
  const num = typeof n === 'number' ? n : typeof n === 'string' && n.trim() ? Number(n) : NaN
  if (!Number.isFinite(num) || num < 0) return null
  if (num < 1024) return `${Math.round(num)} B`
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`
  return `${(num / (1024 * 1024)).toFixed(1)} MB`
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
  const activeProject = useAppStore((s) => s.activeProject)
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
  const [recentRuns, setRecentRuns] = React.useState<RecentRun[]>([])
  const [typeOptions, setTypeOptions] = React.useState<string[]>([])

  const idOf = (a: Artifact) => String(a.artifact_id ?? a.id ?? '')

  const hasActiveFilters = Boolean(
    runFilter.trim() || nodeTypeFilter.trim() || artifactTypeFilter.trim(),
  )

  const clearFilters = () => {
    setRunFilter('')
    setNodeTypeFilter('')
    setArtifactTypeFilter('')
    setSelected(null)
    setDetail(null)
  }

  const loadRecentRuns = React.useCallback(async () => {
    if (!activeProject) {
      setRecentRuns([])
      return
    }
    try {
      const rows = await apiJson<RecentRun[]>('/runs', {
        query: { limit: 20, project: activeProject },
      })
      setRecentRuns(Array.isArray(rows) ? rows : [])
    } catch {
      setRecentRuns([])
    }
  }, [activeProject])

  React.useEffect(() => {
    void loadRecentRuns()
  }, [loadRecentRuns])

  const load = React.useCallback(async () => {
    setError(null)
    try {
      const rows = await apiJson<Artifact[]>('/artifacts', {
        query: {
          run_id: runFilter || undefined,
          node_type: nodeTypeFilter || undefined,
          artifact_type: artifactTypeFilter || undefined,
        },
      })
      setItems(rows)
      const types = Array.from(
        new Set(
          rows
            .map((a) => String(a.artifact_type ?? '').trim())
            .filter(Boolean),
        ),
      ).sort()
      setTypeOptions((prev) => {
        const merged = new Set([...prev, ...types])
        if (artifactTypeFilter.trim()) merged.add(artifactTypeFilter.trim())
        return Array.from(merged).sort()
      })
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

  const runInPicker = recentRuns.some((r) => r.run_id === runFilter.trim())

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-300 bg-white p-4">
        <PageHeader
          title="Artifacts"
          description="Advanced cross-run file registry. For one run, stay on Run → Files."
        />
        <div className="mb-3 space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            {activeProject ? (
              <label className="text-[11px] font-medium text-ink-500">
                Run
                <select
                  value={runFilter.trim()}
                  onChange={(e) => setRunFilter(e.target.value)}
                  className="mt-0.5 block min-w-[12rem] rounded-lg border border-ink-200 px-2 py-1 text-sm"
                >
                  <option value="">Any run</option>
                  {!runInPicker && runFilter.trim() ? (
                    <option value={runFilter.trim()}>
                      Current · {shortRunId(runFilter.trim())}
                    </option>
                  ) : null}
                  {recentRuns.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {shortRunId(r.run_id)}
                      {r.graph_name ? ` · ${humanizeTemplateName(r.graph_name)}` : ''}
                      {r.status ? ` · ${r.status}` : ''}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="text-[12px] text-ink-400 self-center">
                Open a project for a recent-run picker, or use advanced ID below.
              </p>
            )}
            <label className="text-[11px] font-medium text-ink-500">
              Type
              <select
                value={artifactTypeFilter}
                onChange={(e) => setArtifactTypeFilter(e.target.value)}
                className="mt-0.5 block min-w-[8rem] rounded-lg border border-ink-200 px-2 py-1 text-sm"
              >
                <option value="">All types</option>
                {typeOptions.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <button type="button" onClick={() => void load()} className="btn-secondary">
              <RefreshCw className="h-3.5 w-3.5" /> Apply
            </button>
            {hasActiveFilters ? (
              <button type="button" className="btn-quiet text-[12px]" onClick={clearFilters}>
                Clear filters
              </button>
            ) : null}
          </div>
          <details className="rounded-lg border border-ink-100 bg-ink-50/60">
            <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[12px] font-medium text-ink-600">
              Advanced — free-text IDs / node type
            </summary>
            <div className="flex flex-wrap items-end gap-2 border-t border-ink-100 px-2.5 py-2">
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
                  className={`mt-0.5 block rounded-lg border border-ink-200 px-2 py-1 font-mono text-[11px] ${
                    initialHash.runId && runFilter === initialHash.runId
                      ? 'bg-ink-50 text-ink-500'
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
            </div>
          </details>
          <p className="text-[11px] leading-relaxed text-ink-400">
            Run → Files shows outputs for one run. Use this registry only for cross-run search or a specific artifact id.
          </p>
        </div>
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {items === null ? (
          <LoadingBlock />
        ) : items.length === 0 ? (
          <EmptyState
            title={
              hasActiveFilters
                ? 'No artifacts match these filters'
                : 'No artifacts yet'
            }
            description={
              hasActiveFilters
                ? runFilter.trim()
                  ? 'This filter produced no stored artifacts (common for failed or cancelled runs). Clear filters or open the run for logs.'
                  : 'Nothing matches. Clear filters to browse the full library.'
                : 'Run a pipeline that produces node outputs, then refresh. Prefer Run → Files for one run.'
            }
            action={
              hasActiveFilters ? (
                <button type="button" className="btn-primary" onClick={clearFilters}>
                  Clear filters
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    useAppStore.getState().setView('runs')
                    window.history.replaceState(null, '', '#/runs')
                    window.dispatchEvent(new HashChangeEvent('hashchange'))
                  }}
                >
                  Open Run
                </button>
              )
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
            description="Inspect this output, download it, open Lineage, or jump to its run."
            action={
              items && items.length > 0 ? (
                <button type="button" className="btn-secondary" onClick={() => void open(idOf(items[0]))}>
                  Open first artifact
                </button>
              ) : hasActiveFilters ? (
                <button type="button" className="btn-primary" onClick={clearFilters}>
                  Clear filters
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    useAppStore.getState().setView('runs')
                    window.history.replaceState(null, '', '#/runs')
                    window.dispatchEvent(new HashChangeEvent('hashchange'))
                  }}
                >
                  Open Run
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
              const sizeLabel = formatBytes(rec.size ?? rec.byte_size ?? rec.bytes)
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
                    {sizeLabel ? <span className="text-xs text-ink-400">{sizeLabel}</span> : null}
                    {created ? (
                      <span className="text-xs text-ink-400">{formatLocaleDateTime(created)}</span>
                    ) : null}
                  </div>
                  {path ? (
                    <div className="pt-1 font-mono text-[11px] text-ink-600 break-all">{path}</div>
                  ) : null}
                  <div className="font-mono text-[11px] text-ink-400">{selected}</div>
                </div>
              )
            })()}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
                  const runId = String(rec.run_id ?? '').trim()
                  openTrace({
                    artifactId: selected,
                    runId: runId || undefined,
                    project: useAppStore.getState().activeProject || undefined,
                  })
                }}
              >
                <GitBranch className="h-3.5 w-3.5" /> Lineage
              </button>
              {path ? (
                <button type="button" className="btn-primary" onClick={() => void download(path)}>
                  <Download className="h-3.5 w-3.5" /> Download
                </button>
              ) : null}
              {(() => {
                const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
                const runId = String(rec.run_id ?? '').trim()
                if (!runId) return null
                return (
                  <button type="button" className="btn-primary" onClick={() => openRun(runId)}>
                    <History className="h-3.5 w-3.5" /> Open run
                  </button>
                )
              })()}
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={() => void replay(selected)}>
                <Play className="h-3.5 w-3.5" /> Replay
              </button>
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
                          pushToast('Opened graph in Editor', 'success')
                        } catch (err) {
                          pushToast(err instanceof Error ? err.message : String(err), 'error')
                        }
                      })()
                    }}
                  >
                    <Workflow className="h-3.5 w-3.5" /> Editor
                  </button>
                )
              })()}
              {path ? (
                <button type="button" className="btn-secondary" onClick={() => void copyPath(path)}>
                  <Copy className="h-3.5 w-3.5" /> Copy path
                </button>
              ) : null}
            </div>
            {path && previewUrl && (
              <img
                src={previewUrl}
                alt={path.split(/[\\/]/).pop() || 'preview'}
                className="max-h-80 w-full rounded-xl border border-ink-200 object-contain bg-white"
              />
            )}
            <p className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-600">
              Prefer Run → Files for one run. Provenance lives on Run → Lineage (or this Trace deep-link for artifact ids).
            </p>
          </>
        )}
      </div>
    </div>
  )
}
