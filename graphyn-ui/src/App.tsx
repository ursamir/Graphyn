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
  GitPullRequest,
  Cpu,
  X,
  Menu,
  PanelLeftClose,
  Eye,
  EyeOff,
  Box,
  Shield,
} from 'lucide-react'
import { apiJson, ApiError, getApiToken, setApiToken } from './api/client'
import { useAppStore, type AppView } from './store/appStore'
import type { NodeCatalogEntry } from './types/graph'
import { ErrorBoundary, ToastHost } from './components/ui'
import { SplitPane } from './components/SplitPane'
import { LayoutModeControl, LayoutPrefsProvider, LAYOUT_KEYS } from './layout'
import { shortRunId } from './lib/format'
import { KeyboardHelp } from './components/KeyboardHelp'
import { CommandPalette } from './components/CommandPalette'
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
import EdgeWizardView from './features/edge/EdgeWizardView'
import ExperimentsView from './features/experiments/ExperimentsView'
import ProposalsView from './features/proposals/ProposalsView'
import ModelsView from './features/models/ModelsView'
import AccessView from './features/access/AccessView'
import DevicesView from './features/ship/DevicesView'
import LoginView from './features/auth/LoginView'
import { HashRedirect } from './routes/HashRedirect'
import { resolveLegacyHash } from './routes/legacyHash'
import { paths } from './routes/paths'
import { pathForView } from './routes/viewMap'
import { navigatePath, parsePathname, panelToFocus, stripLegacyAppHash } from './routes/parsePath'
import { JUMP_KEYS } from './routes/nav'

type NavItem = { id: AppView; label: string; icon: React.ComponentType<{ className?: string }> }
type NavGroup = { title: string; items: NavItem[] }

/**
 * Workspace strip — always the same rows (VS Code Activity/Explorer pattern).
 * Home is always enabled; Editor/Runs/Models/Ship/Datasets require activeProject
 * (disabled + "Open a project first" otherwise). Shape never changes.
 */
const WORKSPACE_NAV_ITEMS: NavItem[] = [
  { id: 'projects', label: 'Home', icon: FolderKanban },
  { id: 'builder', label: 'Editor', icon: Workflow },
  { id: 'runs', label: 'Runs', icon: History },
  { id: 'models', label: 'Models', icon: Box },
  { id: 'edge', label: 'Ship', icon: Cpu },
  { id: 'data', label: 'Datasets', icon: Database },
]

/**
 * Fixed groups below the strip — same titles/items whether or not a workspace
 * is open. Models / Ship / Datasets live only on the workspace strip (not here).
 */
const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Build',
    items: [
      { id: 'templates', label: 'Templates', icon: BookOpen },
      { id: 'proposals', label: 'Agent inbox', icon: GitPullRequest },
    ],
  },
  {
    title: 'Library',
    items: [
      { id: 'plugins', label: 'Plugins', icon: Package },
      { id: 'artifacts', label: 'Artifacts', icon: Archive },
    ],
  },
  {
    title: 'Deploy',
    items: [
      { id: 'workers', label: 'Worker fleet', icon: Server },
    ],
  },
  {
    title: 'Admin',
    items: [
      { id: 'secrets', label: 'Secrets', icon: KeyRound },
      { id: 'system', label: 'Ops', icon: Activity },
      { id: 'access', label: 'Access', icon: Shield },
    ],
  },
]

const VIEW_LABEL: Record<AppView, string> = {
  builder: 'Editor',
  templates: 'Templates',
  runs: 'Runs',
  plugins: 'Plugins',
  data: 'Datasets',
  artifacts: 'Artifacts',
  edge: 'Ship',
  experiments: 'Compare runs',
  proposals: 'Agent inbox',
  projects: 'Home',
  secrets: 'Secrets',
  system: 'Ops',
  workers: 'Worker fleet',
  models: 'Models',
  access: 'Access',
  devices: 'Devices',
}

const NAV_HINTS: Partial<Record<AppView, string>> = {
  builder: 'Editor — design Graph IR pipelines on the canvas',
  templates: 'Templates — stamp a starter graph into a workspace',
  proposals: 'Agent inbox — review agent GraphIR before it enters the Editor',
  runs: 'Runs — history; open a run for Outputs, Lineage, and Compare',
  experiments: 'Compare runs — prefer Runs → Compare when a workspace is open',
  artifacts: 'Artifacts — cross-run registry; for one run use Runs → Run outputs',
  plugins: 'Plugins — install node packs for the Editor catalog',
  data: 'Datasets — shared Inputs/Outputs library (not run downloads)',
  edge: 'Ship — edge package and devices',
  workers: 'Worker fleet — distributed workers (Mode B only)',
  projects: 'Home — workspace status, pipelines, linked data, runs',
  secrets: 'Secrets — named credentials for graphs',
  system: 'Ops — health, schedules, webhooks, cleanup, audit',
  models: 'Models — registry stages and prod approve',
  access: 'Access — actor identity and future RBAC',
  devices: 'Devices — fleet inventory (API pending)',
}

/** Compact last-run observe control — Trace / Artifacts / Compare live in a menu. (ux-pass) */
/** Dot colour for a finished run's outcome, folded into the run chip so the
 *  header doesn't carry a second pill saying the same thing in words. */
const OUTCOME_DOT: Record<string, string> = {
  failed: 'bg-rose-500',
  cancelled: 'bg-ink-400',
  succeeded: 'bg-emerald-500',
  running: 'bg-amber-500',
}

function LastRunMenu({
  runId,
  showCompare,
  outcome,
  outcomeLabel,
  onOpenRun,
  onOpenTrace,
  onOpenArtifacts,
  onOpenCompare,
}: {
  runId: string
  showCompare: boolean
  outcome?: string | null
  outcomeLabel?: string | null
  onOpenRun: () => void
  onOpenTrace: () => void
  onOpenArtifacts: () => void
  onOpenCompare: () => void
}) {
  const [open, setOpen] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])
  return (
    <div
      ref={rootRef}
      className="relative flex items-center gap-0.5"
      title={outcomeLabel ? `Last run ${outcomeLabel.toLowerCase()} · ${runId}` : `Last run ${runId}`}
    >
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-l-full border border-ink-200 bg-white px-2.5 py-0.5 font-mono text-[11px] text-ink-700 hover:border-accent-400 hover:text-accent-800"
        onClick={onOpenRun}
      >
        {outcome ? (
          <span
            aria-hidden
            className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', OUTCOME_DOT[outcome] ?? 'bg-ink-300')}
          />
        ) : null}
        Last {shortRunId(runId)}
        {outcomeLabel ? <span className="sr-only"> — {outcomeLabel}</span> : null}
      </button>
      <button
        type="button"
        className="rounded-r-full border border-l-0 border-ink-200 bg-white px-1.5 py-0.5 text-[11px] text-ink-600 hover:border-accent-300 hover:text-accent-800"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Last run actions"
        onClick={() => setOpen((o) => !o)}
      >
        ▾
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-40 mt-1 min-w-[9.5rem] rounded-xl border border-ink-200 bg-white py-1 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-[12px] text-ink-800 hover:bg-ink-50"
            onClick={() => {
              setOpen(false)
              onOpenTrace()
            }}
          >
            Lineage
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-[12px] text-ink-800 hover:bg-ink-50"
            onClick={() => {
              setOpen(false)
              onOpenArtifacts()
            }}
          >
            Run outputs
          </button>
          {showCompare && (
            <button
              type="button"
              role="menuitem"
              className="block w-full px-3 py-1.5 text-left text-[12px] text-ink-800 hover:bg-ink-50"
              onClick={() => {
                setOpen(false)
                onOpenCompare()
              }}
            >
              Compare runs…
            </button>
          )}
        </div>
      )}
    </div>
  )
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
  const activeProject = useAppStore((s) => s.activeProject)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const closeProject = useAppStore((s) => s.closeProject)
  const openProject = useAppStore((s) => s.openProject)
  const statusMessage = useAppStore((s) => s.statusMessage)
  const runOutcome = useAppStore((s) => s.runOutcome)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const lastRunProject = useAppStore((s) => s.lastRunProject)
  const isRunning = useAppStore((s) => s.isRunning)
  const toasts = useAppStore((s) => s.toasts)
  const dismissToast = useAppStore((s) => s.dismissToast)
  const dismissAllToasts = useAppStore((s) => s.dismissAllToasts)
  const pushToast = useAppStore((s) => s.pushToast)
  const bootError = useAppStore((s) => s.bootError)
  const bootStatus = useAppStore((s) => s.bootStatus)
  const backendMode = useAppStore((s) => s.backendMode)
  const setBackendMode = useAppStore((s) => s.setBackendMode)
  const pendingProposalCount = useAppStore((s) => s.pendingProposalCount)
  const setPendingProposalCount = useAppStore((s) => s.setPendingProposalCount)
  const setBootError = useAppStore((s) => s.setBootError)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const [helpOpen, setHelpOpen] = React.useState(false)
  const [paletteOpen, setPaletteOpen] = React.useState(false)
  const [modeExplainerOpen, setModeExplainerOpen] = React.useState(false)
  const [tokenDraft, setTokenDraft] = React.useState('')
  const [tokenVisible, setTokenVisible] = React.useState(false)
  const [authHonesty, setAuthHonesty] = React.useState<{
    auth_required?: boolean
    token_configured?: boolean
  } | null>(null)
  const settingsPanelRef = React.useRef<HTMLDivElement>(null)
  const settingsTriggerRef = React.useRef<HTMLElement | null>(null)
  const tokenInputRef = React.useRef<HTMLInputElement>(null)
  const [navOpen, setNavOpen] = React.useState(() => {
    if (typeof window === 'undefined') return true
    try {
      const stored = localStorage.getItem('graphyn.layout.navOpen')
      if (stored === '0') return false
      if (stored === '1') return true
    } catch {
      /* ignore */
    }
    return window.matchMedia('(min-width: 768px)').matches
  })
  const [narrow, setNarrow] = React.useState(() =>
    typeof window !== 'undefined' ? !window.matchMedia('(min-width: 768px)').matches : false,
  )
  React.useEffect(() => {
    try {
      localStorage.setItem('graphyn.layout.navOpen', navOpen ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [navOpen])

  const [locationKey, setLocationKey] = React.useState(
    () => `${window.location.pathname}${window.location.search}`,
  )
  React.useEffect(() => {
    const bump = () => setLocationKey(`${window.location.pathname}${window.location.search}`)
    window.addEventListener('popstate', bump)
    return () => window.removeEventListener('popstate', bump)
  }, [])

  const parsedLocation = React.useMemo(
    () => parsePathname(window.location.pathname, window.location.search),
    [locationKey],
  )
  /** Workspace id present in the URL (not localStorage alone). */
  const workspaceOpen = Boolean(parsedLocation.workspaceId)

  /**
   * Collapse alias URLs onto one canonical spelling. `/`, `/workspaces` and any
   * unmatched path all render the workspaces picker, so the same page could sit
   * under three different URLs depending on how you got there — and whichever
   * one you arrived on stayed in the address bar, so bookmarks and shared links
   * disagreed about the address of a single page. replaceState (not
   * navigatePath) on purpose: no popstate, so this cannot re-enter the parse.
   */
  React.useEffect(() => {
    const canonical = parsedLocation.canonical
    if (!canonical || window.location.pathname === canonical) return
    window.history.replaceState(null, '', `${canonical}${window.location.search}`)
  }, [parsedLocation])

  /**
   * Reconcile legacy `#/…` fragments on path URLs.
   *
   * This effect also used to auto-resume: landing on `/` or `/workspaces`
   * redirected straight into whichever workspace you had open last, so the app
   * had no landing page you could actually reach — every entry bounced past it
   * into a workspace you might not have wanted, and typing `/workspaces`
   * silently took you somewhere else. The workspaces console surfaces recents
   * itself (sorted recently-opened first, with a Recent tag), so getting back to
   * yesterday's work is one visible click instead of a redirect that overrides
   * the address you asked for.
   */
  React.useEffect(() => {
    const { hash } = window.location
    if (!hash || !/^#\//.test(hash)) return
    const target = resolveLegacyHash(hash, { activeProject: useAppStore.getState().activeProject })
    if (target) navigatePath(target, true)
    else stripLegacyAppHash()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Prefer project's latest run (same API as Overview) for header chip / Last-run menu. */
  const [projectLatest, setProjectLatest] = React.useState<{
    run_id: string
    status?: string
  } | null>(null)
  React.useEffect(() => {
    let cancelled = false
    let timer: number | null = null
    if (!activeProject) {
      setProjectLatest(null)
      return
    }
    const project = activeProject
    const NON_TERMINAL = new Set(['running', 'queued', 'pending', 'paused'])
    const fetchLatest = async () => {
      try {
        const runs = await apiJson<
          Array<{ run_id: string; status?: string; created_at?: string }>
        >('/runs', { query: { limit: 8, offset: 0, project } })
        if (cancelled) return
        const first = Array.isArray(runs) && runs.length > 0 ? runs[0] : null
        setProjectLatest(first ? { run_id: first.run_id, status: first.status } : null)
        // Keep polling while the latest run is still non-terminal — otherwise
        // this one-shot fetch freezes the header chip at "Running" forever
        // once the user navigates away from whatever started the run (the
        // isRunning/lastRunId deps below never change again to re-trigger it).
        const status = (first?.status || '').toLowerCase()
        if (!cancelled && NON_TERMINAL.has(status)) {
          timer = window.setTimeout(fetchLatest, 4000)
        }
      } catch {
        if (!cancelled) setProjectLatest(null)
      }
    }
    void fetchLatest()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [activeProject, lastRunId, isRunning])

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
    try {
      const ready = await apiJson<{ backend_mode?: string }>('/system/readiness')
      const mode = String(ready?.backend_mode || '').toLowerCase()
      setBackendMode(mode === 'distributed' ? 'distributed' : mode === 'local' ? 'local' : null)
    } catch {
      /* readiness is optional for catalog boot */
    }
    try {
      const auth = await apiJson<{ auth_required?: boolean; token_configured?: boolean }>(
        '/system/auth-status',
      )
      setAuthHonesty(auth)
    } catch {
      /* optional */
    }
  }, [setCatalog, setBootError, setSettingsOpen, setBackendMode])

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

  /** Path ↔ store sync (HTML5 History). Hash handled by <HashRedirect />. */
  React.useEffect(() => {
    const apply = () => {
      stripLegacyAppHash()
      const parsed = parsePathname(window.location.pathname, window.location.search)
      const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
      if (parts[0] === 'workspaces' && !parts[1]) {
        setActiveProject(null)
      } else if (parsed.workspaceId) {
        const cur = useAppStore.getState().activeProject
        if (cur !== parsed.workspaceId) setActiveProject(parsed.workspaceId)
      }
      if (parsed.runsTab === 'compare' || parsed.view === 'experiments') {
        openExperiments(parsed.compareIds?.length ? { runIds: parsed.compareIds } : {})
        return
      }
      if (parsed.runId) {
        openRun(parsed.runId, {
          project: parsed.workspaceId,
          panel: panelToFocus(parsed.panel) ?? undefined,
        })
        return
      }
      if (parsed.view) setView(parsed.view)
      if (parsed.runsTab === 'live') useAppStore.getState().setFocusRunsTab('live')
      else if (parsed.runsTab === 'history' && parsed.view === 'runs') {
        useAppStore.getState().setFocusRunsTab('history')
      }
    }
    apply()
    window.addEventListener('popstate', apply)
    return () => window.removeEventListener('popstate', apply)
  }, [openRun, openExperiments, setView, setActiveProject])

  React.useEffect(() => {
    const label = VIEW_LABEL[view] || 'Console'
    const ws = activeProject ? ` · ${activeProject}` : ''
    document.title = `Graphyn · ${label}${ws}`
  }, [view, activeProject])

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
    const ap = useAppStore.getState().activeProject
    const path = pathForView(id, { workspaceId: ap })
    if (!path) {
      pushToast('Open a workspace first', 'info')
      setView('projects')
      navigatePath(paths.workspaces())
      if (narrow) setNavOpen(false)
      return
    }
    setView(id)
    navigatePath(path)
    if (narrow) setNavOpen(false)
  }

  /** Switch workspace: clear active project, then show the Projects picker. */
  const switchProject = () => {
    closeProject()
    setView('projects')
    navigatePath(paths.workspaces())
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
      if (modeExplainerOpen) {
        if (e.key === 'Escape') {
          e.preventDefault()
          setModeExplainerOpen(false)
        }
        return
      }
      if (paletteOpen) {
        return
      }
      // Cmd-K / "/" owned by CommandPalette (mounted below)
      const metaK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'
      const slash = e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey
      if (metaK || (slash && !typing)) {
        e.preventDefault()
        setPaletteOpen(true)
        return
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault()
        setHelpOpen(true)
        return
      }
      const key = e.key.toLowerCase()
      if (key === 'o') {
        e.preventDefault()
        const rid = useAppStore.getState().lastRunId
        if (rid) openTrace({ runId: rid })
        else go('runs')
        return
      }
      if (key === 'e') {
        e.preventDefault()
        const rid = useAppStore.getState().lastRunId
        openExperiments(rid ? { runIds: [rid] } : {})
        return
      }
      const dest = JUMP_KEYS[key]
      if (dest) {
        e.preventDefault()
        go(dest)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [view, settingsOpen, helpOpen, paletteOpen, modeExplainerOpen, narrow])

  /** Prefer Overview-style project latest run when a workspace is open; keep lastRunProject scoping. */
  const editorScoped =
    Boolean(lastRunId) && (!activeProject || !lastRunProject || lastRunProject === activeProject)
  const effectiveLastRunId = activeProject
    ? projectLatest?.run_id || (editorScoped ? lastRunId : null)
    : lastRunId
  const projectStatus = (projectLatest?.status || '').toLowerCase()
  const projectOutcome =
    projectStatus === 'failed' || projectStatus === 'error'
      ? 'failed'
      : projectStatus === 'cancelled' || projectStatus === 'canceled'
        ? 'cancelled'
        : projectStatus === 'succeeded' ||
            projectStatus === 'completed' ||
            projectStatus === 'success'
          ? 'succeeded'
          : projectStatus === 'running' || projectStatus === 'queued' || projectStatus === 'paused'
            ? 'running'
            : null
  const usingProjectLatest =
    Boolean(activeProject && projectLatest?.run_id && effectiveLastRunId === projectLatest.run_id)
  const effectiveOutcome = usingProjectLatest
    ? projectOutcome || (editorScoped && lastRunId === effectiveLastRunId ? runOutcome : null)
    : runOutcome
  const chipLabel = isRunning
    ? statusMessage && statusMessage !== 'Running…'
      ? statusMessage
      : 'Running'
    : statusMessage ||
      (effectiveOutcome === 'failed'
        ? 'Failed'
        : effectiveOutcome === 'cancelled'
          ? 'Cancelled'
          : effectiveOutcome === 'succeeded'
            ? 'Succeeded'
            : effectiveOutcome === 'running'
              ? 'Running'
              : null)
  const chipTone = isRunning
    ? 'bg-amber-100 text-amber-900'
    : effectiveOutcome === 'failed'
      ? 'bg-rose-100 text-rose-800'
      : effectiveOutcome === 'cancelled'
        ? 'bg-ink-100 text-ink-600'
        : effectiveOutcome === 'succeeded'
          ? 'bg-emerald-100 text-emerald-800'
          : effectiveOutcome === 'running'
            ? 'bg-amber-100 text-amber-900'
            : 'bg-ink-100 text-ink-600'

  const mainContent = (
    <main className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {window.location.pathname.startsWith('/login') ? (
        <LoginView />
      ) : (
        <>
          {view === 'builder' && <BuilderView />}
          {view === 'runs' && <RunsView />}
          {view === 'artifacts' && <ArtifactsView />}
          {view === 'plugins' && <PluginsView />}
          {view === 'templates' && <TemplatesView />}
          {view === 'data' && <DataView />}
          {view === 'projects' && <ProjectsView />}
          {view === 'system' && <SystemView />}
          {view === 'workers' && <WorkersView />}
          {view === 'edge' && <EdgeWizardView />}
          {view === 'experiments' && <ExperimentsView />}
          {view === 'proposals' && <ProposalsView />}
          {view === 'secrets' && <SecretsView />}
          {view === 'models' && <ModelsView />}
          {view === 'access' && <AccessView />}
          {view === 'devices' && <DevicesView workspaceId={activeProject} />}
        </>
      )}
    </main>
  )

  /** Hint + jump-key suffix, shared by every nav row so the tooltip format never drifts. */
  const navTitle = (id: AppView, fallback?: string) => {
    const hint = NAV_HINTS[id] ?? fallback
    if (!hint) return undefined
    const jump = Object.entries(JUMP_KEYS).find(([, v]) => v === id)?.[0]
    return jump ? `${hint} · Press ${jump}` : hint
  }

  const navAside = (
    <aside
              className={clsx(
                'z-30 flex h-full min-h-0 flex-col border-r border-ink-200/80 bg-[#f7f7f8]',
                narrow ? 'absolute inset-y-0 left-0 w-[13.5rem] shadow-xl' : 'w-full',
              )}
            >
              {/*
                One fixed shape, always: Workspace strip (Home/Editor/Runs/Models/Ship/Datasets,
                disabled without activeProject) then the same four NAV_GROUPS. Only enabled
                state and highlight change — never a different collapsed Library&admin chrome.
              */}
              <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Primary">
                <div className="mb-3 space-y-0.5">
                  <div className="flex items-center justify-between gap-2 px-2.5 pb-1">
                    {activeProject ? (
                      <>
                        <div
                          className="truncate text-[10px] font-semibold uppercase tracking-wide text-ink-400"
                          title={activeProject}
                        >
                          Workspace: {activeProject}
                        </div>
                        <button
                          type="button"
                          className="shrink-0 text-[10px] font-medium text-ink-400 hover:text-ink-800"
                          title="Switch workspace — show project picker"
                          onClick={switchProject}
                        >
                          Switch
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                          No project open
                        </div>
                        <button
                          type="button"
                          className="shrink-0 text-[10px] font-medium text-accent-800 hover:text-accent-950"
                          title="Open a project"
                          onClick={() => go('projects')}
                        >
                          Open
                        </button>
                      </>
                    )}
                  </div>
                  <div className="space-y-0.5">
                    {WORKSPACE_NAV_ITEMS.map(({ id, label, icon: Icon }) => {
                      const active = view === id
                      const enabled = id === 'projects' || Boolean(activeProject)
                      return (
                        <button
                          key={`ws-${id}`}
                          type="button"
                          disabled={!enabled}
                          title={enabled ? navTitle(id) : 'Open a project first'}
                          onClick={() => go(id)}
                          className={clsx(
                            'relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-left text-[13px] transition',
                            !enabled && 'cursor-not-allowed opacity-40',
                            active
                              ? 'bg-white font-medium text-ink-950 shadow-sm'
                              : enabled && 'text-ink-700 hover:bg-white/70 hover:text-ink-950',
                          )}
                          aria-current={active ? 'page' : undefined}
                        >
                          <Icon className={clsx('h-4 w-4', active ? 'text-accent-800' : 'text-ink-400')} />
                          <span className="flex-1 truncate">{label}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
                {NAV_GROUPS.map((group) => (
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
                            title={navTitle(id)}
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
                ))}
              </nav>
            </aside>
  )


  return (
    <ErrorBoundary>
      <LayoutPrefsProvider>
      <HashRedirect activeProject={activeProject} />
      <div className="flex h-full flex-col overflow-hidden bg-mesh">
        <header className="relative z-40 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-ink-200/70 bg-white/80 px-4 backdrop-blur-md">
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
              {/* The workspace name is already shown in the sidebar's Workspace strip and in the
                  page's own title — repeating it here too just added a third copy of the same
                  string. This line is now purely "which page," matching the sidebar's own labels. */}
              <div className="truncate text-[11px] text-ink-500">{VIEW_LABEL[view]}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Single status chip: mode + connection (Auth banner handles 401 CTA) */}
            <button
              type="button"
              onClick={() => {
                if (bootStatus === 401) openSettings()
                else if (!bootError) setModeExplainerOpen(true)
              }}
              className={clsx(
                'hidden items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium sm:inline-flex',
                bootStatus === 401
                  ? 'border-amber-200 bg-amber-50 text-amber-900'
                  : bootError
                    ? 'border-rose-200 bg-rose-50 text-rose-800'
                    : backendMode === 'distributed'
                      ? 'border-accent-300 bg-accent-50 text-accent-950'
                      : 'border-ink-200 bg-white text-ink-600 hover:border-ink-300',
              )}
              title={
                bootStatus === 401
                  ? 'Paste API token in Settings'
                  : bootError
                    ? bootError
                    : 'Click for Mode A vs Mode B'
              }
            >
              {bootStatus === 401
                ? 'Sign in'
                : bootError
                  ? 'Offline'
                  : backendMode === 'distributed'
                    ? 'Distributed'
                    : 'Local'}
              {authHonesty?.auth_required && !bootError && bootStatus !== 401 ? (
                <span className="text-ink-400">· Auth</span>
              ) : null}
            </button>
            {(() => {
              // A finished run used to get TWO adjacent chips for the same thing: a
              // bare outcome word ("Succeeded" — at what?) and the "Last <id>" menu
              // right beside it. The outcome is now a dot inside that run chip, so
              // only the in-flight case (and a status with no run id yet) still needs
              // a pill of its own.
              if (!chipLabel) return null
              if (isRunning) {
                return (
                  <span className={clsx('inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold', chipTone)}>
                    {chipLabel}
                  </span>
                )
              }
              if (!effectiveLastRunId) {
                return (
                  <span className={clsx('hidden max-w-[12rem] truncate rounded-full px-2.5 py-0.5 text-[11px] font-medium lg:inline', chipTone)}>
                    {chipLabel}
                  </span>
                )
              }
              return null
            })()}
            {workspaceOpen && parsedLocation.workspaceId && (
              <div className="inline-flex max-w-[15rem] items-center gap-0.5">
                <button
                  type="button"
                  className="inline-flex max-w-[12rem] items-center gap-1 truncate rounded-l-full border border-accent-300 bg-accent-50 px-2.5 py-0.5 text-[11px] font-medium text-accent-900 hover:border-accent-400"
                  title="Open workspace Home"
                  onClick={() => {
                    const W = parsedLocation.workspaceId || activeProject
                    if (W) openProject(W)
                  }}
                >
                  <FolderKanban className="h-3 w-3 shrink-0" />
                  <span className="truncate">{parsedLocation.workspaceId || activeProject}</span>
                </button>
                <button
                  type="button"
                  className="rounded-r-full border border-l-0 border-accent-300 bg-accent-50 px-1.5 py-0.5 text-[11px] font-medium text-accent-800 hover:bg-accent-100"
                  title="Switch workspace — leave to project picker"
                  onClick={switchProject}
                >
                  Switch
                </button>
              </div>
            )}
            {/* With no project open, this chip said "Open workspace" and navigated to
                the projects picker — which, on the picker itself, is the page you are
                already looking at. A visible, enabled, no-op control; hidden there. */}
            {(!activeProject || !workspaceOpen) && !(!activeProject && view === 'projects') && (
              <button
                type="button"
                className={clsx(
                  'inline-flex max-w-[13rem] items-center gap-1 truncate rounded-full border px-2.5 py-0.5 text-[11px]',
                  activeProject
                    ? 'border-accent-200 bg-accent-50/60 text-accent-800 hover:border-accent-300'
                    : 'border-dashed border-ink-300 bg-white/80 text-ink-500 hover:border-accent-300 hover:text-accent-800',
                )}
                // On a global page (Artifacts/Templates/Secrets/…), activeProject can still be
                // set from earlier — the workspace was never closed, just not part of this URL.
                // Say so explicitly instead of the generic "Open workspace", which reads as
                // "nothing is open" and made the project feel silently lost.
                title={activeProject ? `${activeProject} is still open — return to it` : 'Open a project'}
                onClick={() => {
                  if (activeProject) openProject(activeProject)
                  else go('projects')
                }}
              >
                {activeProject ? (
                  <>
                    <FolderKanban className="h-3 w-3 shrink-0" />
                    <span className="truncate">Back to {activeProject}</span>
                  </>
                ) : (
                  'Open workspace'
                )}
              </button>
            )}
            {effectiveLastRunId && (
              <LastRunMenu
                runId={effectiveLastRunId}
                showCompare
                outcome={isRunning ? null : effectiveOutcome}
                outcomeLabel={isRunning ? null : chipLabel}
                onOpenRun={() =>
                  openRun(effectiveLastRunId, activeProject ? { project: activeProject } : undefined)
                }
                onOpenTrace={() =>
                  openTrace({ runId: effectiveLastRunId, project: activeProject || undefined })
                }
                onOpenArtifacts={() =>
                  openArtifacts({ runId: effectiveLastRunId, project: activeProject || undefined })
                }
                onOpenCompare={() => openExperiments({ runIds: [effectiveLastRunId] })}
              />
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

        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          {navOpen && narrow && (
            <button
              type="button"
              className="absolute inset-0 z-20 bg-ink-950/30 md:hidden"
              aria-label="Close navigation"
              onClick={() => setNavOpen(false)}
            />
          )}
          {navOpen && !narrow ? (
            <SplitPane
              className="h-full min-h-0 w-full flex-1"
              storageKey={LAYOUT_KEYS.nav}
              defaultSize={216}
              minSize={168}
              maxSize={300}
              paneOverflow="hidden"
            >
              {[navAside, mainContent]}
            </SplitPane>
          ) : (
            <>
              {navOpen ? navAside : null}
              {mainContent}
            </>
          )}
        </div>

        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} onOpenChange={setPaletteOpen} />
        <KeyboardHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
        {modeExplainerOpen && (
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center bg-ink-950/30 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mode-explainer-title"
            onClick={() => setModeExplainerOpen(false)}
          >
            <div
              className="w-full max-w-md rounded-2xl border border-ink-200 bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-3">
                <h2 id="mode-explainer-title" className="text-base font-semibold text-ink-950">
                  Execution mode
                </h2>
                <button
                  type="button"
                  className="rounded-lg p-1 text-ink-400 hover:bg-ink-50 hover:text-ink-700"
                  aria-label="Close"
                  onClick={() => setModeExplainerOpen(false)}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-ink-600">
                {backendMode === 'distributed' ? (
                  <>
                    <strong className="font-medium text-ink-900">Mode B — Distributed.</strong> The
                    control plane schedules nodes onto registered workers. Placement and labels in
                    the graph are honored.
                  </>
                ) : (
                  <>
                    <strong className="font-medium text-ink-900">Mode A — Local.</strong> This API
                    host runs every node in-process. Graph placement is ignored until you switch to
                    Distributed.
                  </>
                )}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {backendMode === 'distributed' ? (
                  <>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => {
                        setModeExplainerOpen(false)
                        go('workers')
                      }}
                    >
                      Open Worker fleet
                    </button>
                    <button type="button" className="btn-secondary" onClick={() => setModeExplainerOpen(false)}>
                      Got it
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className="btn-primary" onClick={() => setModeExplainerOpen(false)}>
                      Got it
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        setModeExplainerOpen(false)
                        go('workers')
                      }}
                    >
                      Mode B · Worker fleet
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
        <ToastHost toasts={toasts} onDismiss={dismissToast} onDismissAll={dismissAllToasts} />

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
              <div className="mt-5 border-t border-ink-100 pt-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm text-ink-700">Content layout</div>
                    <p className="mt-0.5 text-xs text-ink-500">
                      Master–Detail shows list and detail side-by-side; Stack shows them one above
                      the other. Applies to Runs, Datasets, and similar split views.
                    </p>
                  </div>
                  <LayoutModeControl className="shrink-0" />
                </div>
              </div>
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
      </LayoutPrefsProvider>
    </ErrorBoundary>
  )
}
