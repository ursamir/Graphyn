import React from 'react'
import clsx from 'clsx'
import { Download, RefreshCw, PackagePlus, MoreHorizontal, Search, Trash2 } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from '../../components/ui'
import { formatLocaleDateTime, formatRelativeTime, isIsolatedRuntime } from '../../lib/format'

interface DepSummary {
  missing_required?: string[]
  missing_optional?: string[]
  runtime?: string
}

interface Plugin {
  name: string
  version?: string
  enabled?: boolean
  status?: string
  /** Not actually sent at this level by GET /plugins — kept only as a fallback.
   *  Read via nodeTypesOf(), which prefers `manifest.node_types`. */
  node_types?: string[]
  error?: string | null
  runtime?: string
  installed_at?: string
  dependency_summary?: DepSummary | null
  manifest?: {
    dependencies?: string[]
    optional_dependencies?: string[]
    runtime?: string
    /* All three are sent for every installed plugin and none were rendered:
       the description says what the plugin is for, node_types are the names you
       search for in the Editor catalog, and tags are the only sensible way to
       narrow a 48-item list. */
    description?: string
    node_types?: string[]
    tags?: string[]
  }
}

interface DepRow {
  requirement: string
  name: string
  satisfied: boolean
  installed_version: string | null
  optional: boolean
}

interface DepStatus {
  name: string
  runtime: string
  python?: string | null
  dependencies: DepRow[]
  missing_required: string[]
  missing_optional: string[]
  install_status?: string | null
  install_error?: string | null
  include_optional?: boolean | null
}

type MainTab = 'installed' | 'install'
type StatusFilter = 'all' | 'ok' | 'missing' | 'disabled'

const DEPS_INSTALL_TIMEOUT_MS = 900_000

const DOCS_GETTING_STARTED_MODE_B =
  'https://github.com/ursamir/Graphyn/blob/main/docs/GETTING_STARTED.md#mode-b--multi-machine-control-plane--workers'

function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

/** One-line summary for pip logs — avoid duplicating walls of text in cards + toasts. */
function shortenInstallError(msg: string, max = 220): string {
  const trimmed = msg.trim()
  if (!trimmed) return 'Install failed'
  const lines = trimmed
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  // Prefer pip's concrete reason over our wrapper "pip install failed for […]".
  const interesting =
    [...lines]
      .reverse()
      .find((l) =>
        /ERROR:|Could not find|No matching distribution|ResolutionImpossible|conflict|incompatible|Some optional packages failed/i.test(
          l,
        ),
      ) ||
    lines.find((l) => /failed|error/i.test(l) && !/^pip install failed for \[/i.test(l)) ||
    lines[0] ||
    trimmed
  return interesting.length > max ? `${interesting.slice(0, max - 1)}…` : interesting
}

function installStatusLabel(status: string | null | undefined): string | null {
  if (!status) return null
  if (status === 'installing') return 'installing…'
  if (status === 'installed') return 'install finished'
  if (status === 'failed') return 'install failed'
  return status
}

/** Bare package name from a requirement string (`torch>=2.0` → `torch`). */
function reqPackageName(req: string): string {
  const raw = req.trim().split(/\s+/)[0] || req
  return raw.replace(/\[.*$/, '').split(/[<=>!~]/)[0].trim().toLowerCase()
}

/** Human list of packages for progress copy (no fake “PyTorch” when installing something else). */
function summarizePackages(reqs: string[], maxNames = 3): string {
  const names = Array.from(
    new Set(reqs.map(reqPackageName).filter(Boolean)),
  )
  if (names.length === 0) return ''
  if (names.length <= maxNames) return names.join(', ')
  return `${names.slice(0, maxNames).join(', ')} +${names.length - maxNames} more`
}

function installProgressCopy(opts: {
  includeOptional: boolean
  packageNames: string[]
  isolated: boolean
}): { title: string; detail: string } {
  const { includeOptional, packageNames, isolated } = opts
  const what = includeOptional ? 'optional extras' : 'required deps'
  const pkgs = summarizePackages(packageNames)
  const title = pkgs
    ? `Installing ${what}: ${pkgs}…`
    : `Installing ${what}…`
  const detail = isolated
    ? 'Into this plugin’s isolated venv — large wheels can take several minutes.'
    : 'Into the shared API Python — large wheels can take several minutes.'
  return { title, detail }
}

function pluginBucket(p: Plugin): StatusFilter {
  if (p.enabled === false) return 'disabled'
  const missingReq = p.dependency_summary?.missing_required?.length ?? 0
  if (missingReq > 0 || p.status === 'failed') return 'missing'
  return 'ok'
}

/**
 * Node types a plugin contributes to the Editor catalog.
 *
 * The card read `p.node_types` and the interface declared it, but the API only
 * ever sends it nested under `manifest` — so across all 48 installed plugins the
 * optional chain quietly resolved to undefined and the "N nodes" chip never
 * rendered once. Optional chaining on a field that is always absent fails
 * silently and looks correct in review; only diffing the declared type against
 * the actual payload catches it.
 */
function nodeTypesOf(p: Plugin): string[] {
  const fromManifest = p.manifest?.node_types
  if (Array.isArray(fromManifest) && fromManifest.length) return fromManifest
  return Array.isArray(p.node_types) ? p.node_types : []
}

function tagsOf(p: Plugin): string[] {
  const t = p.manifest?.tags
  return Array.isArray(t) ? t : []
}

type PluginSort = 'name' | 'installed' | 'nodes'

const PLUGIN_SORT_LABEL: Record<PluginSort, string> = {
  name: 'Name (A–Z)',
  installed: 'Recently installed',
  nodes: 'Most node types',
}

export default function PluginsView() {
  const refreshCatalog = useAppStore((s) => s.refreshCatalog)
  const pushToast = useAppStore((s) => s.pushToast)
  const [plugins, setPlugins] = React.useState<Plugin[] | null>(null)
  const [mainTab, setMainTab] = React.useState<MainTab>('installed')
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>('all')
  /* The Installed tab had four status pills and no text search at all — 48
     plugins with no way to find one by name, by what it does, or by the node
     type it contributes. */
  const [listQuery, setListQuery] = React.useState('')
  const [activeTags, setActiveTags] = React.useState<string[]>([])
  const [runtimeFilter, setRuntimeFilter] = React.useState<'all' | 'isolated' | 'inprocess'>('all')
  const [pluginSort, setPluginSort] = React.useState<PluginSort>('name')
  const [menuUp, setMenuUp] = React.useState(false)
  const toggleTag = (t: string) =>
    setActiveTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))
  const [source, setSource] = React.useState('')
  const [upgrade, setUpgrade] = React.useState(false)
  const [sha, setSha] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [searchHits, setSearchHits] = React.useState<Array<Record<string, unknown>>>([])
  const [searchState, setSearchState] = React.useState<'idle' | 'ok' | 'empty' | 'error'>('idle')
  const [error, setError] = React.useState<string | null>(null)
  const [expanded, setExpanded] = React.useState<string | null>(null)
  const [menuFor, setMenuFor] = React.useState<string | null>(null)
  const [depStatus, setDepStatus] = React.useState<DepStatus | null>(null)
  const [installingName, setInstallingName] = React.useState<string | null>(null)
  const [installingOptional, setInstallingOptional] = React.useState(false)
  const [installingPackages, setInstallingPackages] = React.useState<string[]>([])
  const [installStartedAt, setInstallStartedAt] = React.useState<number | null>(null)
  const [depInstallErrors, setDepInstallErrors] = React.useState<Record<string, string>>({})
  const [pkgInstalling, setPkgInstalling] = React.useState<string | null>(null)
  const [pkgInstallError, setPkgInstallError] = React.useState<string | null>(null)
  const [elapsedTick, setElapsedTick] = React.useState(0)
  const [venvGcBusy, setVenvGcBusy] = React.useState(false)
  const pollRef = React.useRef<number | null>(null)
  const depPollRef = React.useRef<number | null>(null)

  const clearDepPoll = React.useCallback(() => {
    if (depPollRef.current) {
      window.clearInterval(depPollRef.current)
      depPollRef.current = null
    }
  }, [])

  const load = React.useCallback(async () => {
    setError(null)
    try {
      setPlugins(await apiJson<Plugin[]>('/plugins'))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPlugins([])
    }
  }, [])

  React.useEffect(() => {
    void load()
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
      if (depPollRef.current) window.clearInterval(depPollRef.current)
    }
  }, [load])

  React.useEffect(() => {
    if (!installingName || !installStartedAt) return
    const id = window.setInterval(() => setElapsedTick((t) => t + 1), 1000)
    return () => window.clearInterval(id)
  }, [installingName, installStartedAt])

  const afterMutation = async (opts?: { announceCatalog?: boolean }) => {
    await load()
    await refreshCatalog?.()
    if (opts?.announceCatalog) {
      pushToast('Editor catalog refreshed', 'success')
    }
  }

  const pollInstall = (name: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current)
    setPkgInstalling(name)
    setPkgInstallError(null)
    pollRef.current = window.setInterval(() => {
      void apiJson<Plugin>(`/plugins/${encodeURIComponent(name)}`)
        .then(async (rec) => {
          if (rec.status === 'installed' || rec.status === 'failed') {
            if (pollRef.current) window.clearInterval(pollRef.current)
            setPkgInstalling(null)
            if (rec.status === 'failed') {
              const msg = rec.error ?? `Install failed: ${name}`
              setPkgInstallError(msg)
              pushToast(msg, 'error')
            } else {
              setPkgInstallError(null)
              pushToast(`Installed ${name}`, 'success')
              setMainTab('installed')
            }
            await afterMutation({ announceCatalog: rec.status !== 'failed' })
          }
        })
        .catch(() => undefined)
    }, 1500)
  }

  const finishDepsInstall = React.useCallback(
    async (name: string, includeOptional: boolean, failed?: string | null) => {
      clearDepPoll()
      setInstallingName(null)
      setInstallStartedAt(null)
      setInstallingPackages([])
      if (failed) {
        const short = shortenInstallError(failed)
        setDepInstallErrors((prev) => ({ ...prev, [name]: short }))
      } else {
        setDepInstallErrors((prev) => {
          const next = { ...prev }
          delete next[name]
          return next
        })
        pushToast(
          includeOptional ? `Installed extras for ${name}` : `Installed required deps for ${name}`,
          'success',
        )
      }
      await afterMutation({ announceCatalog: !failed })
      if (expanded === name) {
        try {
          setDepStatus(await apiJson<DepStatus>(`/plugins/${encodeURIComponent(name)}/dependencies`))
        } catch {
          /* keep prior */
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [clearDepPoll, expanded, pushToast, refreshCatalog],
  )

  const pollDepsInstall = React.useCallback(
    (name: string, includeOptional: boolean) => {
      clearDepPoll()
      depPollRef.current = window.setInterval(() => {
        void apiJson<DepStatus>(`/plugins/${encodeURIComponent(name)}/dependencies`)
          .then(async (status) => {
            if (expanded === name) setDepStatus(status)
            const job = status.install_status
            if (job === 'installed') {
              await finishDepsInstall(name, includeOptional)
            } else if (job === 'failed') {
              await finishDepsInstall(name, includeOptional, status.install_error || `Dependency install failed for ${name}`)
            }
          })
          .catch(() => undefined)
      }, 2000)
    },
    [clearDepPoll, expanded, finishDepsInstall],
  )

  const install = async () => {
    setPkgInstallError(null)
    try {
      const res = await apiJson<{ name?: string; status?: string }>('/plugins/install', {
        method: 'POST',
        body: JSON.stringify({
          source,
          upgrade,
          expected_sha256: sha.trim() || null,
        }),
      })
      const name = res.name ?? source
      if (res.status === 'installing') {
        pushToast(`Installing ${name}…`, 'info')
        pollInstall(name)
      } else if (res.status === 'installed' || res.status == null) {
        pushToast(`Installed ${name}`, 'success')
        setPkgInstalling(null)
        setMainTab('installed')
        await afterMutation({ announceCatalog: true })
      } else if (res.status === 'failed') {
        const msg = `Install failed for ${name}`
        setPkgInstallError(msg)
        pushToast(msg, 'error')
      } else {
        pushToast(`Install status: ${res.status ?? 'unknown'}`, 'info')
        pollInstall(name)
      }
      setSource('')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPkgInstallError(msg)
      pushToast(msg, 'error')
    }
  }

  const searchIndex = async () => {
    try {
      const hits = await apiJson<Array<Record<string, unknown>>>('/plugins/search', {
        query: { q: query },
      })
      setSearchHits(hits)
      setSearchState(hits.length === 0 ? 'empty' : 'ok')
    } catch (err) {
      setSearchHits([])
      setSearchState('error')
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const toggleDeps = async (name: string) => {
    if (expanded === name) {
      setExpanded(null)
      setDepStatus(null)
      return
    }
    setExpanded(name)
    try {
      setDepStatus(await apiJson<DepStatus>(`/plugins/${encodeURIComponent(name)}/dependencies`))
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
      setDepStatus(null)
    }
  }

  const installDeps = async (name: string, includeOptional: boolean) => {
    if (installingName) return
    setDepInstallErrors((prev) => {
      const next = { ...prev }
      delete next[name]
      return next
    })
    const plug = plugins?.find((x) => x.name === name)
    const runtime =
      plug?.runtime ?? plug?.dependency_summary?.runtime ?? plug?.manifest?.runtime ?? 'inprocess'
    const isolated = isIsolatedRuntime(runtime, name)
    // Prefer currently-missing list; fall back to declared deps so the banner still names packages.
    const missingOnly = includeOptional
      ? plug?.dependency_summary?.missing_optional ?? []
      : plug?.dependency_summary?.missing_required ?? []
    const declared = includeOptional
      ? plug?.manifest?.optional_dependencies ?? []
      : plug?.manifest?.dependencies ?? []
    const packageNames = (missingOnly.length ? missingOnly : declared).map(String)
    setInstallingName(name)
    setInstallingOptional(includeOptional)
    setInstallingPackages(packageNames)
    setInstallStartedAt(Date.now())
    try {
      const res = await apiJson<DepStatus & { status?: string }>(
        `/plugins/${encodeURIComponent(name)}/dependencies/install`,
        {
          method: 'POST',
          body: JSON.stringify({ include_optional: includeOptional }),
          timeoutMs: DEPS_INSTALL_TIMEOUT_MS,
        },
      )
      if (res.status === 'installing' || res.install_status === 'installing') {
        const copy = installProgressCopy({
          includeOptional,
          packageNames,
          isolated,
        })
        pushToast(`${copy.title} ${copy.detail}`, 'info')
        if (expanded !== name) {
          setExpanded(name)
        }
        try {
          setDepStatus(await apiJson<DepStatus>(`/plugins/${encodeURIComponent(name)}/dependencies`))
        } catch {
          /* ignore */
        }
        pollDepsInstall(name, includeOptional)
        return
      }
      if (Array.isArray(res.dependencies)) {
        setDepStatus(res)
      }
      await finishDepsInstall(name, includeOptional)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      clearDepPoll()
      setInstallingName(null)
      setInstallStartedAt(null)
      setInstallingPackages([])
      setDepInstallErrors((prev) => ({ ...prev, [name]: shortenInstallError(msg) }))
    }
  }

  const setEnabled = async (name: string, enable: boolean) => {
    const action = enable ? 'enable' : 'disable'
    try {
      await apiJson(`/plugins/${encodeURIComponent(name)}/${action}`, { method: 'POST' })
      await afterMutation()
      pushToast(`${enable ? 'Enabled' : 'Disabled'} ${name}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const liveElapsed =
    installingName && installStartedAt ? Date.now() - installStartedAt : 0
  void elapsedTick

  const matchesStatusAndSearch = React.useCallback(
    (p: Plugin) => {
      if (statusFilter !== 'all' && pluginBucket(p) !== statusFilter) return false
      if (runtimeFilter !== 'all') {
        const rt = p.runtime ?? p.dependency_summary?.runtime ?? p.manifest?.runtime ?? 'inprocess'
        const isolated = isIsolatedRuntime(rt, p.name)
        if (runtimeFilter === 'isolated' ? !isolated : isolated) return false
      }
      const q = listQuery.trim().toLowerCase()
      if (!q) return true
      return [p.name, p.version ?? '', p.manifest?.description ?? '', ...tagsOf(p), ...nodeTypesOf(p)]
        .join(' ')
        .toLowerCase()
        .includes(q)
    },
    [statusFilter, runtimeFilter, listQuery],
  )

  /* Tag counts come from the status+search+runtime result, not the tag-filtered
     list — otherwise picking one tag zeroes every other count and you can never
     widen the selection without clearing first. (Same rule as Templates.) */
  const tagPool = React.useMemo(
    () => (plugins ?? []).filter(matchesStatusAndSearch),
    [plugins, matchesStatusAndSearch],
  )
  const tagFacets = React.useMemo(() => {
    const counts = new Map<string, number>()
    for (const p of tagPool) for (const t of tagsOf(p)) counts.set(t, (counts.get(t) ?? 0) + 1)
    return [...counts.entries()]
      /* n > 2, not > 1: these 48 manifests carry ~34 tags used exactly twice,
         which filled the bar with two wrapped rows of near-useless chips. The
         long tail stays reachable — search matches tags, and a tag clicked on a
         card joins the bar because activeTags is always included here. */
      .filter(([t, n]) => n > 2 || activeTags.includes(t))
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [tagPool, activeTags])

  const filtered = React.useMemo(() => {
    if (!plugins) return null
    return tagPool
      .filter((p) => activeTags.every((t) => tagsOf(p).includes(t)))
      .sort((a, b) => {
        if (pluginSort === 'nodes') {
          return nodeTypesOf(b).length - nodeTypesOf(a).length || a.name.localeCompare(b.name)
        }
        if (pluginSort === 'installed') {
          const t = (v?: string) => {
            const n = v ? Date.parse(v) : NaN
            return Number.isNaN(n) ? 0 : n
          }
          return t(b.installed_at) - t(a.installed_at) || a.name.localeCompare(b.name)
        }
        return a.name.localeCompare(b.name)
      })
  }, [plugins, tagPool, activeTags, pluginSort])

  const filterCounts = React.useMemo(() => {
    const counts = { all: 0, ok: 0, missing: 0, disabled: 0 }
    for (const p of plugins ?? []) {
      counts.all += 1
      counts[pluginBucket(p)] += 1
    }
    return counts
  }, [plugins])

  const tabs: Array<{ id: MainTab; label: string }> = [
    { id: 'installed', label: `Installed${plugins ? ` (${plugins.length})` : ''}` },
    { id: 'install', label: 'Install / Search' },
  ]

  const statusFilters: Array<{ id: StatusFilter; label: string }> = [
    { id: 'all', label: `All (${filterCounts.all})` },
    { id: 'ok', label: `Ok (${filterCounts.ok})` },
    { id: 'missing', label: `Missing deps (${filterCounts.missing})` },
    { id: 'disabled', label: `Disabled (${filterCounts.disabled})` },
  ]

  return (
    <div className="h-full min-h-0 overflow-y-auto p-8 space-y-6">
      <PageHeader
        title="Plugins"
        description="Library — install node packs for the Editor catalog."
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              disabled={venvGcBusy}
              onClick={() => {
                setVenvGcBusy(true)
                void apiJson<{ removed?: string[] }>('/plugins/venvs/gc', { method: 'POST' })
                  .then((res) => {
                    const n = Array.isArray(res?.removed) ? res.removed.length : 0
                    pushToast(
                      n
                        ? `Removed ${n} unused plugin venv${n === 1 ? '' : 's'}`
                        : 'No unused plugin venvs to remove',
                      'success',
                    )
                  })
                  .catch((err) =>
                    pushToast(err instanceof Error ? err.message : String(err), 'error'),
                  )
                  .finally(() => setVenvGcBusy(false))
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
              {venvGcBusy ? 'Cleaning…' : 'Clean unused venvs'}
            </button>
            <button type="button" className="btn-secondary" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        }
      />
      <p className="rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
        <span className="font-medium text-ink-800">Deps:</span>{' '}
        <span className="font-mono text-[11px]">inprocess</span> installs into the shared API Python;{' '}
        <span className="font-mono text-[11px]">isolated</span> creates{' '}
        <span className="font-mono text-[11px]">~/.graphyn/plugins/venvs/&lt;name&gt;</span> (heavy ML
        stacks). Reinstall/upgrade a plugin after changing its runtime. Mode B workers need the same
        packs —{' '}
        <a
          href={DOCS_GETTING_STARTED_MODE_B}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-accent-700 hover:underline"
        >
          Getting Started
        </a>
        .
      </p>
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="flex flex-wrap gap-1 border-b border-ink-200/80 pb-0">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setMainTab(t.id)}
            className={
              mainTab === t.id
                ? 'border-b-2 border-accent-600 px-3 py-2 text-[13px] font-semibold text-ink-950'
                : 'px-3 py-2 text-[13px] text-ink-500 hover:text-ink-800'
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Both forms were laid out full-bleed in a ~1300px card: the source input
          stretched the whole page for a short package string while the search box
          next to it was 200px, so two similar fields looked unrelated. Capped and
          matched. */}
      {mainTab === 'install' && (
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="surface-card space-y-3 p-5">
            <h3 className="text-sm font-semibold">Install from source</h3>
            <p className="text-type-meta text-ink-500">
              A local path, a PyPI package name, an https:// archive, or a{' '}
              <span className="font-mono">git+</span> URL.
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="path, package, https://…, git+…"
                aria-label="Plugin source"
                className="min-w-0 max-w-md flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm"
              />
              <button
                type="button"
                className="btn-primary shrink-0"
                disabled={!source.trim() || !!pkgInstalling}
                title={!source.trim() ? 'Enter a path, package or URL first' : undefined}
                onClick={() => void install()}
              >
                <Download className="h-3.5 w-3.5" /> Install
              </button>
            </div>
            <details className="rounded-lg border border-ink-100 bg-ink-50 px-3 py-2">
              <summary className="cursor-pointer select-none text-xs font-medium text-ink-600">Advanced</summary>
              <div className="mt-2 space-y-2">
                <input
                  value={sha}
                  onChange={(e) => setSha(e.target.value)}
                  placeholder="SHA256 (optional expected_sha256)"
                  className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm font-mono"
                />
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={upgrade} onChange={(e) => setUpgrade(e.target.checked)} />
                  Upgrade if installed
                </label>
              </div>
            </details>
            {pkgInstalling && (
              <div className="flex items-start gap-2 rounded-xl border border-accent-200 bg-accent-50/60 px-3 py-2 text-sm text-ink-700">
                <span className="mt-0.5 inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent-500 border-t-transparent" />
                <div>
                  <div className="font-medium">Installing {pkgInstalling}…</div>
                  <div className="text-type-meta text-ink-500">Progress updates when the install job finishes.</div>
                </div>
              </div>
            )}
            {pkgInstallError && (
              <ErrorBanner message={pkgInstallError} onDismiss={() => setPkgInstallError(null)} />
            )}
          </section>

          <section className="surface-card space-y-3 p-5">
            <h3 className="text-sm font-semibold">Search index</h3>
            {/* "Search index" never said what index. The page only admitted it needs
                a configured plugin directory once a search had already failed. */}
            <p className="text-type-meta text-ink-500">
              Looks up packages in the configured plugin directory. Not connected to the
              Installed tab’s search, which filters what you already have.
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="min-w-0 max-w-md flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm"
                placeholder="package name"
                aria-label="Package name to search"
                onKeyDown={(e) => e.key === 'Enter' && query.trim() && void searchIndex()}
              />
              <button
                type="button"
                className="btn-secondary shrink-0"
                disabled={!query.trim()}
                title={!query.trim() ? 'Enter a package name first' : undefined}
                onClick={() => void searchIndex()}
              >
                Search
              </button>
            </div>
            {(searchState === 'empty' || searchState === 'error') && (
              <p className="text-sm text-ink-500">
                No plugin directory configured. Install from a path, git URL, or package name.
              </p>
            )}
            {searchState === 'ok' &&
              searchHits.map((h, i) => (
                <div key={i} className="flex justify-between rounded-lg border border-ink-100 px-2 py-1.5 text-sm">
                  <span>{String(h.name ?? h.id ?? i)}</span>
                  <button
                    type="button"
                    className="text-accent-700"
                    onClick={() => setSource(String(h.source ?? h.url ?? h.name ?? ''))}
                  >
                    Use
                  </button>
                </div>
              ))}
          </section>
        </div>
      )}

      {mainTab === 'installed' && (
        <section className="surface-card p-5 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[13rem] flex-1 sm:max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
              <input
                value={listQuery}
                onChange={(e) => setListQuery(e.target.value)}
                placeholder="Search name, description, node type…"
                aria-label="Search installed plugins"
                className="w-full rounded-lg border border-ink-200 bg-white py-1.5 pl-8 pr-2 text-sm"
              />
            </div>
            <label className="flex items-center gap-1.5 text-[12px] text-ink-500">
              Runtime
              <select
                className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                value={runtimeFilter}
                onChange={(e) =>
                  setRuntimeFilter(e.target.value as 'all' | 'isolated' | 'inprocess')
                }
              >
                <option value="all">Any</option>
                <option value="isolated">Isolated venv</option>
                <option value="inprocess">Shared env</option>
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-[12px] text-ink-500">
              Sort
              <select
                className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                value={pluginSort}
                onChange={(e) => setPluginSort(e.target.value as PluginSort)}
              >
                {(Object.keys(PLUGIN_SORT_LABEL) as PluginSort[]).map((k) => (
                  <option key={k} value={k}>
                    {PLUGIN_SORT_LABEL[k]}
                  </option>
                ))}
              </select>
            </label>
            <span className="ml-auto text-[12px] text-ink-400">
              {plugins == null ? 'Loading…' : `${filtered?.length ?? 0} of ${plugins.length} shown`}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {statusFilters.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setStatusFilter(f.id)}
                className={
                  statusFilter === f.id
                    ? 'rounded-full border border-accent-300 bg-accent-50 px-2.5 py-1 text-[12px] font-semibold text-accent-900'
                    : 'rounded-full border border-ink-200 bg-white px-2.5 py-1 text-[12px] text-ink-600 hover:border-ink-300'
                }
              >
                {f.label}
              </button>
            ))}
          </div>
          {/* Tag facets, mirroring Templates: manifest tags were fetched for every
              plugin and shown nowhere, so the only way to find "the audio ones"
              was to read all 48 names. */}
          {tagFacets.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-ink-400">
                Tag
              </span>
              {tagFacets.map(([t, n]) => {
                const on = activeTags.includes(t)
                return (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={on}
                    className={clsx(
                      'rounded-md border px-1.5 py-0.5 text-[11px] transition',
                      on
                        ? 'border-accent-400 bg-accent-50 font-medium text-accent-900'
                        : 'border-ink-200 bg-white text-ink-600 hover:border-accent-300 hover:text-accent-800',
                    )}
                    onClick={() => toggleTag(t)}
                  >
                    {t} <span className={on ? 'text-accent-700' : 'text-ink-400'}>{n}</span>
                  </button>
                )
              })}
              {activeTags.length > 0 && (
                <button
                  type="button"
                  className="ml-1 text-[11px] font-medium text-ink-500 hover:text-ink-900"
                  onClick={() => setActiveTags([])}
                >
                  Clear {activeTags.length} tag{activeTags.length === 1 ? '' : 's'}
                </button>
              )}
            </div>
          )}

          {plugins === null ? (
            <LoadingBlock />
          ) : plugins.length === 0 ? (
            <EmptyState
              title="No plugins installed"
              description="Install a package, path, or git URL to add nodes to the Editor catalog."
              action={
                <button type="button" className="btn-secondary" onClick={() => setMainTab('install')}>
                  Go to Install / Search
                </button>
              }
            />
          ) : filtered && filtered.length === 0 ? (
            <div className="py-6 text-center">
              <p className="text-sm text-ink-500">
                No plugins match{listQuery.trim() ? ` “${listQuery.trim()}”` : ' this filter'}
                {activeTags.length ? ` with tag${activeTags.length === 1 ? '' : 's'} ${activeTags.join(' + ')}` : ''}.
              </p>
              {(activeTags.length > 0 || listQuery.trim() || runtimeFilter !== 'all' || statusFilter !== 'all') && (
                <button
                  type="button"
                  className="btn-secondary mt-3"
                  onClick={() => {
                    setActiveTags([])
                    setListQuery('')
                    setRuntimeFilter('all')
                    setStatusFilter('all')
                  }}
                >
                  Clear all filters
                </button>
              )}
            </div>
          ) : (
            /* Two columns on wide screens. Each card was full-width (~1300px) for
               ~140px of content, so 48 plugins meant an enormous scroll with a huge
               dead gap between the text on the left and the ⋯ menu on the right.
               A card that expands its dependency panel spans both columns so the
               table inside it isn't cramped. */
            <ul className="grid gap-2 xl:grid-cols-2">
              {(filtered ?? []).map((p) => {
                const missingReq = p.dependency_summary?.missing_required?.length ?? 0
                const showMissingOptCount = p.dependency_summary?.missing_optional?.length ?? 0
                const optionalDeclared =
                  (p.manifest?.optional_dependencies?.length ?? 0) > 0 || showMissingOptCount > 0
                const runtime = p.runtime ?? p.dependency_summary?.runtime ?? p.manifest?.runtime ?? 'inprocess'
                const isolated = isIsolatedRuntime(runtime, p.name)
                const isExpanded = expanded === p.name
                const panelMissingOpt = depStatus?.missing_optional?.length ?? showMissingOptCount
                const panelMissingReq = depStatus?.missing_required?.length ?? missingReq
                const panelHasOptional =
                  (depStatus?.dependencies.some((d) => d.optional) ?? false) ||
                  optionalDeclared ||
                  panelMissingOpt > 0 ||
                  (p.manifest?.optional_dependencies?.length ?? 0) > 0
                const busy = installingName === p.name
                const anyBusy = installingName != null
                const apiInstallFailed =
                  isExpanded &&
                  depStatus?.install_status === 'failed' &&
                  depStatus.install_error
                    ? shortenInstallError(String(depStatus.install_error))
                    : ''
                const cardError =
                  (busy ? '' : depInstallErrors[p.name] || apiInstallFailed) ||
                  (p.status === 'failed' && p.error ? shortenInstallError(String(p.error)) : '')
                return (
                  <li
                    key={p.name}
                    className={clsx(
                      'rounded-2xl border border-ink-200/70 bg-white px-3.5 py-3 shadow-sm',
                      // The dependency panel is a table; give it the full width.
                      isExpanded && 'xl:col-span-2',
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-type-body">
                          {p.name} {p.version ? `v${p.version}` : ''}
                        </div>
                        {/* Every installed plugin ships a description and this page
                            rendered none of them — the one line that says what a
                            plugin is actually for. */}
                        {p.manifest?.description ? (
                          <p className="mt-0.5 line-clamp-2 text-type-secondary text-ink-600">
                            {p.manifest.description}
                          </p>
                        ) : null}
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-type-meta text-ink-500">
                          <StatusBadge status={p.enabled === false ? 'disabled' : p.status ?? 'enabled'} />
                          <span
                            className={clsx(
                              'rounded px-1.5 py-0.5 font-mono text-type-mono',
                              isolated ? 'bg-accent-50 text-accent-900' : 'bg-ink-50 text-ink-600',
                            )}
                            title={
                              isolated
                                ? 'Optional/required deps install into a per-plugin venv'
                                : 'Deps install into the shared API Python environment'
                            }
                          >
                            {isolated ? 'isolated venv' : 'shared env'}
                          </span>
                          {/* Only the exceptional state is loud. "required deps ok"
                              used to print in green on all 48 rows, which is the
                              same noise as badging every project "DRAFT" — it made
                              the one row that actually needs attention harder to
                              spot, not easier. */}
                          {missingReq > 0 ? (
                            <span className="font-medium text-amber-700">
                              {missingReq} missing required
                            </span>
                          ) : null}
                          {showMissingOptCount > 0 ? (
                            <span className="text-amber-700">{showMissingOptCount} missing optional</span>
                          ) : optionalDeclared ? (
                            <span className="text-ink-500">optional extras available</span>
                          ) : null}
                          {p.installed_at ? (
                            <span title={formatLocaleDateTime(p.installed_at)}>
                              installed {formatRelativeTime(p.installed_at)}
                            </span>
                          ) : null}
                        </div>
                        {/* Node types are what you type into the Editor catalog, so
                            they're the most searchable thing a plugin has — and the
                            card previously showed only a count, which never rendered
                            (see nodeTypesOf). Tags double as the facet control. */}
                        {(() => {
                          const nodeTypes = nodeTypesOf(p)
                          const tags = tagsOf(p)
                          if (!nodeTypes.length && !tags.length) return null
                          return (
                            <div className="mt-1.5 flex flex-wrap items-center gap-1">
                              {/* Labelled: node types and tags are different kinds of
                                  thing but rendered as one undifferentiated row of
                                  chips, so `alignment_node` read as just another tag. */}
                              {nodeTypes.length ? (
                                <span className="mr-0.5 text-[10px] uppercase tracking-wide text-ink-400">
                                  Nodes
                                </span>
                              ) : null}
                              {nodeTypes.slice(0, 4).map((nt) => (
                                <span
                                  key={nt}
                                  className="rounded-md bg-ink-50 px-1.5 py-0.5 font-mono text-type-mono text-ink-600"
                                  title={`Node type “${nt}” — appears in the Editor catalog`}
                                >
                                  {nt}
                                </span>
                              ))}
                              {nodeTypes.length > 4 ? (
                                <span className="text-type-meta text-ink-400">
                                  +{nodeTypes.length - 4}
                                </span>
                              ) : null}
                              {tags.slice(0, 4).map((t) => {
                                const on = activeTags.includes(t)
                                return (
                                  <button
                                    key={t}
                                    type="button"
                                    aria-pressed={on}
                                    title={on ? `Stop filtering by ${t}` : `Show only ${t} plugins`}
                                    className={clsx(
                                      'rounded-full border px-1.5 py-px text-type-meta transition',
                                      on
                                        ? 'border-accent-400 bg-accent-50 font-medium text-accent-900'
                                        : 'border-ink-200/80 text-ink-500 hover:border-accent-300 hover:text-accent-800',
                                    )}
                                    onClick={() => toggleTag(t)}
                                  >
                                    {t}
                                  </button>
                                )
                              })}
                            </div>
                          )
                        })()}
                        {/* Collapsed: exactly one dep CTA */}
                        {!isExpanded && (
                          <div className="mt-2">
                            {missingReq > 0 ? (
                              <button
                                type="button"
                                className="btn-primary"
                                disabled={anyBusy}
                                onClick={() => void installDeps(p.name, false)}
                              >
                                <PackagePlus className="h-3.5 w-3.5" /> Install required deps
                              </button>
                            ) : showMissingOptCount > 0 ? (
                              /* Quiet, not secondary: optional extras are a
                                 maintenance action, but styled as a filled button
                                 it was the loudest thing on the card — louder than
                                 the plugin's own name — on half the list. */
                              <button
                                type="button"
                                className="btn-quiet"
                                disabled={anyBusy}
                                onClick={() => void installDeps(p.name, true)}
                                title={
                                  isolated
                                    ? 'Install optional extras into this plugin’s isolated venv — not into the API image'
                                    : 'Installs into the shared API Python — heavy ML extras often fail here; prefer isolated runtime'
                                }
                              >
                                <PackagePlus className="h-3.5 w-3.5" />
                                {isolated ? 'Install optional (venv)' : 'Install optional (shared)'}
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="btn-quiet"
                                onClick={() => void toggleDeps(p.name)}
                              >
                                Manage dependencies
                              </button>
                            )}
                          </div>
                        )}
                        {isExpanded && (
                          <div className="mt-2">
                            <button
                              type="button"
                              className="btn-quiet"
                              onClick={() => void toggleDeps(p.name)}
                            >
                              Hide dependencies
                            </button>
                          </div>
                        )}
                      </div>
                      <div className="relative">
                        <button
                          type="button"
                          className="btn-icon"
                          aria-label={`Actions for ${p.name}`}
                          aria-expanded={menuFor === p.name}
                          aria-haspopup="menu"
                          onClick={(e) => {
                            if (menuFor === p.name) {
                              setMenuFor(null)
                              return
                            }
                            /* Flip above the trigger near the window edge — with 48
                               rows the last few opened off-screen and Uninstall was
                               unreachable (same fix as Workspaces and Templates). */
                            const rect = e.currentTarget.getBoundingClientRect()
                            setMenuUp(window.innerHeight - rect.bottom < 170)
                            setMenuFor(p.name)
                          }}
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                        {menuFor === p.name && (
                          <div
                            role="menu"
                            className={clsx(
                              'absolute right-0 z-20 w-52 rounded-2xl border border-ink-200 bg-white p-1.5 shadow-soft',
                              menuUp ? 'bottom-full mb-1' : 'top-full mt-1',
                            )}
                          >
                            <button type="button" className="btn-quiet w-full justify-start" onClick={() => { void toggleDeps(p.name); setMenuFor(null) }}>
                              Dependencies
                            </button>
                            {p.enabled === false ? (
                              <button type="button" className="btn-quiet w-full justify-start" onClick={() => { void setEnabled(p.name, true); setMenuFor(null) }}>
                                Enable
                              </button>
                            ) : (
                              <button type="button" className="btn-quiet w-full justify-start" onClick={() => { void setEnabled(p.name, false); setMenuFor(null) }}>
                                Disable
                              </button>
                            )}
                            <div className="mt-1 border-t border-ink-100 pt-1">
                              <ConfirmButton
                                label="Uninstall"
                                confirmLabel="Confirm uninstall"
                                danger
                                onConfirm={() =>
                                  void apiJson(`/plugins/${encodeURIComponent(p.name)}`, { method: 'DELETE' })
                                    .then(() => afterMutation())
                                    .then(() => {
                                      setMenuFor(null)
                                      pushToast(`Uninstalled ${p.name}`, 'success')
                                    })
                                    .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
                                }
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                    {/* This sentence used to print on every isolated plugin — 16 copies
                        of one general fact that the "Deps:" banner at the top of the
                        page already states. It now lives on the button's tooltip,
                        where it applies to the action that needs it. */}
                    {busy && (
                      <div className="mt-3 flex items-start gap-2 rounded-xl border border-accent-200 bg-accent-50/60 px-3 py-2 text-sm text-ink-700">
                        <span className="mt-0.5 inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent-500 border-t-transparent" />
                        <div>
                          {(() => {
                            const copy = installProgressCopy({
                              includeOptional: installingOptional,
                              packageNames: installingPackages,
                              isolated,
                            })
                            return (
                              <>
                                <div className="font-medium">{copy.title}</div>
                                <div className="text-type-meta text-ink-500">
                                  {copy.detail} Elapsed {formatElapsed(liveElapsed)}
                                </div>
                              </>
                            )
                          })()}
                        </div>
                      </div>
                    )}
                    {cardError && !busy && (
                      <div className="mt-2 space-y-1">
                        <p
                          className="rounded-lg border border-rose-100 bg-rose-50/80 px-2.5 py-1.5 text-[12px] leading-snug text-rose-900"
                          title={cardError}
                        >
                          {cardError}
                        </p>
                        {!isolated ? (
                          <p className="text-[11px] text-ink-500">
                            Shared-env installs often fail for heavy ML extras. After upgrading this
                            plugin to <span className="font-mono">runtime=isolated</span>, use{' '}
                            <span className="font-medium">Install optional (venv)</span>.
                          </p>
                        ) : null}
                      </div>
                    )}
                    {isExpanded && depStatus && (
                      <div className="mt-3 space-y-2 border-t border-ink-100 pt-3 text-sm">
                        <div className="text-type-meta text-ink-500">
                          {depStatus.python ? (
                            <span className="font-mono text-[11px]">{depStatus.python}</span>
                          ) : (
                            <span>runtime={depStatus.runtime}</span>
                          )}
                          {installStatusLabel(depStatus.install_status)
                            ? ` · ${installStatusLabel(depStatus.install_status)}`
                            : ''}
                        </div>
                        <ul className="space-y-1 font-mono text-type-mono">
                          {depStatus.dependencies.map((d) => (
                            <li key={d.requirement} className="flex flex-wrap items-center justify-between gap-2">
                              <span>
                                {d.requirement}
                                {d.optional ? (
                                  <span className="ml-1 rounded bg-ink-100 px-1 py-px text-type-meta font-sans text-ink-500">
                                    optional
                                  </span>
                                ) : null}
                              </span>
                              <span className={d.satisfied ? 'text-emerald-700' : 'text-amber-700'}>
                                {d.satisfied ? `ok ${d.installed_version ?? ''}` : 'missing'}
                              </span>
                            </li>
                          ))}
                        </ul>
                        <div className="flex flex-wrap gap-2">
                          {panelMissingReq > 0 && (
                            <button
                              type="button"
                              className="btn-primary"
                              disabled={anyBusy}
                              onClick={() => void installDeps(p.name, false)}
                            >
                              <PackagePlus className="h-3.5 w-3.5" /> Install required deps
                            </button>
                          )}
                          {panelHasOptional && panelMissingReq === 0 && (
                            <button
                              type="button"
                              className="btn-secondary"
                              disabled={anyBusy}
                              onClick={() => void installDeps(p.name, true)}
                            >
                              <PackagePlus className="h-3.5 w-3.5" />
                              {isolated ? 'Install optional (venv)' : 'Install optional (shared)'}
                            </button>
                          )}
                        </div>
                        {isolated && (
                          <p className="text-type-meta text-ink-500">
                            Optional packages listed above install into this plugin’s isolated venv — not into the API
                            image.
                          </p>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}
