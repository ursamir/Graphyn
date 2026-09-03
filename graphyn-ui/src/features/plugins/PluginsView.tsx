import React from 'react'
import { Download, RefreshCw, PackagePlus } from 'lucide-react'
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
  const [depStatus, setDepStatus] = React.useState<DepStatus | null>(null)
  const pollRef = React.useRef<number | null>(null)
  const sourceRef = React.useRef<HTMLInputElement | null>(null)

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
    }
  }, [load])

  const afterMutation = async () => {
    await load()
    await refreshCatalog?.()
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
            await afterMutation()
          }
        })
        .catch(() => undefined)
    }, 1500)
  }

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
        await afterMutation()
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
    try {
      const status = await apiJson<DepStatus>(`/plugins/${encodeURIComponent(name)}/dependencies/install`, {
        method: 'POST',
        body: JSON.stringify({ include_optional: includeOptional }),
      })
      setDepStatus(status)
      pushToast(
        includeOptional ? `Installed extras for ${name}` : `Installed required deps for ${name}`,
        'success',
      )
      await afterMutation()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
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

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Plugins"
        description="Install node packs, manage dependencies, and enable isolated runtimes."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
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

      <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3">
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

      <section className="rounded-2xl border border-ink-200 bg-white p-4">
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
              const runtime = p.runtime ?? p.dependency_summary?.runtime ?? p.manifest?.runtime ?? 'inprocess'
              const isolated = isIsolatedRuntime(runtime, p.name)
              return (
                <li key={p.name} className="rounded-2xl border border-ink-200/70 bg-white px-3.5 py-3 shadow-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="font-medium">
                        {p.name} {p.version ? `v${p.version}` : ''}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                        <StatusBadge status={p.enabled === false ? 'disabled' : p.status ?? 'enabled'} />
                        <span className="rounded bg-ink-50 px-1.5 py-0.5 font-mono">{runtime}</span>
                        {p.node_types?.length ? `${p.node_types.length} nodes` : null}
                        {missingReq > 0 ? (
                          <span className="text-amber-700">{missingReq} missing required dep(s)</span>
                        ) : (
                          <span className="text-emerald-700">deps ok</span>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <button type="button" className="btn-secondary" onClick={() => void toggleDeps(p.name)}>
                        Deps
                      </button>
                      {isolated && (
                        <button type="button" className="btn-secondary" onClick={() => void installDeps(p.name, true)}>
                          Install extras (TensorFlow, …)
                        </button>
                      )}
                      {p.enabled === false ? (
                        <button type="button" className="btn-secondary" onClick={() => void setEnabled(p.name, true)}>
                          Enable
                        </button>
                      ) : (
                        <button type="button" className="btn-quiet" onClick={() => void setEnabled(p.name, false)}>
                          Disable
                        </button>
                      )}
                      <ConfirmButton
                        label="Uninstall"
                        confirmLabel="Confirm uninstall"
                        danger
                        onConfirm={() =>
                          void apiJson(`/plugins/${encodeURIComponent(p.name)}`, { method: 'DELETE' })
                            .then(afterMutation)
                            .then(() => pushToast(`Uninstalled ${p.name}`, 'success'))
                            .catch((err) => pushToast(err instanceof Error ? err.message : String(err), 'error'))
                        }
                      />
                    </div>
                  </div>
                  {isolated && (
                    <p className="mt-2 text-[11px] text-ink-500">
                      Optional extras (TensorFlow, …) install into this plugin’s isolated venv — they are not added to
                      the API image.
                    </p>
                  )}
                  {expanded === p.name && depStatus && (
                    <div className="mt-3 space-y-2 border-t border-ink-100 pt-3 text-sm">
                      <div className="text-[11px] text-ink-500">
                        runtime={depStatus.runtime}
                        {depStatus.python ? ` · ${depStatus.python}` : ''}
                      </div>
                      <ul className="space-y-1 font-mono text-[11px]">
                        {depStatus.dependencies.map((d) => (
                          <li key={d.requirement} className="flex justify-between gap-2">
                            <span>
                              {d.requirement}
                              {d.optional ? ' (optional)' : ''}
                            </span>
                            <span className={d.satisfied ? 'text-emerald-700' : 'text-amber-700'}>
                              {d.satisfied ? `ok ${d.installed_version ?? ''}` : 'missing'}
                            </span>
                          </li>
                        ))}
                      </ul>
                      <div className="flex flex-wrap gap-2">
                        <button type="button" className="btn-primary" onClick={() => void installDeps(p.name, false)}>
                          <PackagePlus className="h-3.5 w-3.5" /> Install required
                        </button>
                      </div>
                      {isolated && (
                        <p className="text-[11px] text-ink-500">
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
