import React from 'react'
import clsx from 'clsx'
import {
  Boxes,
  Workflow,
  History,
  Archive,
  Package,
  BookOpen,
  Database,
  FolderKanban,
  Activity,
  Settings,
  KeyRound,
  X,
} from 'lucide-react'
import { apiJson, ApiError, getApiToken, setApiToken } from './api/client'
import { useAppStore, type AppView } from './store/appStore'
import type { NodeCatalogEntry } from './types/graph'
import { ErrorBoundary, ToastHost } from './components/ui'
import BuilderView from './features/builder/BuilderView'
import RunsView from './features/runs/RunsView'
import ArtifactsView from './features/artifacts/ArtifactsView'
import PluginsView from './features/plugins/PluginsView'
import TemplatesView from './features/templates/TemplatesView'
import DataView from './features/data/DataView'
import ProjectsView from './features/projects/ProjectsView'
import SystemView from './features/system/SystemView'
import SecretsView from './features/secrets/SecretsView'

const NAV: Array<{ id: AppView; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: 'builder', label: 'Builder', icon: Workflow },
  { id: 'runs', label: 'Runs', icon: History },
  { id: 'artifacts', label: 'Artifacts', icon: Archive },
  { id: 'plugins', label: 'Plugins', icon: Package },
  { id: 'templates', label: 'Templates', icon: BookOpen },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'projects', label: 'Projects', icon: FolderKanban },
  { id: 'system', label: 'System', icon: Activity },
  { id: 'secrets', label: 'Secrets', icon: KeyRound },
]

const VIEW_IDS = new Set(NAV.map((n) => n.id))

function parseHash(): { view?: AppView; runId?: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  if (!raw) return {}
  const [viewPart, runPart] = raw.split('/')
  const view = VIEW_IDS.has(viewPart as AppView) ? (viewPart as AppView) : undefined
  if (view === 'runs' && runPart) return { view, runId: runPart }
  return { view }
}

export default function App() {
  const view = useAppStore((s) => s.view)
  const setView = useAppStore((s) => s.setView)
  const setCatalog = useAppStore((s) => s.setCatalog)
  const setRefreshCatalog = useAppStore((s) => s.setRefreshCatalog)
  const openRun = useAppStore((s) => s.openRun)
  const statusMessage = useAppStore((s) => s.statusMessage)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const toasts = useAppStore((s) => s.toasts)
  const dismissToast = useAppStore((s) => s.dismissToast)
  const pushToast = useAppStore((s) => s.pushToast)
  const bootError = useAppStore((s) => s.bootError)
  const setBootError = useAppStore((s) => s.setBootError)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const [tokenDraft, setTokenDraft] = React.useState('')

  const refreshCatalog = React.useCallback(async () => {
    try {
      const nodes = await apiJson<NodeCatalogEntry[]>('/nodes')
      setCatalog(nodes)
      setBootError(null, null)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load node catalog'
      const status = err instanceof ApiError ? err.status : null
      setBootError(message, status)
      if (err instanceof ApiError && err.status === 401) {
        setTokenDraft(getApiToken())
        setSettingsOpen(true)
      }
    }
  }, [setCatalog, setBootError, setSettingsOpen])

  React.useEffect(() => {
    setRefreshCatalog(refreshCatalog)
    void refreshCatalog()
  }, [refreshCatalog, setRefreshCatalog])

  React.useEffect(() => {
    const apply = () => {
      const { view: v, runId } = parseHash()
      if (runId) openRun(runId)
      else if (v) setView(v)
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [openRun, setView])

  React.useEffect(() => {
    const focus = useAppStore.getState().focusRunId
    const next = view === 'runs' && focus ? `#/runs/${focus}` : `#/${view}`
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [view])

  React.useEffect(() => {
    if (settingsOpen) setTokenDraft(getApiToken())
  }, [settingsOpen])

  const openSettings = () => {
    setTokenDraft(getApiToken())
    setSettingsOpen(true)
  }

  const saveSettings = () => {
    setApiToken(tokenDraft)
    setSettingsOpen(false)
    pushToast(tokenDraft.trim() ? 'API token saved' : 'API token cleared', 'success')
    void refreshCatalog()
  }

  return (
    <ErrorBoundary>
      <div className="flex h-full flex-col bg-mesh">
        <header className="relative overflow-hidden border-b border-ink-200/80 bg-ink-950 text-ink-50">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_0%_0%,rgba(30,181,166,0.35),transparent_50%)]" />
          <div className="relative flex flex-wrap items-center justify-between gap-3 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500 text-ink-950 shadow-lg shadow-accent-500/30">
                <Boxes className="h-5 w-5" />
              </div>
              <div>
                <div className="font-display text-2xl font-extrabold tracking-tight">Graphyn</div>
                <div className="text-xs text-ink-300">Typed DAG workflows · Graph IR · Plugins</div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right text-xs text-ink-300">
                {lastRunId && (
                  <button
                    type="button"
                    className="font-mono text-accent-300 hover:underline"
                    onClick={() => openRun(lastRunId)}
                  >
                    last run: {lastRunId}
                  </button>
                )}
                {statusMessage && <div className="text-accent-300">{statusMessage}</div>}
              </div>
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 px-3 py-1.5 text-sm text-ink-100 hover:bg-white/10"
                onClick={openSettings}
                aria-label="Settings"
              >
                <Settings className="h-3.5 w-3.5" />
                Settings
              </button>
            </div>
          </div>
          <nav className="relative flex flex-wrap gap-1 px-4 pb-3" aria-label="Primary">
            {NAV.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setView(id)
                  window.history.replaceState(null, '', `#/${id}`)
                }}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                  view === id
                    ? 'bg-white text-ink-950'
                    : 'text-ink-200 hover:bg-white/10 hover:text-white',
                )}
                aria-current={view === id ? 'page' : undefined}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </nav>
        </header>

        {bootError && (
          <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-800">
            API connection error: {bootError}. Start the Graphyn API on port 8001, or set a token in
            Settings if auth is required.
          </div>
        )}

        <main className="min-h-0 flex-1 overflow-hidden">
          {view === 'builder' && <BuilderView />}
          {view === 'runs' && <RunsView />}
          {view === 'artifacts' && <ArtifactsView />}
          {view === 'plugins' && <PluginsView />}
          {view === 'templates' && <TemplatesView />}
          {view === 'data' && <DataView />}
          {view === 'projects' && <ProjectsView />}
          {view === 'system' && <SystemView />}
          {view === 'secrets' && <SecretsView />}
        </main>

        <ToastHost toasts={toasts} onDismiss={dismissToast} />

        {settingsOpen && (
          <div
            className="fixed inset-0 z-[110] flex items-center justify-center bg-ink-950/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
          >
            <div className="w-full max-w-md rounded-2xl border border-ink-200 bg-white p-5 shadow-xl">
              <div className="mb-4 flex items-center justify-between">
                <h2 id="settings-title" className="font-display text-lg font-bold">
                  Settings
                </h2>
                <button type="button" className="btn-secondary" onClick={() => setSettingsOpen(false)} aria-label="Close">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <label className="block text-sm text-ink-600">
                API Bearer token
                <input
                  type="password"
                  value={tokenDraft}
                  onChange={(e) => setTokenDraft(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
                  placeholder="GRAPHYN_API_TOKEN"
                  autoComplete="off"
                />
              </label>
              <p className="mt-2 text-xs text-ink-500">
                Stored in localStorage as <code>graphyn_api_token</code>. Sent as{' '}
                <code>Authorization: Bearer …</code> on API and file requests.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button type="button" className="btn-secondary" onClick={() => setSettingsOpen(false)}>
                  Cancel
                </button>
                <button type="button" className="btn-primary" onClick={saveSettings}>
                  Save
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  )
}
