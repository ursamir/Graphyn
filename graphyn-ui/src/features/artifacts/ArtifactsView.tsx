import React from 'react'
import clsx from 'clsx'
import { Copy, Download, GitBranch, History, Play, RefreshCw, Workflow } from 'lucide-react'
import { apiJson, downloadOutputFile, fetchOutputBlobUrl } from '../../api/client'
import { fetchRunGraph } from '../../lib/runGraph'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, LoadingBlock } from '../../components/ui'
import { MasterDetail, ViewShell } from '../../layout'
import { formatLocaleDateTime, humanNodeLabel, humanizeTemplateName, shortRunId } from '../../lib/format'
import { paths } from '../../routes/paths'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'

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
  // data_path is the real ArtifactRecord field (app/core/artifact_store.py) —
  // check it first; model_path/path are legacy/best-effort fallbacks only.
  for (const k of ['data_path', 'model_path', 'path']) {
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

function parseArtifactsLocation(): { runId: string; artifactId: string } {
  const params = readSearchParams()
  return {
    runId: (params.get('run_id') || '').trim(),
    artifactId: (params.get('artifactId') || params.get('artifact_id') || '').trim(),
  }
}

function writeArtifactsLocation(runId: string, artifactId: string) {
  replacePathSearch(
    {
      artifactId: artifactId.trim() || undefined,
      run_id: runId.trim() || undefined,
    },
    paths.libraryArtifacts().split('?')[0],
  )
}

export default function ArtifactsView() {
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)
  const focusArtifactId = useAppStore((s) => s.focusArtifactId)
  const activeProject = useAppStore((s) => s.activeProject)
  const initialLoc = React.useMemo(() => parseArtifactsLocation(), [])
  const [items, setItems] = React.useState<Artifact[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(
    () => initialLoc.artifactId || null,
  )
  const [detail, setDetail] = React.useState<unknown>(null)
  const [runFilter, setRunFilter] = React.useState(() => initialLoc.runId)
  const [nodeTypeFilter, setNodeTypeFilter] = React.useState('')
  const [artifactTypeFilter, setArtifactTypeFilter] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)
  const [recentRuns, setRecentRuns] = React.useState<RecentRun[]>([])
  const [typeOptions, setTypeOptions] = React.useState<string[]>([])
  const [regModelName, setRegModelName] = React.useState('')
  const [regModelSlug, setRegModelSlug] = React.useState('')
  const [registerBusy, setRegisterBusy] = React.useState(false)
  /* Workspace scoping needs no API change: a run record carries `project` and an
     artifact carries `run_id`, so project → runs → artifacts is a join the client
     can do. `projectRunIds` is the set of run ids for the open workspace. */
  const [projectRunIds, setProjectRunIds] = React.useState<Set<string>>(new Set())
  const [scope, setScope] = React.useState<'workspace' | 'all'>('workspace')
  const [runsTruncated, setRunsTruncated] = React.useState(false)
  const [listTruncated, setListTruncated] = React.useState(false)

  const idOf = (a: Artifact) => String(a.artifact_id ?? a.id ?? '')

  const hasActiveFilters = Boolean(
    runFilter.trim() || nodeTypeFilter.trim() || artifactTypeFilter.trim(),
  )

  /* project → runs → artifacts, resolved on the client. Only meaningful when a
     workspace is open and no explicit run filter is already narrowing the list. */
  const scopedToWorkspace = Boolean(
    activeProject && scope === 'workspace' && !runFilter.trim() && projectRunIds.size > 0,
  )
  const visibleItems = React.useMemo(() => {
    if (!items) return []
    if (!scopedToWorkspace) return items
    return items.filter((a) => projectRunIds.has(String(a.run_id ?? '')))
  }, [items, scopedToWorkspace, projectRunIds])
  /* Artifacts whose run recorded no project can never match any workspace — on
     this API that is most runs, so it is worth saying out loud. */
  const orphanCount = React.useMemo(() => {
    if (!items || !scopedToWorkspace) return 0
    return items.filter((a) => !projectRunIds.has(String(a.run_id ?? ''))).length
  }, [items, scopedToWorkspace, projectRunIds])

  const clearFilters = () => {
    setRunFilter('')
    setNodeTypeFilter('')
    setArtifactTypeFilter('')
    setSelected(null)
    setDetail(null)
  }

  const RUN_SCOPE_LIMIT = 200
  const loadRecentRuns = React.useCallback(async () => {
    if (!activeProject) {
      setRecentRuns([])
      setProjectRunIds(new Set())
      setRunsTruncated(false)
      return
    }
    try {
      /* Was limit 20 — enough to fill the picker, but the picker is no longer the
         only consumer: the same rows define which artifacts belong to this
         workspace, so a short page would silently drop older ones. */
      const rows = await apiJson<RecentRun[]>('/runs', {
        query: { limit: RUN_SCOPE_LIMIT, project: activeProject },
      })
      const list = Array.isArray(rows) ? rows : []
      setRecentRuns(list)
      setProjectRunIds(new Set(list.map((r) => String(r.run_id)).filter(Boolean)))
      setRunsTruncated(list.length >= RUN_SCOPE_LIMIT)
    } catch {
      setRecentRuns([])
      setProjectRunIds(new Set())
      setRunsTruncated(false)
    }
  }, [activeProject])

  React.useEffect(() => {
    void loadRecentRuns()
  }, [loadRecentRuns])

  const load = React.useCallback(async () => {
    setError(null)
    try {
      /* No limit was passed, so this silently took the API default of 100 — with
         121 artifacts stored, the list quietly omitted 21 of them and the count
         read as a total. 1000 is the endpoint's maximum; past that we say so
         rather than truncating in silence. */
      const ARTIFACT_LIMIT = 1000
      const rows = await apiJson<Artifact[]>('/artifacts', {
        query: {
          run_id: runFilter || undefined,
          node_type: nodeTypeFilter || undefined,
          artifact_type: artifactTypeFilter || undefined,
          limit: ARTIFACT_LIMIT,
        },
      })
      setItems(rows)
      setListTruncated(Array.isArray(rows) && rows.length >= ARTIFACT_LIMIT)
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

  /*
   * Resolve which workspace the SELECTED artifact belongs to — for display and
   * for building its action links — without touching global app state.
   *
   * This used to call setActiveProject(), which persists to localStorage. So with
   * no workspace open, clicking one row in a browse list silently opened a
   * workspace you never chose, enabled Home/Editor/Runs in the sidebar, and
   * survived navigation. A selection in a list must not reconfigure the app.
   */
  const [detailProject, setDetailProject] = React.useState<string | null>(null)
  const detailRunId = React.useMemo(() => {
    const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
    return String(rec.run_id ?? '').trim()
  }, [detail])

  React.useEffect(() => {
    const rid = detailRunId
    if (!rid) {
      setDetailProject(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const d = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(rid)}`)
        if (cancelled) return
        const meta = d?.meta && typeof d.meta === 'object' ? (d.meta as Record<string, unknown>) : null
        setDetailProject(String(meta?.project ?? d?.project ?? '').trim() || null)
      } catch {
        if (!cancelled) setDetailProject(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [detailRunId])

  /** Workspace to use when building this artifact's deep links. */
  const linkProject = detailProject || activeProject || undefined

  /** Last artifact id passed to open(), so the path-sync effect can tell a real
   *  navigation from the URL write that selecting an artifact performs. */
  const openedRef = React.useRef<string | null>(null)

  const open = React.useCallback(async (id: string, opts?: { adoptRun?: boolean }) => {
    const aid = id.trim()
    if (!aid) return
    openedRef.current = aid
    setSelected(aid)
    setDetail(null)
    try {
      const d = await apiJson(`/artifacts/${aid}`)
      setDetail(d)
      /* Adopt the run only when arriving by deep link with no run in the URL.
         Doing it on every click meant selecting a row re-filtered the list to
         that row's run — browsing 121 artifacts, clicking one, and being left
         with 3. Selection should not rewrite the query behind it. */
      if (opts?.adoptRun && d && typeof d === 'object') {
        const rid = String((d as Artifact).run_id ?? '').trim()
        if (rid) {
          setRunFilter((prev) => (prev ? prev : rid))
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      // Keep selected id; detail already cleared so prior artifact is not shown.
    }
  }, [])

  /* Selecting an artifact writes it into the URL, and that write dispatches the
     same path-change event this effect listens to. Without a guard, apply() then
     re-opened the artifact we had just opened — with adoptRun set, because the URL
     carried no run yet — which is what collapsed the list to the selection's own
     run even after adoption was made deep-link-only. Re-open only when the URL
     actually points at a different artifact. */
  React.useEffect(() => {
    const apply = () => {
      const { runId, artifactId } = parseArtifactsLocation()
      setRunFilter((prev) => (prev === runId ? prev : runId))
      /* Compare against what we have actually fetched, not `selected`: on a fresh
         deep link `selected` is seeded from the URL before any effect runs, so
         guarding on it skipped the one open() that was needed and left the detail
         pane blank. openedRef is only set by open() itself. */
      if (!artifactId || artifactId === openedRef.current) return
      void open(artifactId, { adoptRun: !runId })
    }
    apply()
    return onPathChange(apply)
  }, [open])

  React.useEffect(() => {
    writeArtifactsLocation(runFilter, selected ?? '')
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

  const registerModelFromArtifact = async (runId: string) => {
    const name = regModelName.trim()
    const slug = regModelSlug.trim() || name || 'model'
    if (!name) {
      pushToast('Enter a model name', 'error')
      return
    }
    if (!runId) {
      pushToast('Artifact has no linked run', 'error')
      return
    }
    setRegisterBusy(true)
    try {
      await apiJson('/models', {
        method: 'POST',
        body: JSON.stringify({
          name,
          run_id: runId,
          slug,
          stage: 'staging',
        }),
      })
      pushToast(`Registered model ${name} @ staging`, 'success')
      setRegModelName('')
      setRegModelSlug('')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setRegisterBusy(false)
    }
  }

  const runInPicker = recentRuns.some((r) => r.run_id === runFilter.trim())

  return (
    <ViewShell
      title="Artifacts"
      /* The store is global — an ArtifactRecord has no project field and
         GET /artifacts takes only run_id/node_type/artifact_type. But a run
         carries its project and an artifact carries its run, so the view resolves
         the workspace itself and defaults to the open one. */
      description="Artifacts produced by your runs. Defaults to the open workspace — switch to All workspaces to search the whole API. For one run's downloads, use Runs → Run outputs."
    >
      <MasterDetail
        master={
      <>
        {/* The filter row used to be `flex flex-wrap` holding selects with
            `min-w-[12rem]` and `min-w-[8rem]`. A min-width can't shrink, so the
            row's intrinsic width (~416px) exceeded the master pane (~310px) and
            forced a horizontal scrollbar across the whole list — measured
            scrollWidth 436 vs clientWidth 350. In a narrow pane these controls
            stack full-width instead. */}
        <div className="mb-3 space-y-2">
          <div className="space-y-2">
            {activeProject ? (
              <label className="block text-[11px] font-medium text-ink-500">
                Run
                <select
                  value={runFilter.trim()}
                  onChange={(e) => setRunFilter(e.target.value)}
                  className="mt-0.5 block w-full rounded-lg border border-ink-200 px-2 py-1 text-sm"
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
                Open a workspace for a recent-run picker, or use advanced ID below.
              </p>
            )}
            <label className="block text-[11px] font-medium text-ink-500">
              Type
              <select
                value={artifactTypeFilter}
                onChange={(e) => setArtifactTypeFilter(e.target.value)}
                className="mt-0.5 block w-full rounded-lg border border-ink-200 px-2 py-1 text-sm"
              >
                <option value="">All types</option>
                {typeOptions.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => void load()} className="btn-secondary">
                <RefreshCw className="h-3.5 w-3.5" /> Apply
              </button>
              {hasActiveFilters ? (
                <button type="button" className="btn-quiet text-[12px]" onClick={clearFilters}>
                  Clear filters
                </button>
              ) : null}
            </div>
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
                    initialLoc.runId && runFilter === initialLoc.runId
                      ? 'Prefilled from Runs — edit to broaden filter'
                      : undefined
                  }
                  className={`mt-0.5 block rounded-lg border border-ink-200 px-2 py-1 font-mono text-[11px] ${
                    initialLoc.runId && runFilter === initialLoc.runId
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
          {/* "For one run's downloads use Runs → Run outputs" was stated three times
              on one screen: the page description, here above the list, and again in
              the detail pane's footer. The page description is the right place for
              it, so both repeats are gone. */}
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
                : 'Run a pipeline that produces node outputs, then refresh. Prefer Runs → Run outputs for one run.'
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
                  onClick={() => goView('runs')}
                >
                  Open Runs
                </button>
              )
            }
          />
        ) : (
          <>
            {/* Selecting an artifact adopts its run into the Run filter, so the list
                you were browsing silently collapses to that run's artifacts. Saying
                how many are shown, and why, makes that legible instead of alarming. */}
            {/* Scope toggle. The artifact record has no project field, but it does
                have run_id, and a run record has project — so the workspace view is
                a client-side join over the run ids fetched above, not a missing API. */}
            {activeProject && !runFilter.trim() ? (
              <div className="mb-2 flex overflow-hidden rounded-md border border-ink-200 text-[11px]">
                {(
                  [
                    ['workspace', 'This workspace'],
                    ['all', 'All workspaces'],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={scope === id}
                    className={clsx(
                      'flex-1 px-2 py-1',
                      id === 'all' && 'border-l border-ink-200',
                      scope === id
                        ? 'bg-ink-100 font-medium text-ink-900'
                        : 'bg-white text-ink-500 hover:text-ink-800',
                    )}
                    onClick={() => setScope(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : null}
            <p className="mb-2 text-[12px] text-ink-500">
              {visibleItems.length} artifact{visibleItems.length === 1 ? '' : 's'}
              {runFilter.trim()
                ? ` in run ${shortRunId(runFilter.trim())}`
                : scopedToWorkspace
                  ? ` in ${activeProject}`
                  : ' across all workspaces'}
              {scopedToWorkspace && items.length > visibleItems.length
                ? ` · ${items.length - visibleItems.length} hidden from other workspaces`
                : ''}
            </p>
            {/* Honest about the join's edges rather than implying completeness:
                most runs on this API carry no project at all, so their artifacts
                belong to no workspace view. */}
            {scopedToWorkspace && orphanCount > 0 ? (
              <p className="mb-2 rounded-lg border border-ink-100 bg-ink-50/70 px-2.5 py-1.5 text-[11px] leading-relaxed text-ink-500">
                {orphanCount} artifact{orphanCount === 1 ? '' : 's'} come from runs with no
                workspace recorded, so they appear only under{' '}
                <button
                  type="button"
                  className="font-medium text-accent-800 hover:underline"
                  onClick={() => setScope('all')}
                >
                  All workspaces
                </button>
                .
              </p>
            ) : null}
            {(runsTruncated || listTruncated) && (
              <p className="mb-2 rounded-lg border border-amber-200 bg-amber-50/70 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-900">
                {listTruncated
                  ? 'Showing the first 1000 artifacts — narrow by run or type to see the rest.'
                  : `Scoped using this workspace's ${RUN_SCOPE_LIMIT} most recent runs; artifacts from older runs may be missing.`}
              </p>
            )}
            {scopedToWorkspace && visibleItems.length === 0 ? (
              <p className="rounded-xl border border-dashed border-ink-200 bg-ink-50/50 px-3 py-3 text-[12px] leading-relaxed text-ink-600">
                No artifacts from {activeProject}’s runs yet.{' '}
                <button
                  type="button"
                  className="font-medium text-accent-800 hover:underline"
                  onClick={() => setScope('all')}
                >
                  See all {items.length} across every workspace
                </button>
                .
              </p>
            ) : null}
            <ul className="space-y-2">
            {visibleItems.map((a) => {
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
                    <div className="truncate text-[11px] text-ink-500">
                      {shortRunId(String(a.run_id ?? ''))} · {String(a.artifact_type ?? '—')}
                    </div>
                    {/* Was the full 32-char id, unwrapped, in a ~310px pane — the
                        second source of the horizontal scrollbar, and unreadable
                        besides. The full id is on the detail pane and on Copy path. */}
                    <div className="truncate font-mono text-[10px] text-ink-400" title={id}>
                      {shortRunId(id)}
                    </div>
                  </button>
                </li>
              )
            })}
            </ul>
          </>
        )}
      </>
        }
        detail={
      <div className="space-y-3">
        {!selected ? (
          <EmptyState
            title="Select an artifact"
            description="Inspect this output, download it, open Runs → Lineage, or jump to its run."
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
                  onClick={() => goView('runs')}
                >
                  Open Runs
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
            {/* Which workspace this artifact came from, stated rather than assumed.
                Opening it is now a deliberate click instead of a side effect of
                selecting a row. */}
            {detailProject ? (
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2 text-[12px] text-ink-600">
                <span>
                  Produced in workspace{' '}
                  <span className="font-medium text-ink-900">{detailProject}</span>
                </span>
                {activeProject === detailProject ? (
                  <span className="text-ink-400">· currently open</span>
                ) : (
                  <button
                    type="button"
                    className="ide-quiet-btn text-[11px]"
                    onClick={() => useAppStore.getState().openProject(detailProject)}
                  >
                    Open workspace
                  </button>
                )}
                {!runFilter.trim() ? (
                  <button
                    type="button"
                    className="ide-quiet-btn text-[11px]"
                    onClick={() => setRunFilter(detailRunId)}
                  >
                    Show this run’s artifacts
                  </button>
                ) : null}
              </div>
            ) : null}
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
                    // The artifact's own workspace, not whatever happens to be open.
                    project: linkProject,
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
                  /* Must pass the project: openRun() builds /workspaces/<W>/runs/<id>
                     and silently no-ops when it has no workspace. Needing that is
                     why the view used to force-open a workspace globally; passing
                     the artifact's own project gets the link working without it. */
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => openRun(runId, linkProject ? { project: linkProject } : undefined)}
                  >
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
            {(() => {
              const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
              const consumers =
                rec.consumers ??
                rec.downstream ??
                rec.downstream_consumers ??
                (rec.metadata && typeof rec.metadata === 'object' && !Array.isArray(rec.metadata)
                  ? (rec.metadata as Record<string, unknown>).consumers ??
                    (rec.metadata as Record<string, unknown>).downstream
                  : undefined)
              if (Array.isArray(consumers) && consumers.length > 0) {
                return (
                  <div className="rounded-xl border border-ink-200 bg-white px-3 py-2 space-y-1.5">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                      Downstream consumers
                    </div>
                    <ul className="space-y-1 text-sm text-ink-700">
                      {consumers.map((c, i) => (
                        <li key={i} className="font-mono text-[11px] break-all">
                          {typeof c === 'string' ? c : JSON.stringify(c)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              }
              return (
                /* Was "Downstream consumers — needs provenance API": an internal
                   TODO about a missing backend, shown verbatim to users, who have
                   no idea what a provenance API is or whether they broke it. Says
                   what it means for them and where the answer does live. */
                <div className="rounded-xl border border-dashed border-ink-200 bg-ink-50/50 px-3 py-2 text-sm text-ink-500">
                  No downstream consumers recorded for this artifact. Full provenance is
                  tracked per run — see{' '}
                  <span className="font-medium text-ink-700">Runs → Lineage</span>.
                </div>
              )
            })()}
            {(() => {
              const rec = (detail && typeof detail === 'object' ? detail : {}) as Record<string, unknown>
              const runId = String(rec.run_id ?? '').trim()
              if (!runId) return null
              return (
                <div className="rounded-2xl border border-accent-200/70 bg-accent-50/40 px-4 py-3 space-y-2">
                  <div className="text-[13px] font-semibold text-ink-950">Register model</div>
                  <p className="text-[12px] text-ink-600">
                    Register a model from this artifact&apos;s run ({shortRunId(runId)}) into staging.
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <label className="min-w-[8rem] flex-1 text-[11px] text-ink-500">
                      Name
                      <input
                        className="mt-0.5 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                        value={regModelName}
                        onChange={(e) => setRegModelName(e.target.value)}
                        placeholder="my-model"
                      />
                    </label>
                    <label className="min-w-[8rem] flex-1 text-[11px] text-ink-500">
                      Slug
                      <input
                        className="mt-0.5 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                        value={regModelSlug}
                        onChange={(e) => setRegModelSlug(e.target.value)}
                        placeholder="artifact slug"
                      />
                    </label>
                    {/* registerModelFromArtifact() already bailed with a toast on an
                        empty name, but the button stayed enabled — the same
                        visible-yet-inert control fixed on Home, the picker and
                        Templates. The requirement is knowable before the click. */}
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={registerBusy || !regModelName.trim()}
                      title={!regModelName.trim() ? 'Enter a model name first' : undefined}
                      onClick={() => void registerModelFromArtifact(runId)}
                    >
                      {registerBusy ? 'Registering…' : 'Register model'}
                    </button>
                  </div>
                </div>
              )
            })()}
          </>
        )}
      </div>
        }
      />
    </ViewShell>
  )
}
