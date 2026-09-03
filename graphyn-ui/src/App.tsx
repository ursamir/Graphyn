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
  Menu,
  PanelLeftClose,
  Eye,
  EyeOff,
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

const NAV_GROUPS: Array<{
  title: string
  items: Array<{ id: AppView; label: string; icon: React.ComponentType<{ className?: string }> }>
}> = [
  {
    title: 'Build',
    items: [
      { id: 'builder', label: 'Builder', icon: Workflow },
      { id: 'templates', label: 'Templates', icon: BookOpen },
      { id: 'runs', label: 'Runs', icon: History },
    ],
  },
  {
    title: 'Library',
    items: [
      { id: 'plugins', label: 'Plugins', icon: Package },
      { id: 'data', label: 'Data', icon: Database },
      { id: 'artifacts', label: 'Artifacts', icon: Archive },
    ],
  },
  {
    title: 'Admin',
    items: [
      { id: 'projects', label: 'Projects', icon: FolderKanban },
      { id: 'secrets', label: 'Secrets', icon: KeyRound },
      { id: 'system', label: 'System', icon: Activity },
    ],
  },
]

const VIEW_IDS = new Set(NAV_GROUPS.flatMap((g) => g.items.map((n) => n.id)))

const VIEW_LABEL: Record<AppView, string> = {
  builder: 'Builder',
  templates: 'Templates',
  runs: 'Runs',
  plugins: 'Plugins',
  data: 'Data',
  artifacts: 'Artifacts',
  projects: 'Projects',
  secrets: 'Secrets',
  system: 'System',
}

const JUMP_KEYS: Record<string, AppView> = {
  b: 'builder',
  t: 'templates',
  r: 'runs',
}

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
  const isRunning = useAppStore((s) => s.isRunning)
  const toasts = useAppStore((s) => s.toasts)
  const dismissToast = useAppStore((s) => s.dismissToast)
  const pushToast = useAppStore((s) => s.pushToast)
  const bootError = useAppStore((s) => s.bootError)
  const bootStatus = useAppStore((s) => s.bootStatus)
  const setBootError = useAppStore((s) => s.setBootError)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const [tokenDraft, setTokenDraft] = React.useState('')
  const [tokenVisible, setTokenVisible] = React.useState(false)
  const [navOpen, setNavOpen] = React.useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true,
  )
  const [narrow, setNarrow] = React.useState(() =>
    typeof window !== 'undefined' ? !window.matchMedia('(min-width: 768px)').matches : false,
  )

  React.useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const apply = () => {
      setNarrow(!mq.matches)
      setNavOpen(mq.matches)
    }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

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
    if (settingsOpen) {
      setTokenDraft(getApiToken())
      setTokenVisible(false)
    }
  }, [settingsOpen])

  React.useEffect(() => {
    if (!settingsOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSettingsOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [settingsOpen, setSettingsOpen])

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

  const go = (id: AppView) => {
    setView(id)
    window.history.replaceState(null, '', `#/${id}`)
    if (narrow) setNavOpen(false)
  }

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing =
        !!el &&
        (el.tagName === 'INPUT' ||
          el.tagName === 'TEXTAREA' ||
          el.tagName === 'SELECT' ||
          el.isContentEditable)
      if (settingsOpen) return
      const metaK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'
      const slash = e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey
      if (metaK || (slash && !typing)) {
        if (view === 'builder') {
          e.preventDefault()
          document.getElementById('builder-catalog-search')?.focus()
        }
        return
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return
      const dest = JUMP_KEYS[e.key.toLowerCase()]
      if (dest) {
        e.preventDefault()
        go(dest)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [view, settingsOpen, narrow])

  const chipLabel = isRunning
    ? statusMessage && statusMessage !== 'Running…'
      ? statusMessage
      : 'Running'
    : statusMessage

  return (
    <ErrorBoundary>
      <div className="flex h-full flex-col bg-mesh">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-ink-200/70 bg-white/80 px-4 backdrop-blur-md">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="btn-quiet md:hidden"
              onClick={() => setNavOpen((o) => !o)}
              aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
            >
              <Menu className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="btn-quiet hidden md:inline-flex"
              onClick={() => setNavOpen((o) => !o)}
              aria-label={navOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            >
              <PanelLeftClose className={clsx('h-4 w-4', !navOpen && 'rotate-180')} />
            </button>
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent-500 text-ink-950 shadow-sm">
              <Boxes className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 leading-tight">
              <div className="font-display text-[17px] font-extrabold tracking-tight text-ink-950">Graphyn</div>
              <div className="truncate text-[11px] text-ink-500">{VIEW_LABEL[view]}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={
                bootStatus === 401
                  ? 'hidden rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-medium text-amber-900 sm:inline'
                  : bootError
                    ? 'hidden rounded-full bg-rose-100 px-2.5 py-0.5 text-[11px] font-medium text-rose-800 sm:inline'
                    : 'hidden rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-800 sm:inline'
              }
            >
              <span className={bootError || bootStatus === 401 ? '' : 'inline-block h-1.5 w-1.5 rounded-full bg-emerald-500'} />
              {bootStatus === 401 ? 'Sign in required' : bootError ? "Can't reach the API" : 'Connected'}
            </span>
            {isRunning && (
              <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold text-amber-900">
                {chipLabel}
              </span>
            )}
            {!isRunning && chipLabel && (
              <span className="hidden max-w-[14rem] truncate rounded-full bg-ink-100 px-2.5 py-0.5 text-[11px] text-ink-600 sm:inline">
                {chipLabel}
              </span>
            )}
            {lastRunId && (
              <button
                type="button"
                className="rounded-full border border-ink-200 bg-white px-2.5 py-0.5 font-mono text-[11px] text-ink-700 hover:border-accent-400 hover:text-accent-800"
                onClick={() => openRun(lastRunId)}
                title={lastRunId}
              >
                Last run {lastRunId.slice(0, 8)}
              </button>
            )}
            <button
              type="button"
              className="btn-icon"
              onClick={openSettings}
              aria-label="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>
          </div>
        </header>

        {bootError && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-950">
            <span title={bootError}>
              {bootStatus === 401 ? 'Sign in with your API token' : "Can't reach the API"}
            </span>
            <button type="button" className="btn-secondary" onClick={openSettings}>
              Open Settings
            </button>
          </div>
        )}

        <div className="relative flex min-h-0 flex-1">
          {navOpen && narrow && (
            <button
              type="button"
              className="absolute inset-0 z-20 bg-ink-950/30 md:hidden"
              aria-label="Close navigation"
              onClick={() => setNavOpen(false)}
            />
          )}
          {navOpen && (
            <aside
              className={clsx(
                'z-30 flex w-56 shrink-0 flex-col border-r border-ink-200/70 bg-white/80 backdrop-blur-md',
                narrow && 'absolute inset-y-0 left-0 shadow-xl md:static md:shadow-none',
              )}
            >
              <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Primary">
                {NAV_GROUPS.map((group) => (
                  <div key={group.title} className="mb-4">
                    <div className="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400">
                      {group.title}
                    </div>
                    <div className="space-y-0.5">
                      {group.items.map(({ id, label, icon: Icon }) => {
                        const active = view === id
                        return (
                          <button
                            key={id}
                            type="button"
                            onClick={() => go(id)}
                            className={clsx(
                              'relative flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm transition',
                              active
                                ? 'bg-accent-50 font-semibold text-accent-900 shadow-sm'
                                : 'text-ink-600 hover:bg-ink-50 hover:text-ink-950',
                            )}
                            aria-current={active ? 'page' : undefined}
                          >
                            <Icon className={clsx('h-3.5 w-3.5', active ? 'text-accent-700' : 'text-ink-400')} />
                            {label}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </nav>
            </aside>
          )}

          <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
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
        </div>

        <ToastHost toasts={toasts} onDismiss={dismissToast} />

        {settingsOpen && (
          <div
            className="fixed inset-0 z-[110] flex items-center justify-center bg-ink-950/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            onClick={() => setSettingsOpen(false)}
          >
            <div
              className="w-full max-w-md rounded-2xl border border-ink-200 bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
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
                <div className="mt-1 flex items-center gap-2">
                  <input
                    type={tokenVisible ? 'text' : 'password'}
                    value={tokenDraft}
                    onChange={(e) => setTokenDraft(e.target.value)}
                    className="w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm"
                    placeholder="GRAPHYN_API_TOKEN"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    className="btn-secondary shrink-0"
                    onClick={() => setTokenVisible((v) => !v)}
                    aria-label={tokenVisible ? 'Hide token' : 'Show token'}
                  >
                    {tokenVisible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </label>
              <p className="mt-2 text-xs text-ink-500">
                Paste the same token as GRAPHYN_API_TOKEN on the server. Stored only in this browser.
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
