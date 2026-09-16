import { create } from 'zustand'
import type { GraphIR, NodeCatalogEntry } from '../types/graph'
import { paths } from '../routes/paths'
import { navigatePath, parsePathname } from '../routes/parsePath'

export type AppView =
  | 'builder'
  | 'runs'
  | 'artifacts'
  | 'plugins'
  | 'templates'
  | 'data'
  | 'projects'
  | 'system'
  | 'secrets'
  | 'workers'
  | 'edge'
  | 'experiments'
  | 'proposals'
  | 'models'
  | 'access'
  | 'devices'

export type ToastTone = 'info' | 'success' | 'error'

export type RunOutcome = 'idle' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Toast {
  id: string
  message: string
  tone: ToastTone
  createdAt: number
  actionLabel?: string
  onAction?: () => void
}

export type PushToastOpts = {
  actionLabel?: string
  onAction?: () => void
  /** Override auto-dismiss ms (default by tone). */
  ttlMs?: number
}

const MAX_TOASTS = 3
const TOAST_TTL_MS: Record<ToastTone, number> = {
  info: 3500,
  success: 3000,
  error: 6000,
}

const toastTimers = new Map<string, ReturnType<typeof setTimeout>>()

function clearToastTimer(id: string) {
  const t = toastTimers.get(id)
  if (t) {
    clearTimeout(t)
    toastTimers.delete(id)
  }
}

const ACTIVE_PROJECT_KEY = 'graphyn.activeProject'

function readStoredActiveProject(): string | null {
  try {
    const v = localStorage.getItem(ACTIVE_PROJECT_KEY)
    const t = (v || '').trim()
    return t || null
  } catch {
    return null
  }
}

function persistActiveProject(name: string | null) {
  try {
    if (name && name.trim()) localStorage.setItem(ACTIVE_PROJECT_KEY, name.trim())
    else localStorage.removeItem(ACTIVE_PROJECT_KEY)
  } catch {
    /* ignore quota / private mode */
  }
}

/** Detail panel on the Run page (Prefect-style tabs on one surface). */
export type FocusRunPanel = 'logs' | 'debug' | 'checkpoints' | 'artifacts' | 'lineage'

/** Top-level mode on the Run page — History vs Compare (W&B/MLflow pattern). */
export type FocusRunsTab = 'history' | 'compare' | 'live'

interface AppState {
  view: AppView
  setView: (view: AppView) => void
  focusRunId: string | null
  focusArtifactId: string | null
  /** Consumed once by RunsView when opening a run into a specific panel. */
  focusRunPanel: FocusRunPanel | null
  clearFocusRunPanel: () => void
  /** Consumed / owned by RunsView for History vs Compare. */
  focusRunsTab: FocusRunsTab
  setFocusRunsTab: (tab: FocusRunsTab) => void
  openRun: (id: string, opts?: { project?: string; panel?: FocusRunPanel }) => void
  openTrace: (opts: { artifactId?: string; runId?: string; project?: string }) => void
  openArtifacts: (opts?: { runId?: string; artifactId?: string; project?: string }) => void
  openExperiments: (opts?: { runIds?: string[] }) => void
  openProposals: (opts?: { id?: string }) => void
  openEdge: (opts?: { project?: string; version?: string; runId?: string }) => void
  openData: (opts?: {
    mode?: 'inputs' | 'outputs' | 'ingest' | 'merge'
    project?: string
    version?: string
    label?: string
  }) => void
  openProjects: (opts?: { project?: string; tab?: string }) => void
  /** Phase-1 project-first workspace context (Decision B — same Project type). */
  activeProject: string | null
  setActiveProject: (name: string | null) => void
  openProject: (name: string, opts?: { tab?: string }) => void
  pendingProposalCount: number
  setPendingProposalCount: (n: number) => void
  catalog: NodeCatalogEntry[]
  setCatalog: (catalog: NodeCatalogEntry[]) => void
  refreshCatalog: (() => Promise<void>) | null
  setRefreshCatalog: (fn: () => Promise<void>) => void
  seed: number
  setSeed: (seed: number) => void
  logs: Array<{ message: string; level: string; ts: string; raw?: string }>
  addLog: (message: string, level?: string, raw?: string) => void
  clearLogs: () => void
  isRunning: boolean
  setIsRunning: (v: boolean) => void
  lastRunId: string | null
  setLastRunId: (id: string | null) => void
  /** Project that owns lastRunId / runOutcome (header chip scoping). */
  lastRunProject: string | null
  statusMessage: string | null
  setStatusMessage: (msg: string | null) => void
  runOutcome: RunOutcome
  setRunOutcome: (outcome: RunOutcome) => void
  toasts: Toast[]
  pushToast: (message: string, tone?: ToastTone, opts?: PushToastOpts) => void
  dismissToast: (id: string) => void
  dismissAllToasts: () => void
  /** Clear active project and strip ?project= from Data/Projects hash so global library is unscoped. */
  closeProject: () => void
  /** Bumped when workspace project is cleared — DataView resets selection / hash scope. */
  dataUnscopeEpoch: number
  bootError: string | null
  bootStatus: number | null
  setBootError: (message: string | null, status?: number | null) => void
  /** Mode A local vs Mode B distributed — from GET /system/readiness. */
  backendMode: 'local' | 'distributed' | null
  setBackendMode: (mode: 'local' | 'distributed' | null) => void
  settingsOpen: boolean
  setSettingsOpen: (open: boolean) => void
  getCanvasGraph: (() => unknown) | null
  setGetCanvasGraph: (fn: (() => unknown) | null) => void
  /** Graph waiting to paint once Builder mounts (Templates → Builder handoff). */
  pendingGraph: GraphIR | null
  loadGraphIntoBuilder: (graph: GraphIR) => void
  consumePendingGraph: () => GraphIR | null
  /** Active dataset project(+version) linked into Editor (Projects → Open in Editor). */
  builderDataset: { project: string; version?: string } | null
  setBuilderDataset: (ctx: { project: string; version?: string } | null) => void
}


/** Close workspace: leave /workspaces/:id for picker or library. */
function stripProjectFromWorkspaceHash() {
  const { pathname } = window.location
  if (pathname.startsWith('/workspaces/')) {
    navigatePath(paths.workspaces(), true)
    return
  }
  if (pathname.startsWith('/library/datasets')) {
    navigatePath(paths.libraryDatasets(), true)
  }
}

function panelPathSegment(
  panel?: 'logs' | 'artifacts' | 'lineage' | 'debug' | 'checkpoints' | null,
): 'logs' | 'outputs' | 'lineage' | 'details' | 'checkpoints' | undefined {
  if (!panel) return undefined
  if (panel === 'artifacts') return 'outputs'
  if (panel === 'debug') return 'details'
  return panel
}

function readInitialView(): AppView {
  if (typeof window === 'undefined') return 'projects'
  if (window.location.pathname && window.location.pathname !== '/') {
    return parsePathname(window.location.pathname, window.location.search).view
  }
  return readStoredActiveProject() ? 'builder' : 'projects'
}

export const useAppStore = create<AppState>((set, get) => ({
  view: readInitialView(),
  setView: (view) => set({ view }),
  focusRunId: null,
  focusArtifactId: null,
  focusRunPanel: null,
  clearFocusRunPanel: () => set({ focusRunPanel: null }),
  focusRunsTab: 'history',
  setFocusRunsTab: (focusRunsTab) => set({ focusRunsTab }),
  openRun: (id, opts) => {
    const proj = opts?.project?.trim() || get().activeProject || ''
    if (opts?.project?.trim()) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const W = proj || get().activeProject || ''
    const seg = panelPathSegment(opts?.panel)
    if (W) navigatePath(seg ? paths.runPanel(W, id, seg) : paths.run(W, id))
    else navigatePath(paths.workspaces())
    set({
      view: 'runs',
      focusRunId: id,
      lastRunId: id,
      lastRunProject: proj || get().activeProject || null,
      focusRunsTab: 'history',
      focusRunPanel: opts?.panel ?? null,
    })
  },
  openTrace: ({ artifactId, runId, project }) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const aid = artifactId?.trim() || ''
    const rid = runId?.trim() || ''
    const W = get().activeProject || ''
    if (rid && !aid) {
      if (W) navigatePath(paths.runPanel(W, rid, 'lineage'))
      set({
        view: 'runs',
        focusRunId: rid,
        lastRunId: rid,
        lastRunProject: get().activeProject,
        focusRunsTab: 'history',
        focusRunPanel: 'lineage',
      })
      return
    }
    // No runId (or both runId+artifactId): land on Artifacts — Lineage for a
    // specific run always resolves via the branch above (Runs → lineage panel).
    navigatePath(paths.libraryArtifacts(aid ? { artifactId: aid } : undefined))
    set({ view: 'artifacts', focusArtifactId: aid || null })
  },
  openArtifacts: ({ runId, artifactId, project } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const aid = artifactId?.trim() || ''
    const rid = runId?.trim() || ''
    const W = get().activeProject || ''
    if (rid && !aid) {
      if (W) navigatePath(paths.runPanel(W, rid, 'outputs'))
      set({
        view: 'runs',
        focusRunId: rid,
        lastRunId: rid,
        lastRunProject: get().activeProject,
        focusRunsTab: 'history',
        focusRunPanel: 'artifacts',
      })
      return
    }
    navigatePath(paths.libraryArtifacts(aid ? { artifactId: aid } : undefined))
    set({ view: 'artifacts', focusArtifactId: aid || null })
  },
  openExperiments: ({ runIds } = {}) => {
    const W = get().activeProject || ''
    const ids = (runIds ?? []).map((id) => id.trim()).filter(Boolean)
    if (W) navigatePath(paths.runsCompare(W, ids.length ? ids : undefined))
    else navigatePath(paths.workspaces())
    set({ view: 'runs', focusRunsTab: 'compare' })
  },
  openProposals: ({ id } = {}) => {
    navigatePath(id?.trim() ? paths.proposal(id.trim()) : paths.agentInbox())
    set({ view: 'proposals' })
  },
  openEdge: ({ project } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const W = proj || get().activeProject || ''
    navigatePath(W ? paths.ship(W) : paths.deployShip())
    set({ view: 'edge' })
  },
  openData: ({ mode, project, version, label } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj, view: 'data' })
    } else {
      set({ view: 'data' })
    }
    const W = proj || get().activeProject || ''
    const base = W ? paths.datasets(W) : paths.libraryDatasets()
    const qs = new URLSearchParams()
    if (mode) qs.set('mode', mode)
    if (version?.trim()) qs.set('version', version.trim())
    if (label?.trim()) qs.set('label', label.trim())
    if (mode === 'ingest' || mode === 'merge') qs.set('manage', '1')
    const s = qs.toString()
    navigatePath(s ? `${base}?${s}` : base)
  },
  openProjects: ({ project } = {}) => {
    const name = project?.trim()
    if (name) {
      persistActiveProject(name)
      set({ activeProject: name })
      navigatePath(paths.workspace(name))
    } else {
      navigatePath(paths.workspaces())
    }
    set({ view: 'projects' })
  },
  activeProject: readStoredActiveProject(),
  setActiveProject: (name) => {
    const next = name?.trim() || null
    persistActiveProject(next)
    if (next === null) {
      set((s) => ({
        activeProject: null,
        dataUnscopeEpoch: s.dataUnscopeEpoch + 1,
        builderDataset: null,
        focusRunId: null,
        focusArtifactId: null,
        focusRunPanel: null,
        lastRunId: null,
        lastRunProject: null,
        runOutcome: 'idle' as const,
        statusMessage: null,
        isRunning: false,
      }))
      stripProjectFromWorkspaceHash()
    } else {
      set({ activeProject: next })
    }
  },
  dataUnscopeEpoch: 0,
  closeProject: () => {
    persistActiveProject(null)
    set((s) => ({
      activeProject: null,
      dataUnscopeEpoch: s.dataUnscopeEpoch + 1,
      builderDataset: null,
      focusRunId: null,
      focusArtifactId: null,
      focusRunPanel: null,
      lastRunId: null,
      lastRunProject: null,
      runOutcome: 'idle' as const,
      statusMessage: null,
      isRunning: false,
    }))
    stripProjectFromWorkspaceHash()
  },
  openProject: (name, opts) => {
    const n = name.trim()
    if (!n) return
    persistActiveProject(n)
    set({ activeProject: n })
    get().openProjects({ project: n, tab: opts?.tab })
  },
  pendingProposalCount: 0,
  setPendingProposalCount: (pendingProposalCount) => set({ pendingProposalCount }),
  catalog: [],
  setCatalog: (catalog) => set({ catalog }),
  refreshCatalog: null,
  setRefreshCatalog: (fn) => set({ refreshCatalog: fn }),
  seed: 42,
  setSeed: (seed) => set({ seed }),
  logs: [],
  addLog: (message, level = 'info', raw) =>
    set((s) => ({
      logs: [...s.logs, { message, level, ts: new Date().toISOString(), raw }].slice(-500),
    })),
  clearLogs: () => set({ logs: [] }),
  isRunning: false,
  setIsRunning: (isRunning) => set({ isRunning }),
  lastRunId: null,
  lastRunProject: null,
  setLastRunId: (lastRunId) => set({ lastRunId, lastRunProject: lastRunId ? get().activeProject : null }),
  statusMessage: null,
  setStatusMessage: (statusMessage) => set({ statusMessage }),
  runOutcome: 'idle',
  setRunOutcome: (runOutcome) => set({ runOutcome }),
  toasts: [],
  pushToast: (message, tone = 'info', opts) => {
    const id = crypto.randomUUID()
    set((s) => ({
      toasts: [
        ...s.toasts,
        {
          id,
          message,
          tone,
          createdAt: Date.now(),
          actionLabel: opts?.actionLabel,
          onAction: opts?.onAction,
        },
      ].slice(-MAX_TOASTS),
    }))
    // Drop oldest timers when capped
    const remaining = new Set(get().toasts.map((t) => t.id))
    for (const tid of [...toastTimers.keys()]) {
      if (!remaining.has(tid)) clearToastTimer(tid)
    }
    clearToastTimer(id)
    const ttl = opts?.ttlMs ?? (opts?.actionLabel ? 10000 : TOAST_TTL_MS[tone] ?? 3500)
    toastTimers.set(
      id,
      setTimeout(() => {
        toastTimers.delete(id)
        get().dismissToast(id)
      }, ttl),
    )
  },
  dismissToast: (id) => {
    clearToastTimer(id)
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
  },
  dismissAllToasts: () => {
    for (const id of [...toastTimers.keys()]) clearToastTimer(id)
    set({ toasts: [] })
  },
  bootError: null,
  bootStatus: null,
  setBootError: (bootError, bootStatus = null) => set({ bootError, bootStatus: bootStatus ?? null }),
  backendMode: null,
  setBackendMode: (backendMode) => set({ backendMode }),
  settingsOpen: false,
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  getCanvasGraph: null,
  setGetCanvasGraph: (fn) => set({ getCanvasGraph: fn }),
  pendingGraph: null,
  loadGraphIntoBuilder: (graph) => {
    navigatePath(paths.editor(get().activeProject || 'workspace'), true)
    set({ pendingGraph: graph, view: 'builder' })
  },
  consumePendingGraph: () => {
    const g = get().pendingGraph
    if (g) set({ pendingGraph: null })
    return g
  },
  builderDataset: null,
  setBuilderDataset: (builderDataset) => set({ builderDataset }),
}))
