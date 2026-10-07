import React from 'react'
import clsx from 'clsx'
import {
  Boxes,
  Workflow,
  History,
  Package,
  BookOpen,
  Database,
  FolderKanban,
  Activity,
  Settings,
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
  KeyRound,
  ChevronDown,
} from 'lucide-react'
import { apiJson, ApiError, getApiToken, setApiToken } from './api/client'
import { fetchAllPages, unwrapList } from './api/unwrapList'
import {
  commitActiveProject,
  forgetPersistedActiveProject,
  useAppStore,
  type AppView,
} from './store/appStore'
import type { NodeCatalogEntry } from './types/graph'
import { ErrorBoundary, ToastHost } from './components/ui'
import { ViewErrorBoundary } from './components/ViewErrorBoundary'
import { SplitPane } from './components/SplitPane'
import { LayoutModeControl, LayoutPrefsProvider, LAYOUT_KEYS } from './layout'
import { runDisplayName, runStatusLabel } from './lib/runDisplay'
import { KeyboardHelp } from './components/KeyboardHelp'
import { CommandPalette } from './components/CommandPalette'
import { NotificationBell } from './components/NotificationBell'
import { ActorName } from './components/ActorName'
import { notifyIdentityChanged, useMe } from './lib/identity'
import { DEVICES_ENABLED } from './features/ship/devicesFlag'
import BuilderView from './features/builder/BuilderView'
import RunsView from './features/runs/RunsView'
import PluginsView from './features/plugins/PluginsView'
import TemplatesView from './features/templates/TemplatesView'
import DataView from './features/data/DataView'
import ProjectsView from './features/projects/ProjectsView'
import SystemView from './features/system/SystemView'
import CredentialsView from './features/credentials/CredentialsView'
import WorkersView from './features/workers/WorkersView'
import EdgeWizardView from './features/edge/EdgeWizardView'
import ExperimentsView from './features/experiments/ExperimentsView'
import ProposalsView from './features/proposals/ProposalsView'
import ModelsView from './features/models/ModelsView'
import AccessView from './features/access/AccessView'
import DevicesView from './features/ship/DevicesView'
import LoginView from './features/auth/LoginView'
import { paths } from './routes/paths'
import { pathForView } from './routes/viewMap'
import { navigatePath, parsePathname, panelToFocus, stripLegacyAppHash } from './routes/parsePath'
import { JUMP_KEYS } from './routes/nav'
import { NAV_SECTIONS, navHighlightFor, navSectionFor } from './routes/navSections'
import { usePolling } from './lib/usePolling'
import { BREAKPOINTS, sidebarModeFor, useViewport } from './lib/viewport'
import { installGlobalDetailsMenuDismiss, OPEN_MODE_EXPLAINER_EVENT, useMenuDismiss } from './lib/menus'
import { sharedFetch } from './lib/sharedFetch'
import { checkRunExists } from './lib/runExists'
import { forgetRecentWorkspace, pruneRecentWorkspaces, readRecentWorkspaces } from './lib/recentWorkspaces'
import {
  checkWorkspaceExists,
  isWorkspaceKnownMissing,
  isWorkspaceKnownValid,
  listWorkspaceNames,
  pickFallbackWorkspace,
} from './lib/workspaceValidity'
import { confirmNavigation } from './lib/navigationGuard'
import { NotFoundView } from './components/NotFoundView'
import { WorkspaceNotFoundView } from './components/WorkspaceNotFoundView'

/** Sidebar icons — structure lives in routes/navSections.ts (pure, tested). */
const NAV_ICON: Partial<Record<AppView, React.ComponentType<{ className?: string }>>> = {
  projects: FolderKanban,
  builder: Workflow,
  runs: History,
  models: Box,
  edge: Cpu,
  data: Database,
  templates: BookOpen,
  plugins: Package,
  proposals: GitPullRequest,
  workers: Server,
  credentials: KeyRound,
  system: Activity,
  access: Shield,
}

const ADMIN_OPEN_KEY = 'graphyn.nav.adminOpen'

const VIEW_LABEL: Record<AppView, string> = {
  builder: 'Editor',
  templates: 'Templates',
  runs: 'Runs',
  plugins: 'Plugins',
  data: 'Datasets',
  edge: 'Ship',
  experiments: 'Compare runs',
  proposals: 'Agent inbox',
  projects: 'Home',
  credentials: 'Credentials',
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
  runs: 'Runs — history; open a run for Overview, Outputs, and Compare',
  experiments: 'Compare runs — prefer Runs → Compare when a workspace is open',
  plugins: 'Plugins — install node packs for the Editor catalog',
  data: 'Datasets — shared Inputs/Outputs library (not run downloads)',
  edge: DEVICES_ENABLED ? 'Ship — edge package and devices' : 'Ship — package a trained model for devices',
  workers: 'Worker fleet — distributed workers (Mode B only)',
  projects: 'Home — workspace status, pipelines, linked data, runs',
  credentials: 'Credentials — platform connections & secrets by kind',
  system: 'Ops — health, schedules, webhooks, cleanup, audit',
  models: 'Models — registry stages and prod approve',
  access: 'Access — actor identity and future RBAC',
  ...(DEVICES_ENABLED ? { devices: 'Devices — fleet inventory (API pending)' } : {}),
}

/** Last-run control: "Last run · <pipeline> · <status>" + an actions menu
 *  (Overview / Run outputs / Compare). Status text is coloured only for
 *  exceptions (failed / running / cancelled …); Done stays muted. */
const OUTCOME_TEXT: Record<string, string> = {
  failed: 'text-rose-700',
  cancelled: 'text-ink-600',
  running: 'text-amber-800',
}

function LastRunMenu({
  runId,
  runName,
  showCompare,
  outcome,
  outcomeLabel,
  onOpenRun,
  onOpenTrace,
  onOpenArtifacts,
  onOpenCompare,
  compact = false,
}: {
  compact?: boolean
  runId: string
  runName?: string | null
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
  const close = React.useCallback(() => setOpen(false), [])
  // Escape / outside click / "another menu opened" all close it (lib/menus).
  useMenuDismiss(open, close, rootRef)
  const name = runName || runDisplayName({ run_id: runId })
  return (
    <div
      ref={rootRef}
      className="relative flex min-w-0 items-center gap-0.5"
      title={`Last run · ${name}${outcomeLabel ? ` · ${outcomeLabel}` : ''} (${runId})`}
    >
      {compact ? (
        // Narrow header: icon + status dot; name/status live in the tooltip.
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-l-full border border-ink-200 bg-white px-2 py-1 text-ink-600 hover:border-accent-400 hover:text-accent-800"
          aria-label={`Last run · ${name}${outcomeLabel ? ` · ${outcomeLabel}` : ''}`}
          onClick={onOpenRun}
        >
          <History className="h-3.5 w-3.5" />
          <span
            aria-hidden
            className={clsx(
              'h-1.5 w-1.5 shrink-0 rounded-full',
              outcome === 'running'
                ? 'animate-pulse bg-amber-500'
                : outcome === 'failed'
                  ? 'bg-rose-500'
                  : outcome === 'cancelled'
                    ? 'bg-ink-400'
                    : outcome
                      ? 'bg-emerald-500'
                      : 'bg-ink-300',
            )}
          />
        </button>
      ) : (
      <button
        type="button"
        className="inline-flex min-w-0 max-w-[18rem] items-center gap-1 rounded-l-full border border-ink-200 bg-white px-2.5 py-0.5 text-[11px] text-ink-600 hover:border-accent-400 hover:text-accent-800"
        onClick={onOpenRun}
      >
        {outcome === 'running' ? (
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-amber-500" />
        ) : null}
        <span className="hidden shrink-0 text-ink-400 xl:inline">Last run ·</span>
        <span className="min-w-0 truncate font-medium text-ink-800">{name}</span>
        {outcomeLabel ? (
          <span className={clsx('shrink-0', (outcome && OUTCOME_TEXT[outcome]) || 'text-ink-500')}>
            · {outcomeLabel}
          </span>
        ) : null}
      </button>
      )}
      <button
        type="button"
        className="self-stretch rounded-r-full border border-l-0 border-ink-200 bg-white px-1.5 py-0.5 text-[11px] text-ink-600 hover:border-accent-300 hover:text-accent-800"
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
            Overview
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

/** Icon-rail popover for a collapsible nav section (Admin): one icon, items in a menu. */
function RailSectionMenu({
  title,
  active,
  badge,
  items,
  onSelect,
}: {
  title: string
  active: boolean
  badge: number
  items: Array<{
    id: AppView
    label: string
    Icon: React.ComponentType<{ className?: string }>
    active: boolean
    hint?: string
    badge: number
  }>
  onSelect: (id: AppView) => void
}) {
  const [open, setOpen] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement>(null)
  const close = React.useCallback(() => setOpen(false), [])
  useMenuDismiss(open, close, rootRef)
  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-md transition',
          active ? 'bg-accent-50 text-accent-800' : 'text-ink-500 hover:bg-white hover:text-ink-900',
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${title} menu`}
        title={`${title}: ${items.map((i) => i.label).join(', ')}`}
        onClick={() => setOpen((o) => !o)}
      >
        <Shield className="h-4 w-4" />
        {badge > 0 ? (
          <span aria-hidden className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
        ) : null}
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={title}
          className="absolute left-full top-0 z-50 ml-1.5 min-w-[11rem] rounded-xl border border-ink-200 bg-white py-1 shadow-lg"
        >
          <div className="px-3 pb-1 pt-0.5 text-[11px] font-semibold text-ink-400">{title}</div>
          {items.map(({ id, label, Icon, active: itemActive, hint, badge: itemBadge }) => (
            <button
              key={id}
              type="button"
              role="menuitem"
              title={hint}
              aria-current={itemActive ? 'page' : undefined}
              className={clsx(
                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-ink-50',
                itemActive ? 'font-medium text-accent-900' : 'text-ink-800',
              )}
              onClick={() => {
                setOpen(false)
                onSelect(id)
              }}
            >
              <Icon className="h-3.5 w-3.5 shrink-0 text-ink-500" />
              <span className="flex-1">{label}</span>
              {itemBadge > 0 ? (
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
                  {itemBadge}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
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
  const storeRunOutcome = useAppStore((s) => s.runOutcome)
  const runOutcomeRunId = useAppStore((s) => s.runOutcomeRunId)
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
  /** `GET /me` — header Settings tooltip + identity line in Settings (null on older APIs). */
  const { me } = useMe()
  const [tokenVisible, setTokenVisible] = React.useState(false)
  const [authHonesty, setAuthHonesty] = React.useState<{
    auth_required?: boolean
    token_configured?: boolean
  } | null>(null)
  const settingsPanelRef = React.useRef<HTMLDivElement>(null)
  const settingsTriggerRef = React.useRef<HTMLElement | null>(null)
  const tokenInputRef = React.useRef<HTMLInputElement>(null)
  // Sidebar: the persisted preference only applies ≥1024 (laptop/desktop).
  // Tablet is always the icon rail; phone hides it behind an overlay drawer
  // (lib/viewport.ts `sidebarModeFor`). `navDrawerOpen` is transient.
  const [navPref, setNavPref] = React.useState<'open' | 'collapsed' | null>(() => {
    try {
      const stored = localStorage.getItem('graphyn.layout.navOpen')
      if (stored === '0') return 'collapsed'
      if (stored === '1') return 'open'
    } catch {
      /* ignore */
    }
    return null
  })
  const [navDrawerOpen, setNavDrawerOpen] = React.useState(false)
  const { width: viewportWidth } = useViewport()
  const sidebarMode = sidebarModeFor(viewportWidth, navPref)
  const compactHeader = viewportWidth < BREAKPOINTS.laptop
  // Drawer only exists below the full-sidebar mode; close it when we leave.
  React.useEffect(() => {
    if (sidebarMode === 'full') setNavDrawerOpen(false)
  }, [sidebarMode])
  React.useEffect(() => {
    if (!navDrawerOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNavDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navDrawerOpen])
  // The app shell never scrolls: each pane scrolls itself. `overflow: hidden`
  // boxes can still be scrolled by scrollIntoView/focus, which pushed the header
  // off-screen when a detail panel grew — snap such boxes back (index.css also
  // uses `overflow: clip` on html/body/#root).
  React.useEffect(() => {
    const onScroll = (e: Event) => {
      const t = e.target
      if (t === document) {
        if (window.scrollY || window.scrollX) window.scrollTo(0, 0)
        return
      }
      if (t instanceof HTMLElement && (t.hasAttribute('data-shell-noscroll') || t === document.body || t.id === 'root')) {
        if (t.scrollTop) t.scrollTop = 0
        if (t.scrollLeft) t.scrollLeft = 0
      }
    }
    document.addEventListener('scroll', onScroll, true)
    return () => document.removeEventListener('scroll', onScroll, true)
  }, [])
  const [adminOpen, setAdminOpen] = React.useState(() => {
    try {
      return localStorage.getItem(ADMIN_OPEN_KEY) === '1'
    } catch {
      return false
    }
  })
  React.useEffect(() => {
    try {
      localStorage.setItem(ADMIN_OPEN_KEY, adminOpen ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [adminOpen])
  const toggleSidebar = () => {
    if (viewportWidth >= BREAKPOINTS.laptop) {
      // Laptop/desktop: the user's persisted choice (full ↔ icon rail).
      const next = sidebarMode === 'full' ? 'collapsed' : 'open'
      setNavPref(next)
      try {
        localStorage.setItem('graphyn.layout.navOpen', next === 'open' ? '1' : '0')
      } catch {
        /* ignore */
      }
      return
    }
    // Tablet / phone: temporary overlay drawer with the full navigation.
    setNavDrawerOpen((o) => !o)
  }

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
    // Legacy artifact-id resolve owns navigation — don't rewrite out from under it.
    if (parsedLocation.resolveArtifactId) return
    const canonical = parsedLocation.canonical
    if (!canonical || window.location.pathname === canonical) return
    window.history.replaceState(null, '', `${canonical}${window.location.search}`)
    // Re-parse the canonical URL (replaceState fires no popstate) so the
    // sidebar highlight / 404 state follow the redirect target.
    setLocationKey(`${window.location.pathname}${window.location.search}`)
  }, [parsedLocation])

  /**
   * Cold boot: if address still has a legacy `#/` fragment, clear it and land
   * on `/workspaces` once. No compatibility matrix — hash routing is gone.
   * (Recents live on the Workspaces picker; we do not auto-resume into a workspace.)
   */
  React.useEffect(() => {
    const { hash } = window.location
    if (!hash || !/^#\//.test(hash)) return
    window.history.replaceState(null, '', '/workspaces')
    navigatePath('/workspaces', true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Prefer project's latest run (same API as Overview) for header chip / Last-run menu. */
  const [projectLatest, setProjectLatest] = React.useState<{
    run_id: string
    status?: string
    name?: string
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
        const runs = unwrapList<{ run_id: string; status?: string; created_at?: string }>(
          await apiJson('/runs', { query: { limit: 8, offset: 0, project } }),
        ).filter((r) => r && typeof r.run_id === 'string')
        if (cancelled) return
        const first = runs.length > 0 ? runs[0] : null
        setProjectLatest(
          first ? { run_id: first.run_id, status: first.status, name: runDisplayName(first) } : null,
        )
        // Keep polling while the latest run is still non-terminal — otherwise
        // this one-shot fetch freezes the header chip at "Running" forever
        // once the user navigates away from whatever started the run (the
        // isRunning/lastRunId deps below never change again to re-trigger it).
        const status = (first?.status || '').toLowerCase()
        if (!cancelled && NON_TERMINAL.has(status)) {
          timer = window.setTimeout(fetchLatest, 12000)
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

  const refreshCatalog = React.useCallback(async () => {
    try {
      // GET /nodes defaults to limit=50; page through so Editor shows the full registry.
      const nodes = await fetchAllPages<NodeCatalogEntry>((offset, limit) =>
        apiJson('/nodes', { query: { limit, offset } }),
      )
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

  // Pending-proposal badge. usePolling skips overlapping ticks and pauses
  // while the tab is hidden; resetKey re-runs it after boot status changes.
  usePolling(
    async () => {
      try {
        // Shared with Agent inbox (ProposalsView) so the two never double-fetch.
        const data = await sharedFetch<{ proposals: unknown[] }>(
          'proposals:pending',
          () => apiJson<{ proposals: unknown[] }>('/proposals?status=pending'),
          { maxAgeMs: 10_000 },
        )
        setPendingProposalCount(Array.isArray(data?.proposals) ? data.proposals.length : 0)
      } catch {
        /* quiet — badge is optional */
      }
    },
    60_000,
    { resetKey: bootStatus },
  )

  React.useEffect(() => installGlobalDetailsMenuDismiss(), [])

  React.useEffect(() => {
    const onOpen = () => setModeExplainerOpen(true)
    window.addEventListener(OPEN_MODE_EXPLAINER_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_MODE_EXPLAINER_EVENT, onOpen)
  }, [])

  /**
   * Workspace validation (UI review #2/#3). Every workspace id — from the URL
   * (`/workspaces/<id>/…`) or resumed from localStorage on a global route — is
   * checked with `GET /projects/<id>` before it is persisted as active/recent.
   * A missing id renders WorkspaceNotFoundView (URL case) and the store falls
   * back to the most recent *valid* workspace instead of "No workspace open".
   */
  const urlWorkspaceId = parsedLocation.workspaceId ?? null
  const [wsGate, setWsGate] = React.useState<{
    id: string
    status: 'checking' | 'ok' | 'missing' | 'unknown'
    fallback?: string | null
  } | null>(null)
  React.useEffect(() => {
    const target = urlWorkspaceId || activeProject
    if (!target) {
      setWsGate(null)
      return
    }
    if (isWorkspaceKnownValid(target)) {
      setWsGate({ id: target, status: 'ok' })
      commitActiveProject(target)
      return
    }
    if (bootError) return
    let cancelled = false
    if (!isWorkspaceKnownMissing(target)) setWsGate({ id: target, status: 'checking' })
    void (async () => {
      let exists: boolean
      try {
        exists = await checkWorkspaceExists(target)
      } catch {
        // Offline / auth — keep the workspace (never drop a real one); boot banner explains.
        if (!cancelled) setWsGate({ id: target, status: 'unknown' })
        return
      }
      if (cancelled) return
      if (exists) {
        setWsGate({ id: target, status: 'ok' })
        commitActiveProject(target)
        return
      }
      forgetRecentWorkspace(target)
      let fallback: string | null = null
      try {
        const names = await listWorkspaceNames()
        pruneRecentWorkspaces(names)
        fallback = pickFallbackWorkspace(readRecentWorkspaces(), names, target)
      } catch {
        /* list unavailable — no fallback */
      }
      if (cancelled) return
      setWsGate({ id: target, status: 'missing', fallback })
      const st = useAppStore.getState()
      if (st.activeProject === target) {
        if (fallback) {
          useAppStore.setState({ activeProject: fallback })
          commitActiveProject(fallback)
        } else if (urlWorkspaceId === target) {
          // Stay on the URL (it renders the not-found view); just clear the store.
          useAppStore.setState({ activeProject: null })
          forgetPersistedActiveProject()
        } else {
          setActiveProject(null)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [urlWorkspaceId, activeProject, bootError, setActiveProject])

  /** Prune recents that no longer exist (once per boot, after the API answers). */
  React.useEffect(() => {
    if (bootError) return
    listWorkspaceNames()
      .then((names) => pruneRecentWorkspaces(names))
      .catch(() => undefined)
  }, [bootError])

  const urlWorkspaceMissing =
    Boolean(urlWorkspaceId) &&
    ((wsGate?.id === urlWorkspaceId && wsGate.status === 'missing') ||
      isWorkspaceKnownMissing(urlWorkspaceId))
  // Computed synchronously (not only from wsGate) so workspace views never mount
  // — and never note recents — for an id that has not been validated yet.
  // Skip the blank gate when we are already on this workspace (Editor/Runs hops)
  // or it sits in recents (optimistic paint while GET /projects/{id} finishes).
  const urlWorkspaceChecking =
    Boolean(urlWorkspaceId) &&
    !bootError &&
    !urlWorkspaceMissing &&
    !isWorkspaceKnownValid(urlWorkspaceId) &&
    !(wsGate?.id === urlWorkspaceId && wsGate.status === 'unknown') &&
    activeProject !== urlWorkspaceId &&
    !readRecentWorkspaces().includes(urlWorkspaceId!)

  /** Path ↔ store sync (HTML5 History). */
  React.useEffect(() => {
    const apply = () => {
      stripLegacyAppHash()
      const parsed = parsePathname(window.location.pathname, window.location.search)
      const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
      if (parts[0] === 'workspaces' && !parts[1]) {
        setActiveProject(null)
      } else if (parsed.workspaceId) {
        // A workspace App already knows is missing renders WorkspaceNotFoundView;
        // never make it active (or open runs under it).
        if (isWorkspaceKnownMissing(parsed.workspaceId)) {
          if (parsed.view) setView(parsed.view)
          return
        }
        const cur = useAppStore.getState().activeProject
        if (cur !== parsed.workspaceId) setActiveProject(parsed.workspaceId)
      }
      if (parsed.runsTab === 'compare' || parsed.view === 'experiments') {
        openExperiments(parsed.compareIds?.length ? { runIds: parsed.compareIds } : {})
        return
      }
      // Legacy /library/artifacts?artifactId= → resolve → Runs panel.
      // Also heal sticky `?artifactId=` left on /workspaces/:id/runs from older redirects.
      const qsAid = new URLSearchParams(window.location.search).get('artifactId')
        || new URLSearchParams(window.location.search).get('artifact_id')
        || ''
      const orphanAid = (parsed.resolveArtifactId || qsAid).trim()
      const onRunsList =
        parts[0] === 'workspaces' && parts[2] === 'runs' && !parts[3] && Boolean(orphanAid)
      if (parsed.resolveArtifactId || onRunsList) {
        const aid = orphanAid
        if (!aid) return
        if (parsed.legacyArtifactsOutputs || onRunsList) {
          openArtifacts({ artifactId: aid, project: parsed.workspaceId || parts[1] })
        } else {
          openTrace({ artifactId: aid, project: parsed.workspaceId || parts[1] })
        }
        return
      }
      if (parsed.editorPipeline && parsed.workspaceId) {
        const env = parsed.editorEnv
        useAppStore
          .getState()
          .openPipelineInEditor(
            parsed.editorPipeline,
            env === 'draft' || env === 'staging' || env === 'prod' ? env : undefined,
          )
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
      // /runs/live → unified Runs list with Active filter (no separate Live tab).
      if (parsed.runsTab === 'live' && parsed.workspaceId) {
        useAppStore.getState().setFocusRunsTab('history')
        const target = `${paths.runs(parsed.workspaceId)}?status=active`
        if (`${window.location.pathname}${window.location.search}` !== target) {
          window.history.replaceState(null, '', target)
        }
      } else if (parsed.runsTab === 'history' && parsed.view === 'runs') {
        useAppStore.getState().setFocusRunsTab('history')
      }
    }
    apply()
    window.addEventListener('popstate', apply)
    return () => window.removeEventListener('popstate', apply)
  }, [openRun, openExperiments, openArtifacts, openTrace, setView, setActiveProject])

  const onLoginRoute = window.location.pathname.startsWith('/login')
  React.useEffect(() => {
    if (parsedLocation.notFound) {
      document.title = 'Graphyn · Not found'
      return
    }
    if (urlWorkspaceMissing) {
      document.title = 'Graphyn · Workspace not found'
      return
    }
    if (onLoginRoute) {
      document.title = 'Graphyn · Sign in'
      return
    }
    // Workspace suffix only on workspace-scoped URLs — a global page (Templates,
    // Ops, …) is not "in" the remembered workspace. The picker is "Workspaces".
    const inWorkspace = Boolean(parsedLocation.workspaceId && activeProject)
    const label =
      view === 'projects' && !inWorkspace ? 'Workspaces' : VIEW_LABEL[view] || 'Console'
    const ws = inWorkspace ? ` · ${activeProject}` : ''
    document.title = `Graphyn · ${label}${ws}`
  }, [view, activeProject, parsedLocation, urlWorkspaceMissing, onLoginRoute])

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
    notifyIdentityChanged()
    void refreshCatalog()
  }

  /** Run a navigation action only if the Editor unsaved-changes guard allows it. */
  const guarded = (fn: () => void) => () => {
    if (confirmNavigation()) fn()
  }

  const go = (id: AppView) => {
    if (!confirmNavigation()) return
    const ap = useAppStore.getState().activeProject
    const path = pathForView(id, { workspaceId: ap })
    if (!path) {
      pushToast('Open a workspace first', 'info')
      setView('projects')
      navigatePath(paths.workspaces())
      setNavDrawerOpen(false)
      return
    }
    setView(id)
    navigatePath(path)
    setNavDrawerOpen(false)
  }

  /** Switch workspace: clear active project, then show the Workspaces picker. */
  const switchProject = () => {
    if (!confirmNavigation()) return
    closeProject()
    setView('projects')
    navigatePath(paths.workspaces())
    setNavDrawerOpen(false)
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
        if (rid) {
          if (confirmNavigation()) openTrace({ runId: rid })
        } else go('runs')
        return
      }
      if (key === 'a') {
        e.preventDefault()
        const rid = useAppStore.getState().lastRunId
        if (rid) {
          if (confirmNavigation()) openArtifacts({ runId: rid })
        } else go('runs')
        return
      }
      if (key === 'e') {
        e.preventDefault()
        const rid = useAppStore.getState().lastRunId
        if (confirmNavigation()) openExperiments(rid ? { runIds: [rid] } : {})
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
  }, [view, settingsOpen, helpOpen, paletteOpen, modeExplainerOpen])

  /** Prefer Overview-style project latest run when a workspace is open; keep lastRunProject scoping. */
  // Only runs of the *active* workspace drive the header chip — a run opened
  // from another workspace's schedule (or with no recorded owner) is never shown.
  const editorScoped =
    Boolean(lastRunId) && Boolean(activeProject) && lastRunProject === activeProject
  const effectiveLastRunId = activeProject
    ? projectLatest?.run_id || (editorScoped ? lastRunId : null)
    : null
  // The store outcome only counts for the run it was recorded for.
  const runOutcome =
    runOutcomeRunId && runOutcomeRunId === effectiveLastRunId ? storeRunOutcome : null
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

  /**
   * The fallback store `lastRunId` (not from `GET /runs?project=`) may point at
   * a deleted run, or one owned by another workspace. Verify before showing it;
   * 404 / wrong owner clears it so the chip never links to a dead run.
   */
  const [rejectedRunId, setRejectedRunId] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (!effectiveLastRunId || usingProjectLatest || isRunning) return
    const rid = effectiveLastRunId
    const ws = activeProject
    let cancelled = false
    checkRunExists(rid)
      .then((res) => {
        if (cancelled) return
        const wrongOwner = Boolean(res.exists && res.project && ws && res.project !== ws)
        if (!res.exists || wrongOwner) {
          setRejectedRunId(rid)
          const st = useAppStore.getState()
          if (st.lastRunId === rid) {
            st.setLastRunId(null)
            st.setRunOutcome('idle')
          }
        }
      })
      .catch(() => {
        /* transient — keep showing it */
      })
    return () => {
      cancelled = true
    }
  }, [effectiveLastRunId, usingProjectLatest, isRunning, activeProject])
  const shownLastRunId = effectiveLastRunId && effectiveLastRunId !== rejectedRunId ? effectiveLastRunId : null
  const effectiveOutcome = usingProjectLatest
    ? projectOutcome || (editorScoped && lastRunId === effectiveLastRunId ? runOutcome : null)
    : runOutcome
  const chipLabel = isRunning
    ? statusMessage && statusMessage !== 'Running…'
      ? statusMessage
      : 'Running'
    : statusMessage || (effectiveOutcome ? runStatusLabel(effectiveOutcome) : null)
  // Shared vocabulary (lib/runDisplay): Done / Failed / Running / Queued / …
  const lastRunStatusLabel = isRunning
    ? 'Running'
    : usingProjectLatest && projectStatus
      ? runStatusLabel(projectStatus)
      : effectiveOutcome
        ? runStatusLabel(effectiveOutcome)
        : null
  const lastRunName =
    usingProjectLatest && projectLatest?.run_id === shownLastRunId ? projectLatest?.name ?? null : null

  /** Quiet backend/auth indicator: dot + one word, details in the tooltip. */
  const modeWord = backendMode === 'distributed' ? 'Distributed' : 'Local'
  const authPhrase =
    bootStatus === 401
      ? 'sign-in required'
      : authHonesty?.auth_required
        ? 'signed in'
        : authHonesty
          ? 'no sign-in required'
          : null
  const statusIndicator =
    bootStatus === 401
      ? { word: 'Sign in', dot: 'bg-amber-500', text: 'text-amber-900', tip: 'Sign-in required — paste your API token in Settings' }
      : bootError
        ? { word: 'Offline', dot: 'bg-rose-500', text: 'text-rose-800', tip: `Can't reach the API (${bootError}) — click for Mode A vs Mode B` }
        : {
            word: modeWord,
            dot: backendMode === 'distributed' ? 'bg-accent-500' : 'bg-emerald-500',
            text: 'text-ink-500',
            tip: `${modeWord} backend${authPhrase ? ` · ${authPhrase}` : ''} — click for Mode A vs Mode B`,
          }

  const mainContent = (
    <main className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden" data-shell-noscroll>
      {window.location.pathname.startsWith('/login') ? (
        <LoginView />
      ) : parsedLocation.notFound ? (
        <NotFoundView pathname={window.location.pathname} />
      ) : urlWorkspaceMissing && urlWorkspaceId ? (
        <WorkspaceNotFoundView workspaceId={urlWorkspaceId} fallback={wsGate?.fallback ?? null} />
      ) : urlWorkspaceChecking ? (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6" role="status">
          <div className="h-8 w-8 animate-pulse rounded-full bg-ink-200" aria-hidden />
          <p className="text-[13px] font-medium text-ink-700">
            Opening {urlWorkspaceId}…
          </p>
          <p className="max-w-sm text-center text-[12px] text-ink-500">
            Checking that this workspace still exists on the API.
          </p>
        </div>
      ) : (
        <ViewErrorBoundary resetKey={view} viewLabel={VIEW_LABEL[view] ?? view}>
          {view === 'builder' && <BuilderView />}
          {view === 'runs' && <RunsView />}
          {view === 'plugins' && <PluginsView />}
          {view === 'templates' && <TemplatesView />}
          {view === 'data' && <DataView />}
          {view === 'projects' && <ProjectsView />}
          {view === 'system' && <SystemView />}
          {view === 'workers' && <WorkersView />}
          {view === 'edge' && <EdgeWizardView />}
          {view === 'experiments' && <ExperimentsView />}
          {view === 'proposals' && <ProposalsView />}
          {view === 'credentials' && <CredentialsView />}
          {view === 'models' && <ModelsView />}
          {view === 'access' && <AccessView />}
          {view === 'devices' && <DevicesView workspaceId={activeProject} />}
        </ViewErrorBoundary>
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

  // Highlight follows the URL: nested routes map to their parent row
  // (Compare → Runs, Devices → Ship); a 404 highlights nothing.
  const highlightId = parsedLocation.notFound || urlWorkspaceMissing ? null : navHighlightFor(view)
  const activeSection = highlightId ? navSectionFor(highlightId) : null
  const adminExpanded = adminOpen || activeSection === 'admin'

  const renderNavRow = (id: AppView, label: string, opts: { workspaceScoped?: boolean } = {}) => {
    const Icon = NAV_ICON[id] ?? Box
    const active = highlightId === id
    const isHome = id === 'projects'
    // Work items other than Home need a workspace (greyed + tooltip otherwise).
    const enabled = !opts.workspaceScoped || isHome || Boolean(activeProject)
    return (
      <button
        key={id}
        type="button"
        disabled={!enabled}
        aria-disabled={!enabled}
        title={enabled ? navTitle(id) : 'Open a workspace first — Home stays available'}
        onClick={() => go(id)}
        className={clsx(
          'ide-row',
          !enabled && 'cursor-not-allowed opacity-35 grayscale-[0.35]',
          active && 'is-active font-medium',
          enabled && !active && 'text-ink-700',
        )}
        aria-current={active ? 'page' : undefined}
        data-strip-role={opts.workspaceScoped ? (isHome ? 'home' : 'workspace-scoped') : undefined}
        data-strip-enabled={opts.workspaceScoped ? (enabled ? 'true' : 'false') : undefined}
      >
        <Icon
          className={clsx(
            'h-3.5 w-3.5 shrink-0',
            active ? 'text-accent-800' : enabled ? 'text-ink-500' : 'text-ink-300',
          )}
        />
        <span className="flex-1 truncate">{label}</span>
        {id === 'proposals' && pendingProposalCount > 0 && (
          <span
            className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900"
            title={`${pendingProposalCount} pending proposal${pendingProposalCount === 1 ? '' : 's'}`}
          >
            {pendingProposalCount}
          </span>
        )}
      </button>
    )
  }

  const renderNavAside = (asDrawer: boolean) => (
    <aside
      className={clsx(
        'z-30 flex h-full min-h-0 flex-col border-r border-ink-200/80 bg-[#ebedf0]',
        asDrawer ? 'absolute inset-y-0 left-0 w-[min(15rem,85vw)] shadow-xl' : 'w-full',
      )}
      aria-label={asDrawer ? 'Navigation' : undefined}
    >
      {/*
        Fixed shape: workspace switcher, then Work (workspace-scoped, disabled
        without a workspace), Library, and a collapsible Admin section (closed
        by default; auto-open while one of its pages is active).
      */}
      <nav className="flex-1 overflow-y-auto px-1.5 py-2" aria-label="Primary">
        <div className="mb-2 flex items-center justify-between gap-2 rounded-md px-2 py-1">
          {activeProject ? (
            <>
              <div className="min-w-0">
                <div className="text-[10px] text-ink-400">Workspace</div>
                <div className="truncate text-[12px] font-semibold text-ink-900" title={activeProject}>
                  {activeProject}
                </div>
              </div>
              <button
                type="button"
                className="shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium text-ink-500 hover:bg-white hover:text-ink-900"
                title="Switch workspace — show workspace picker"
                onClick={switchProject}
              >
                Switch
              </button>
            </>
          ) : (
            <>
              <div className="text-[12px] text-ink-500">No workspace open</div>
              <button
                type="button"
                className="shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium text-accent-800 hover:bg-white hover:text-accent-950"
                title="Open a workspace"
                onClick={() => go('projects')}
              >
                Open
              </button>
            </>
          )}
        </div>
        {NAV_SECTIONS.map((section) => {
          if (section.collapsible) {
            const childActive = activeSection === section.id
            return (
              <div key={section.id} className="mb-3" data-nav-section={section.id}>
                <button
                  type="button"
                  className={clsx(
                    'flex w-full items-center gap-1 rounded-md px-2 pb-1 pt-0.5 text-left hover:text-ink-900',
                    childActive && !adminExpanded && 'text-accent-900',
                  )}
                  aria-expanded={adminExpanded}
                  aria-controls={`nav-section-${section.id}`}
                  title={
                    childActive
                      ? `${section.title} — contains the current page`
                      : adminExpanded
                        ? `Hide ${section.title}`
                        : `Show ${section.title}: ${section.items.map((i) => i.label).join(', ')}`
                  }
                  onClick={() => {
                    if (childActive) return
                    setAdminOpen((o) => !o)
                  }}
                >
                  <ChevronDown
                    className={clsx(
                      'h-3 w-3 shrink-0 text-ink-400 transition-transform',
                      !adminExpanded && '-rotate-90',
                    )}
                  />
                  <span className="ide-section-title flex-1">{section.title}</span>
                  {!adminExpanded && pendingProposalCount > 0 ? (
                    <span
                      className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900"
                      title={`${pendingProposalCount} pending in Agent inbox`}
                    >
                      {pendingProposalCount}
                    </span>
                  ) : null}
                </button>
                {adminExpanded ? (
                  <div id={`nav-section-${section.id}`} className="space-y-0.5">
                    {section.items.map((item) => renderNavRow(item.id, item.label))}
                  </div>
                ) : null}
              </div>
            )
          }
          return (
            <div key={section.id} className="mb-3" data-nav-section={section.id}>
              <div className="ide-section-title px-2 pb-1">{section.title}</div>
              <div className="space-y-0.5">
                {section.items.map((item) =>
                  renderNavRow(item.id, item.label, { workspaceScoped: section.id === 'work' }),
                )}
              </div>
            </div>
          )
        })}
      </nav>
    </aside>
  )

  /** Tablet (and collapsed laptop/desktop) icon rail: icons + tooltips; Admin as an icon menu. */
  const renderRailButton = (id: AppView, label: string, opts: { workspaceScoped?: boolean } = {}) => {
    const Icon = NAV_ICON[id] ?? Box
    const active = highlightId === id
    const enabled = !opts.workspaceScoped || id === 'projects' || Boolean(activeProject)
    return (
      <button
        key={id}
        type="button"
        disabled={!enabled}
        aria-disabled={!enabled}
        aria-label={label}
        aria-current={active ? 'page' : undefined}
        title={enabled ? navTitle(id) ?? label : `${label} — open a workspace first`}
        onClick={() => go(id)}
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-md transition',
          active ? 'bg-accent-50 text-accent-800' : 'text-ink-500 hover:bg-white hover:text-ink-900',
          !enabled && 'cursor-not-allowed opacity-35',
        )}
      >
        <Icon className="h-4 w-4" />
        {id === 'proposals' && pendingProposalCount > 0 ? (
          <span aria-hidden className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
        ) : null}
      </button>
    )
  }

  const navRail = (
    <aside
      className="z-20 flex h-full w-12 shrink-0 flex-col items-center border-r border-ink-200/80 bg-[#ebedf0] py-2"
      aria-label="Primary"
      data-sidebar-mode="rail"
    >
      <button
        type="button"
        className="mb-2 flex h-8 w-8 items-center justify-center rounded-md border border-ink-200 bg-white text-[11px] font-semibold text-ink-700 hover:border-accent-300"
        title={activeProject ? `Workspace: ${activeProject} — switch workspace` : 'No workspace open — open one'}
        aria-label={activeProject ? `Workspace ${activeProject} — switch` : 'Open a workspace'}
        onClick={activeProject ? switchProject : () => go('projects')}
      >
        {activeProject ? activeProject.slice(0, 2).toUpperCase() : '+'}
      </button>
      <nav className="flex min-h-0 flex-1 flex-col items-center gap-0.5 overflow-y-auto" aria-label="Primary">
        {NAV_SECTIONS.map((section, idx) =>
          section.collapsible ? (
            <div key={section.id} className="mt-1 border-t border-ink-200/80 pt-1.5" data-nav-section={section.id}>
              <RailSectionMenu
                title={section.title}
                active={activeSection === section.id}
                badge={pendingProposalCount}
                items={section.items.map((item) => ({
                  id: item.id,
                  label: item.label,
                  Icon: NAV_ICON[item.id] ?? Box,
                  active: highlightId === item.id,
                  hint: navTitle(item.id),
                  badge: item.id === 'proposals' ? pendingProposalCount : 0,
                }))}
                onSelect={(id) => go(id)}
              />
            </div>
          ) : (
            <div
              key={section.id}
              className={clsx('flex flex-col items-center gap-0.5', idx > 0 && 'mt-1 border-t border-ink-200/80 pt-1.5')}
              data-nav-section={section.id}
            >
              {section.items.map((item) =>
                renderRailButton(item.id, item.label, { workspaceScoped: section.id === 'work' }),
              )}
            </div>
          ),
        )}
      </nav>
    </aside>
  )

  return (
    <ErrorBoundary>
      <LayoutPrefsProvider>
      <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f0f2f5]" data-shell-noscroll>
        <header className="relative z-40 flex h-11 shrink-0 items-center justify-between gap-2 border-b border-ink-200/80 bg-white px-2 sm:gap-3 sm:px-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {sidebarMode === 'full' || viewportWidth >= BREAKPOINTS.laptop ? (
              <button
                type="button"
                className="btn-quiet shrink-0"
                onClick={toggleSidebar}
                aria-label={sidebarMode === 'full' ? 'Collapse sidebar' : 'Expand sidebar'}
                title={sidebarMode === 'full' ? 'Collapse sidebar to icons' : 'Expand sidebar'}
              >
                <PanelLeftClose className={clsx('h-4 w-4', sidebarMode !== 'full' && 'rotate-180')} />
              </button>
            ) : (
              <button
                type="button"
                className="btn-quiet shrink-0"
                onClick={toggleSidebar}
                aria-expanded={navDrawerOpen}
                aria-label={navDrawerOpen ? 'Close navigation' : 'Open navigation'}
              >
                <Menu className="h-4 w-4" />
              </button>
            )}
            <div className="hidden h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-500 text-ink-950 min-[400px]:flex">
              <Boxes className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 leading-tight">
              <div className="text-[13px] font-semibold text-ink-950">Graphyn</div>
              {/* Workspace context only — page title lives in ViewShell / WorkbenchPage. */}
              {activeProject ? (
                <div className="truncate text-[10px] text-ink-500" title={activeProject}>
                  {activeProject}
                </div>
              ) : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            {/* Quiet status indicator: dot + "Local" / "Distributed" (exceptions
                "Sign in" / "Offline" coloured). Mode + auth details live in the tooltip. */}
            <button
              type="button"
              onClick={() => {
                if (bootStatus === 401) openSettings()
                else setModeExplainerOpen(true)
              }}
              aria-haspopup="dialog"
              aria-expanded={modeExplainerOpen}
              aria-label={statusIndicator.tip}
              className={clsx(
                'hidden items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium hover:bg-ink-50 sm:inline-flex',
                statusIndicator.text,
              )}
              title={statusIndicator.tip}
              data-testid="backend-status"
            >
              <span aria-hidden className={clsx('h-1.5 w-1.5 rounded-full', statusIndicator.dot)} />
              {statusIndicator.word}
            </button>
            {(() => {
              // One run indicator: the Last-run control carries name + status.
              // A separate pill only for an in-flight run with no id yet, or a
              // progress message ("Running 3/7 nodes") beside the Last-run control.
              if (!chipLabel) return null
              if (isRunning && (!shownLastRunId || chipLabel !== 'Running')) {
                return (
                  <span className="hidden max-w-[14rem] items-center gap-1.5 truncate rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 lg:inline-flex">
                    <span aria-hidden className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-amber-500" />
                    <span className="truncate">{chipLabel}</span>
                  </span>
                )
              }
              if (!isRunning && !shownLastRunId) {
                return (
                  <span className="hidden max-w-[12rem] truncate text-[11px] text-ink-500 lg:inline">
                    {chipLabel}
                  </span>
                )
              }
              return null
            })()}
            {/* "Back to <workspace>" / "Open workspace" duplicates the sidebar's
                workspace switcher — show it only while the sidebar is hidden. */}
            {sidebarMode !== 'full' && !compactHeader && (!activeProject || !workspaceOpen) && !(!activeProject && view === 'projects') && (
              <button
                type="button"
                className={clsx(
                  'inline-flex max-w-[13rem] items-center gap-1 truncate rounded-full border px-2.5 py-0.5 text-[11px]',
                  activeProject
                    ? 'border-accent-200 bg-accent-50/60 text-accent-800 hover:border-accent-300'
                    : 'border-dashed border-ink-300 bg-white/80 text-ink-500 hover:border-accent-300 hover:text-accent-800',
                )}
                // On a global page (Artifacts/Templates/Credentials/…), activeProject can still be
                // set from earlier — the workspace was never closed, just not part of this URL.
                // Say so explicitly instead of the generic "Open workspace", which reads as
                // "nothing is open" and made the project feel silently lost.
                title={activeProject ? `${activeProject} is still open — return to it` : 'Open a workspace'}
                onClick={() => {
                  if (activeProject) {
                    if (confirmNavigation()) openProject(activeProject)
                  } else go('projects')
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
            {shownLastRunId && (
              <LastRunMenu
                runId={shownLastRunId}
                compact={compactHeader}
                runName={lastRunName}
                showCompare
                outcome={isRunning ? 'running' : effectiveOutcome}
                outcomeLabel={lastRunStatusLabel}
                onOpenRun={guarded(() =>
                  openRun(shownLastRunId, activeProject ? { project: activeProject } : undefined),
                )}
                onOpenTrace={guarded(() =>
                  openTrace({ runId: shownLastRunId, project: activeProject || undefined }),
                )}
                onOpenArtifacts={guarded(() =>
                  openArtifacts({ runId: shownLastRunId, project: activeProject || undefined }),
                )}
                onOpenCompare={guarded(() => openExperiments({ runIds: [shownLastRunId] }))}
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
            <NotificationBell />
            <button
              type="button"
              className="btn-icon"
              onClick={openSettings}
              aria-label="Settings"
              title={
                me && me.actor
                  ? `Settings · signed in as ${me.actor}${me.actorVerified ? ' (verified)' : ' (not verified)'}`
                  : 'Settings'
              }
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

        <div className="relative flex min-h-0 flex-1 overflow-hidden" data-sidebar-mode={sidebarMode} data-shell-noscroll>
          {navDrawerOpen && sidebarMode !== 'full' ? (
            <>
              <button
                type="button"
                className="absolute inset-0 z-20 cursor-default bg-ink-950/30"
                aria-label="Close navigation"
                onClick={() => setNavDrawerOpen(false)}
              />
              {renderNavAside(true)}
            </>
          ) : null}
          {sidebarMode === 'full' ? (
            <SplitPane
              className="h-full min-h-0 w-full flex-1"
              storageKey={LAYOUT_KEYS.nav}
              defaultSize={216}
              minSize={168}
              maxSize={300}
              paneOverflow="hidden"
            >
              {[renderNavAside(false), mainContent]}
            </SplitPane>
          ) : (
            <>
              {sidebarMode === 'rail' ? navRail : null}
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
              {me ? (
                <div className="mb-3 flex flex-wrap items-center gap-1.5 rounded-lg bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
                  <span>Signed in as</span>
                  <ActorName actor={me.actor} verified={me.actorVerified} claimed={me.claimedActor} bold className="text-ink-900" />
                  {!me.actorVerified ? (
                    <span className="text-ink-400" title="Your administrator can give you a named token (GRAPHYN_API_TOKENS)">
                      · not verified
                    </span>
                  ) : null}
                </div>
              ) : null}
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
                Paste the same token as GRAPHYN_API_TOKEN on the server. It stays in this browser
                only.
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
