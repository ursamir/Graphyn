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
  Server,
  GitBranch,
  Cpu,
  FlaskConical,
  GitPullRequest,
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
import { shortRunId } from './lib/format'
import { KeyboardHelp } from './components/KeyboardHelp'
import BuilderView from './features/builder/BuilderView'
import RunsView from './features/runs/RunsView'
import ArtifactsView from './features/artifacts/ArtifactsView'
import PluginsView from './features/plugins/PluginsView'
import TemplatesView from './features/templates/TemplatesView'
import DataView from './features/data/DataView'
import ProjectsView from './features/projects/ProjectsView'
import SystemView from './features/system/SystemView'
import SecretsView from './features/secrets/SecretsView'
import WorkersView from './features/workers/WorkersView'
import TraceView from './features/trace/TraceView'
import EdgeWizardView from './features/edge/EdgeWizardView'
import ExperimentsView from './features/experiments/ExperimentsView'
import ProposalsView from './features/proposals/ProposalsView'

type NavItem = { id: AppView; label: string; icon: React.ComponentType<{ className?: string }> }
type NavGroup = { title: string; items: NavItem[] }

/** Global shell when no project is open (project-first IA Phase 1). */
const GLOBAL_NAV_GROUPS: NavGroup[] = [
  {
    title: 'Projects',
    items: [{ id: 'projects', label: 'Projects', icon: FolderKanban }],
  },
  {
    title: 'Build',
    items: [
      { id: 'templates', label: 'Templates', icon: BookOpen },
      { id: 'proposals', label: 'Proposals', icon: GitPullRequest },
      { id: 'builder', label: 'Builder', icon: Workflow },
    ],
  },
  {
    title: 'Library',
    items: [{ id: 'data', label: 'Data library', icon: Database }],
  },
  {
    title: 'Deploy',
    items: [
      { id: 'edge', label: 'Edge deploy', icon: Cpu },
      { id: 'workers', label: 'Workers', icon: Server },
    ],
  },
  {
    title: 'Admin',
    items: [
      { id: 'plugins', label: 'Plugins', icon: Package },
      { id: 'secrets', label: 'Secrets', icon: KeyRound },
      { id: 'system', label: 'System', icon: Activity },
    ],
  },
]

/** Project-local strip when activeProject is set. Trace/Artifacts demoted to detail + last-run. */
const PROJECT_NAV_ITEMS: NavItem[] = [
  { id: 'projects', label: 'Overview', icon: FolderKanban },
  { id: 'builder', label: 'Editor', icon: Workflow },
  { id: 'runs', label: 'Run', icon: History },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
]

const ALL_NAV_ITEMS: NavItem[] = [
  ...GLOBAL_NAV_GROUPS.flatMap((g) => g.items),
  ...PROJECT_NAV_ITEMS,
  { id: 'trace', label: 'Trace', icon: GitBranch },
  { id: 'artifacts', label: 'Artifacts', icon: Archive },
]

const VIEW_IDS = new Set(ALL_NAV_ITEMS.map((n) => n.id))

const VIEW_LABEL: Record<AppView, string> = {
  builder: 'Editor',
  templates: 'Templates',
  runs: 'Run',
  plugins: 'Plugins',
  data: 'Explorer',
  artifacts: 'Artifacts',
  trace: 'Trace',
  edge: 'Edge deploy',
  experiments: 'Experiments',
  proposals: 'Proposals',
  projects: 'Workspace',
  secrets: 'Secrets',
  system: 'System',
  workers: 'Workers',
}


const NAV_HINTS: Partial<Record<AppView, string>> = {
  builder: 'Editor — design Graph IR pipelines on the canvas',
  templates: 'New from template — opens or creates a workspace first',
  proposals: 'PR-like review of agent-proposed graphs',
  runs: 'Run panel — execution history and ops for this workspace',
  trace: 'Lineage panel — provenance across artifact, run, graph, worker',
  experiments: 'Compare panel — params and metrics across runs',
  artifacts: 'Output panel — pipeline files across runs',
  plugins: 'Extensions — install node packs for the Editor catalog',
  data: 'Global library / Explorer — browse files; link into a project from Workspace home',
  edge: 'Deploy target — package models for on-device runtimes',
  workers: 'Deploy targets — distributed workers, GPU, heartbeats',
  projects: 'Workspace home — linked data, pipelines, runs, experiments',
  secrets: 'Settings — named credentials for runs',
  system: 'Settings — health, cleanup, webhooks, audit trail',
}

const JUMP_KEYS: Record<string, AppView> = {
  b: 'builder',
  t: 'templates',
  p: 'proposals',
  r: 'runs',
  o: 'trace',
  e: 'experiments',
  a: 'artifacts',
  d: 'data',
  j: 'projects',
  g: 'edge',
  w: 'workers',
  l: 'plugins',
  k: 'secrets',
  s: 'system',
}

function parseHash(): { view?: AppView; runId?: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  if (!raw) return {}
  const pathOnly = raw.split('?')[0]
  const [viewPart, runPart] = pathOnly.split('/')
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
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openExperiments = useAppStore((s) => s.openExperiments)
  const openProjects = useAppStore((s) => s.openProjects)
  const activeProject = useAppStore((s) => s.activeProject)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const openProject = useAppStore((s) => s.openProject)
  const statusMessage = useAppStore((s) => s.statusMessage)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const isRunning = useAppStore((s) => s.isRunning)
  const toasts = useAppStore((s) => s.toasts)
  const dismissToast = useAppStore((s) => s.dismissToast)
  const pushToast = useAppStore((s) => s.pushToast)
  const bootError = useAppStore((s) => s.bootError)
  const bootStatus = useAppStore((s) => s.bootStatus)
  const pendingProposalCount = useAppStore((s) => s.pendingProposalCount)
  const setPendingProposalCount = useAppStore((s) => s.setPendingProposalCount)
  const setBootError = useAppStore((s) => s.setBootError)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const [helpOpen, setHelpOpen] = React.useState(false)
  const [tokenDraft, setTokenDraft] = React.useState('')
  const [tokenVisible, setTokenVisible] = React.useState(false)
  const settingsPanelRef = React.useRef<HTMLDivElement>(null)
  const settingsTriggerRef = React.useRef<HTMLElement | null>(null)
  const tokenInputRef = React.useRef<HTMLInputElement>(null)
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
    let cancelled = false
    const loadPending = async () => {
      try {
        const data = await apiJson<{ proposals: unknown[] }>('/proposals?status=pending')
        if (!cancelled) {
          setPendingProposalCount(Array.isArray(data?.proposals) ? data.proposals.length : 0)
        }
      } catch {
        /* quiet — badge is optional */
      }
    }
    void loadPending()
    const t = window.setInterval(() => void loadPending(), 60000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [setPendingProposalCount, bootStatus])

  React.useEffect(() => {
    const apply = () => {
      const { view: v, runId } = parseHash()
      if (runId) openRun(runId)
      else if (v) setView(v)
      // Sync active project from #/projects?project= without breaking other deep links.
      const raw = window.location.hash.replace(/^#\/?/, '')
      const qIdx = raw.indexOf('?')
      if (qIdx >= 0) {
        const params = new URLSearchParams(raw.slice(qIdx + 1))
        const proj = (params.get('project') || '').trim()
        if (proj && (v === 'projects' || raw.startsWith('projects'))) {
          const cur = useAppStore.getState().activeProject
          if (cur !== proj) setActiveProject(proj)
        }
      }
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [openRun, setView, setActiveProject])

  React.useEffect(() => {
    // Preserve query strings for deep links (#/trace?run_id=, #/edge?…, etc.)
    const PRESERVE_QUERY = new Set<AppView>(['trace', 'edge', 'experiments', 'proposals', 'artifacts', 'data', 'projects'])
    const focus = useAppStore.getState().focusRunId
    const raw = window.location.hash.replace(/^#\/?/, '')
    const pathOnly = raw.split('?')[0] || ''
    if (PRESERVE_QUERY.has(view)) {
      if (pathOnly !== view && !pathOnly.startsWith(`${view}/`)) {
        window.history.replaceState(null, '', `#/${view}`)
      }
      return
    }
    const next = view === 'runs' && focus ? `#/runs/${focus}` : `#/${view}`
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [view])

  React.useEffect(() => {
    if (settingsOpen) {
      setTokenDraft(getApiToken())
      setTokenVisible(false)
      settingsTriggerRef.current = document.activeElement as HTMLElement | null
      requestAnimationFrame(() => tokenInputRef.current?.focus())
    } else if (settingsTriggerRef.current) {
      settingsTriggerRef.current.focus?.()
      settingsTriggerRef.current = null
    }
  }, [settingsOpen])

  React.useEffect(() => {
    if (!settingsOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSettingsOpen(false)
        return
      }
      if (e.key !== 'Tab') return
      const root = settingsPanelRef.current
      if (!root) return
      const focusables = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
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
    const PRESERVE_QUERY = new Set<AppView>([
      'trace',
      'edge',
      'experiments',
      'proposals',
      'artifacts',
      'data',
      'projects',
    ])
    const raw = window.location.hash.replace(/^#\/?/, '')
    const qIdx = raw.indexOf('?')
    const query = qIdx >= 0 ? raw.slice(qIdx) : ''
    if (PRESERVE_QUERY.has(id) && PRESERVE_QUERY.has(view) && query) {
      window.history.replaceState(null, '', `#/${id}${query}`)
    } else if (id === 'projects') {
      const ap = useAppStore.getState().activeProject
      if (ap) {
        window.history.replaceState(null, '', `#/projects?project=${encodeURIComponent(ap)}`)
      } else {
        window.history.replaceState(null, '', `#/projects`)
      }
    } else {
      window.history.replaceState(null, '', `#/${id}`)
    }
    if (narrow) setNavOpen(false)
  }

  const goLinkedData = () => {
    const ap = useAppStore.getState().activeProject
    if (ap) {
      openProjects({ project: ap, tab: 'versions' })
    } else {
      go('projects')
    }
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
      if (helpOpen) {
        if (e.key === 'Escape') {
          e.preventDefault()
          setHelpOpen(false)
        }
        return
      }
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
      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault()
        setHelpOpen(true)
        return
      }
      const dest = JUMP_KEYS[e.key.toLowerCase()]
      if (dest) {
        e.preventDefault()
        go(dest)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [view, settingsOpen, helpOpen, narrow])

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
              <div className="text-[15px] font-semibold text-ink-950">Graphyn</div>
              <div className="truncate text-[11px] text-ink-500">{VIEW_LABEL[view]}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {bootStatus === 401 ? (
              <span className="hidden text-[12px] font-medium text-amber-800 sm:inline">Sign in required</span>
            ) : bootError ? (
              <span className="hidden text-[12px] font-medium text-rose-700 sm:inline">Can't reach the API</span>
            ) : (
              <span className="hidden text-[12px] text-ink-400 sm:inline">Connected</span>
            )}
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
            {activeProject && (
              <div className="hidden max-w-[16rem] items-center gap-0.5 sm:inline-flex">
                <button
                  type="button"
                  className="inline-flex max-w-[14rem] items-center gap-1 truncate rounded-l-full border border-accent-300 bg-accent-50 px-2.5 py-0.5 text-[11px] font-medium text-accent-900 hover:border-accent-400"
                  title="Open workspace home"
                  onClick={() => openProject(activeProject)}
                >
                  <FolderKanban className="h-3 w-3 shrink-0" />
                  <span className="truncate">Project · {activeProject}</span>
                </button>
                <button
                  type="button"
                  className="rounded-r-full border border-l-0 border-accent-300 bg-accent-50 px-1.5 py-0.5 text-[11px] font-medium text-accent-800 hover:bg-accent-100"
                  title="Switch or clear workspace"
                  onClick={() => go('projects')}
                >
                  Switch
                </button>
                <button
                  type="button"
                  className="ml-0.5 rounded-full border border-ink-200 bg-white px-1.5 py-0.5 text-[11px] text-ink-500 hover:border-ink-300 hover:text-ink-800"
                  title="Close workspace"
                  aria-label="Close workspace"
                  onClick={() => setActiveProject(null)}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )}
            {!activeProject && (
              <button
                type="button"
                className="hidden items-center rounded-full border border-dashed border-ink-300 bg-white/80 px-2.5 py-0.5 text-[11px] text-ink-500 hover:border-accent-300 hover:text-accent-800 sm:inline-flex"
                onClick={() => go('projects')}
              >
                Open workspace
              </button>
            )}
            {lastRunId && (
              <div className="hidden items-center gap-1 sm:flex" title={`Observe loop for ${lastRunId}`}>
                <button
                  type="button"
                  className="rounded-full border border-ink-200 bg-white px-2.5 py-0.5 font-mono text-[11px] text-ink-700 hover:border-accent-400 hover:text-accent-800"
                  onClick={() => openRun(lastRunId)}
                  title={lastRunId}
                >
                  Run {shortRunId(lastRunId)}
                </button>
                <button
                  type="button"
                  className="rounded-full border border-ink-100 bg-white/80 px-2 py-0.5 text-[11px] text-ink-600 hover:border-accent-300 hover:text-accent-800"
                  onClick={() => openTrace({ runId: lastRunId })}
                >
                  Lineage
                </button>
                <button
                  type="button"
                  className="rounded-full border border-ink-100 bg-white/80 px-2 py-0.5 text-[11px] text-ink-600 hover:border-accent-300 hover:text-accent-800"
                  onClick={() => openArtifacts({ runId: lastRunId })}
                >
                  Artifacts
                </button>
                {!activeProject && (
                  <>
                    <button
                      type="button"
                      className="rounded-full border border-ink-100 bg-white/80 px-2 py-0.5 text-[11px] text-ink-600 hover:border-accent-300 hover:text-accent-800"
                      title="Opens Experiments with this run preselected — pick a second run to Compare"
                      onClick={() => openExperiments({ runIds: [lastRunId] })}
                    >
                      Compare…
                    </button>
                    <button
                      type="button"
                      className="rounded-full border border-ink-100 bg-white/80 px-2 py-0.5 text-[11px] text-ink-600 hover:border-accent-300 hover:text-accent-800"
                      onClick={() => openProjects()}
                    >
                      Projects
                    </button>
                  </>
                )}
              </div>
            )}
            <button
              type="button"
              className="btn-icon"
              onClick={() => setHelpOpen(true)}
              aria-label="Keyboard shortcuts"
              title="Keyboard shortcuts (?)"
            >
              <span className="text-[13px] font-semibold">?</span>
            </button>
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
          <div role="status" className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-950">
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
                'z-30 flex w-[13.5rem] shrink-0 flex-col border-r border-ink-200/80 bg-[#f7f7f8]',
                narrow && 'absolute inset-y-0 left-0 shadow-xl md:static md:shadow-none',
              )}
            >
              <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Primary">
                {activeProject && (
                  <div className="mb-3 rounded-xl border border-accent-200/80 bg-accent-50/60 p-1.5 shadow-sm">
                    <div className="flex items-center justify-between px-2 pb-1 pt-0.5">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-accent-800">
                        In project
                      </div>
                      <button
                        type="button"
                        className="text-[10px] font-medium text-accent-700/80 hover:text-accent-950"
                        title="Close workspace"
                        onClick={() => setActiveProject(null)}
                      >
                        Close
                      </button>
                    </div>
                    <div className="mb-1 truncate px-2 text-[12px] font-semibold text-accent-950" title={activeProject}>
                      {activeProject}
                    </div>
                    <div className="space-y-0.5">
                      {PROJECT_NAV_ITEMS.map(({ id, label, icon: Icon }) => {
                        const active = view === id
                        return (
                          <button
                            key={`proj-${id}`}
                            type="button"
                            title={NAV_HINTS[id]}
                            onClick={() => (id === 'projects' ? openProject(activeProject) : go(id))}
                            className={clsx(
                              'relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-left text-[13px] transition',
                              active
                                ? 'bg-white font-medium text-ink-950 shadow-sm ring-1 ring-accent-300/70'
                                : 'text-ink-700 hover:bg-white/80 hover:text-ink-950',
                            )}
                            aria-current={active ? 'page' : undefined}
                          >
                            <Icon className={clsx('h-4 w-4', active ? 'text-accent-800' : 'text-ink-400')} />
                            <span className="flex-1 truncate">{label}</span>
                          </button>
                        )
                      })}
                      <button
                        type="button"
                        title="Explorer — linked data, versions, snapshots for this workspace"
                        onClick={goLinkedData}
                        className="relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-left text-[13px] text-ink-700 transition hover:bg-white/80 hover:text-ink-950"
                      >
                        <Database className="h-4 w-4 text-ink-400" />
                        <span className="flex-1 truncate">Explorer</span>
                      </button>
                    </div>
                  </div>
                )}
                {activeProject ? (
                  <div className="mb-4">
                    <div className="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                      Global
                    </div>
                    <div className="space-y-0.5">
                      {(
                        [
                          { id: 'templates' as AppView, label: 'Templates', icon: BookOpen },
                          { id: 'proposals' as AppView, label: 'Proposals', icon: GitPullRequest },
                          { id: 'data' as AppView, label: 'Data library', icon: Database },
                          { id: 'edge' as AppView, label: 'Edge deploy', icon: Cpu },
                          { id: 'workers' as AppView, label: 'Workers', icon: Server },
                          { id: 'plugins' as AppView, label: 'Plugins', icon: Package },
                          { id: 'secrets' as AppView, label: 'Secrets', icon: KeyRound },
                          { id: 'system' as AppView, label: 'System', icon: Activity },
                        ]
                      ).map(({ id, label, icon: Icon }) => {
                        const active = view === id
                        return (
                          <button
                            key={`global-${id}`}
                            type="button"
                            title={(() => {
                              const hint = NAV_HINTS[id]
                              if (!hint) return undefined
                              const jump = Object.entries(JUMP_KEYS).find(([, v]) => v === id)?.[0]
                              return jump ? `${hint} · Press ${jump}` : hint
                            })()}
                            onClick={() => go(id)}
                            className={clsx(
                              'relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-left text-[13px] transition',
                              active
                                ? 'bg-white font-medium text-ink-950 shadow-sm ring-1 ring-ink-200/80'
                                : 'text-ink-600 hover:bg-white/70 hover:text-ink-950',
                            )}
                            aria-current={active ? 'page' : undefined}
                          >
                            <Icon className={clsx('h-4 w-4', active ? 'text-ink-900' : 'text-ink-400')} />
                            <span className="flex-1 truncate">{label}</span>
                            {id === 'proposals' && pendingProposalCount > 0 && (
                              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
                                {pendingProposalCount}
                              </span>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ) : (
                  GLOBAL_NAV_GROUPS.map((group) => (
                    <div key={group.title} className="mb-4">
                      <div className="px-2.5 pb-1.5 text-[11px] font-medium text-ink-400">
                        {group.title}
                      </div>
                      <div className="space-y-0.5">
                        {group.items.map(({ id, label, icon: Icon }) => {
                          const active = view === id
                          return (
                            <button
                              key={id}
                              type="button"
                              title={(() => {
                                const hint = NAV_HINTS[id]
                                if (!hint) return undefined
                                const jump = Object.entries(JUMP_KEYS).find(([, v]) => v === id)?.[0]
                                return jump ? `${hint} · Press ${jump}` : hint
                              })()}
                              onClick={() => go(id)}
                              className={clsx(
                                'relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-left text-[13px] transition',
                                active
                                  ? 'bg-white font-medium text-ink-950 shadow-sm ring-1 ring-ink-200/80'
                                  : 'text-ink-600 hover:bg-white/70 hover:text-ink-950',
                              )}
                              aria-current={active ? 'page' : undefined}
                            >
                              <Icon className={clsx('h-4 w-4', active ? 'text-ink-900' : 'text-ink-400')} />
                              <span className="flex-1 truncate">{label}</span>
                              {id === 'proposals' && pendingProposalCount > 0 && (
                                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
                                  {pendingProposalCount}
                                </span>
                              )}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  ))
                )}
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
            {view === 'workers' && <WorkersView />}
            {view === 'trace' && <TraceView />}
            {view === 'edge' && <EdgeWizardView />}
            {view === 'experiments' && <ExperimentsView />}
            {view === 'proposals' && <ProposalsView />}
            {view === 'secrets' && <SecretsView />}
          </main>
        </div>

        <KeyboardHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
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
              ref={settingsPanelRef}
              className="w-full max-w-md rounded-2xl border border-ink-200 bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 id="settings-title" className="text-lg font-semibold">
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
                    ref={tokenInputRef}
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
