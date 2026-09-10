import React from 'react'
import { Download, RefreshCw, PackagePlus, MoreHorizontal } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from '../../components/ui'
import { isIsolatedRuntime } from '../../lib/format'

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
  node_types?: string[]
  error?: string | null
  runtime?: string
  dependency_summary?: DepSummary | null
  manifest?: {
    dependencies?: string[]
    optional_dependencies?: string[]
    runtime?: string
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

const DEPS_INSTALL_TIMEOUT_MS = 900_000

const DOCS_GETTING_STARTED_MODE_B =
  'https://github.com/ursamir/Graphyn/blob/main/docs/GETTING_STARTED.md#mode-b--multi-machine-control-plane--workers'

function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

export default function PluginsView() {
  const refreshCatalog = useAppStore((s) => s.refreshCatalog)
  const pushToast = useAppStore((s) => s.pushToast)
  const [plugins, setPlugins] = React.useState<Plugin[] | null>(null)
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
  const [installStartedAt, setInstallStartedAt] = React.useState<number | null>(null)
  const [installError, setInstallError] = React.useState<string | null>(null)
  const [elapsedTick, setElapsedTick] = React.useState(0)
  const pollRef = React.useRef<number | null>(null)
  const depPollRef = React.useRef<number | null>(null)
  const sourceRef = React.useRef<HTMLInputElement | null>(null)

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
      pushToast('Builder catalog refreshed', 'success')
    }
  }

  const pollInstall = (name: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(() => {
      void apiJson<Plugin>(`/plugins/${encodeURIComponent(name)}`)
        .then(async (rec) => {
          if (rec.status === 'installed' || rec.status === 'failed' || rec.enabled != null) {
            if (pollRef.current) window.clearInterval(pollRef.current)
            pushToast(
              rec.status === 'failed'
                ? `Install failed: ${rec.error ?? name}`
                : `Installed ${name}`,
              rec.status === 'failed' ? 'error' : 'success',
            )
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
      if (failed) {
        setInstallError(failed)
        pushToast(failed, 'error')
      } else {
        setInstallError(null)
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
      } else {
        pushToast(`Installed ${name}`, 'success')
        await afterMutation({ announceCatalog: true })
      }
      setSource('')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
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
    setInstallError(null)
    setInstallingName(name)
    setInstallingOptional(includeOptional)
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
        pushToast(
          includeOptional
            ? `Installing optional extras for ${name}… this can take several minutes`
            : `Installing required deps for ${name}…`,
          'info',
        )
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
      // Sync / already-complete response (has dependency rows)
      if (Array.isArray(res.dependencies)) {
        setDepStatus(res)
      }
      await finishDepsInstall(name, includeOptional)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      clearDepPoll()
      setInstallingName(null)
      setInstallStartedAt(null)
      setInstallError(msg)
      pushToast(msg, 'error')
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

  return (
    <div className="h-full overflow-y-auto p-8 space-y-6">
      <PageHeader
        title="Plugins"
        description="Install node packs, manage dependencies, and enable isolated runtimes."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />
      <p className="rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
        Mode B: workers need the same plugins they claim, plus shared storage for datasets —{' '}
        <a
          href={DOCS_GETTING_STARTED_MODE_B}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-accent-700 hover:underline"
        >
          Getting Started · Mode B
        </a>
        .
      </p>
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <section className="surface-card space-y-3 p-5">
        <h3 className="text-sm font-semibold">Install</h3>
        <input
          ref={sourceRef}
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="path, package, https://…, git+…"
          className="field-control mt-0 text-sm"
        />
        <button type="button" className="btn-primary" disabled={!source.trim()} onClick={() => void install()}>
          <Download className="h-3.5 w-3.5" /> Install
        </button>
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
      </section>

      <section className="surface-card space-y-3 p-5">
        <h3 className="text-sm font-semibold">Search index</h3>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            placeholder="package name"
          />
          <button type="button" className="btn-secondary" onClick={() => void searchIndex()}>
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

      <section className="surface-card p-5">
        <h3 className="mb-2 text-sm font-semibold">Installed ({plugins?.length ?? '…'})</h3>
        {plugins === null ? (
          <LoadingBlock />
        ) : plugins.length === 0 ? (
          <EmptyState
            title="No plugins installed"
            description="Install a package, path, or git URL above to add nodes to the Builder catalog."
            action={
              <button type="button" className="btn-primary" onClick={() => sourceRef.current?.focus()}>
                Install a plugin
              </button>
            }
          />
        ) : (
          <ul className="space-y-2">
            {plugins.map((p) => {
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
              return (
                <li key={p.name} className="rounded-2xl border border-ink-200/70 bg-white px-3.5 py-3 shadow-sm">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-type-body">
                        {p.name} {p.version ? `v${p.version}` : ''}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-type-meta text-ink-500">
                        <StatusBadge status={p.enabled === false ? 'disabled' : p.status ?? 'enabled'} />
                        <span className="rounded bg-ink-50 px-1.5 py-0.5 font-mono text-type-mono">{runtime}</span>
                        {p.node_types?.length ? `${p.node_types.length} nodes` : null}
                        {missingReq > 0 ? (
                          <span className="text-amber-700">{missingReq} missing required</span>
                        ) : (
                          <span className="text-emerald-700">required deps ok</span>
                        )}
                        {showMissingOptCount > 0 ? (
                          <span className="text-amber-700">{showMissingOptCount} missing optional</span>
                        ) : optionalDeclared ? (
                          <span className="text-ink-500">optional extras available</span>
                        ) : null}
                      </div>
                      {/* Collapsed: at most one install CTA OR Manage dependencies */}
                      {!isExpanded && (
                        <div className="mt-2 flex flex-wrap gap-2">
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
                            <button
                              type="button"
                              className="btn-secondary"
                              disabled={anyBusy}
                              onClick={() => void installDeps(p.name, true)}
                              title={
                                isolated
                                  ? 'Install optional extras into this plugin’s isolated venv'
                                  : 'Install optional extras'
                              }
                            >
                              <PackagePlus className="h-3.5 w-3.5" /> Install optional extras
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
                          {(missingReq > 0 || showMissingOptCount > 0) && (
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
                        onClick={() => setMenuFor((m) => (m === p.name ? null : p.name))}
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </button>
                      {menuFor === p.name && (
                        <div className="absolute right-0 z-20 mt-1 w-52 rounded-2xl border border-ink-200 bg-white p-1.5 shadow-soft">
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
                  {isolated && !isExpanded && (
                    <p className="mt-2 text-type-meta text-ink-500">
                      Optional extras (TensorFlow, …) install into this plugin’s isolated venv — they are not added to
                      the API image.
                    </p>
                  )}
                  {busy && (
                    <div className="mt-3 flex items-start gap-2 rounded-xl border border-accent-200 bg-accent-50/60 px-3 py-2 text-sm text-ink-700">
                      <span className="mt-0.5 inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent-500 border-t-transparent" />
                      <div>
                        <div className="font-medium">
                          Installing{installingOptional ? ' optional extras' : ' required deps'}… this can take several
                          minutes for PyTorch
                        </div>
                        <div className="text-type-meta text-ink-500">Elapsed {formatElapsed(liveElapsed)}</div>
                      </div>
                    </div>
                  )}
                  {installError && installingName == null && (
                    <div className="mt-3">
                      <ErrorBanner message={installError} onDismiss={() => setInstallError(null)} />
                    </div>
                  )}
                  {isExpanded && depStatus && (
                    <div className="mt-3 space-y-2 border-t border-ink-100 pt-3 text-sm">
                      <div className="text-type-meta text-ink-500">
                        runtime={depStatus.runtime}
                        {depStatus.python ? ` · ${depStatus.python}` : ''}
                        {depStatus.install_status ? ` · install=${depStatus.install_status}` : ''}
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
                      {/* Expanded: install CTAs only inside the panel */}
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
                        {panelHasOptional && (
                          <button
                            type="button"
                            className="btn-secondary"
                            disabled={anyBusy}
                            onClick={() => void installDeps(p.name, true)}
                          >
                            <PackagePlus className="h-3.5 w-3.5" /> Install optional extras
                          </button>
                        )}
                      </div>
                      {isolated && (
                        <p className="text-type-meta text-ink-500">
                          Optional extras (TensorFlow, …) install into this plugin’s isolated venv — they are not added
                          to the API image.
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
    </div>
  )
}
