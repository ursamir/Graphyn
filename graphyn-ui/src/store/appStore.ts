import { create } from 'zustand'
import type { GraphIR, NodeCatalogEntry } from '../types/graph'
import { paths } from '../routes/paths'
import { navigatePath, parsePathname } from '../routes/parsePath'
import { resolveArtifactRunId } from '../lib/resolveArtifact'
import { humanizeErrorText } from '../lib/errorText'
import { isWorkspaceKnownValid } from '../lib/workspaceValidity'

export type AppView =
  | 'builder'
  | 'runs'
  | 'plugins'
  | 'templates'
  | 'data'
  | 'projects'
  | 'system'
  | 'credentials'
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

/**
 * Persist the active workspace. Only ids App has validated against the API
 * (`lib/workspaceValidity`) are written — `/workspaces/does-not-exist` must
 * never become the remembered workspace. App calls `commitActiveProject` once
 * validation succeeds for an id that was set before it was known.
 */
function persistActiveProject(name: string | null) {
  try {
    if (name && name.trim()) {
      if (isWorkspaceKnownValid(name)) localStorage.setItem(ACTIVE_PROJECT_KEY, name.trim())
    } else localStorage.removeItem(ACTIVE_PROJECT_KEY)
  } catch {
    /* ignore quota / private mode */
  }
}

/** Drop the remembered workspace (it no longer exists and there is no valid fallback). */
export function forgetPersistedActiveProject() {
  persistActiveProject(null)
}

/** Write `name` as the remembered workspace if it is (still) the active one and validated. */
export function commitActiveProject(name: string) {
  if (useAppStore.getState().activeProject === name) persistActiveProject(name)
}

/** Detail panel on the Run page (Prefect-style tabs on one surface). */
export type FocusRunPanel = 'logs' | 'debug' | 'checkpoints' | 'artifacts' | 'lineage'

/** Top-level mode on the Run page — History vs Compare (W&B/MLflow pattern). */
/** `live` kept for older callers; App maps /runs/live → history + ?status=active. */
export type FocusRunsTab = 'history' | 'compare' | 'live'

interface AppState {
  view: AppView
  setView: (view: AppView) => void
  focusRunId: string | null
  /** Consumed once by RunsView when opening a run into a specific panel. */
  focusRunPanel: FocusRunPanel | null
  clearFocusRunPanel: () => void
  /** Consumed / owned by RunsView for History vs Compare. */
  focusRunsTab: FocusRunsTab
  setFocusRunsTab: (tab: FocusRunsTab) => void
  openRun: (id: string, opts?: { project?: string; panel?: FocusRunPanel }) => void
  /** Prefer Runs → Lineage. Artifact-id-only resolves via GET /artifacts/{id}. */
  openTrace: (opts: { artifactId?: string; runId?: string; project?: string }) => void
  /** Prefer Runs → Run outputs. Artifact-id-only resolves via GET /artifacts/{id}. */
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
  /** Run id `runOutcome` describes (the lastRunId when it was set). The header
   *  ignores `runOutcome` for any other run — openRun() moves lastRunId without
   *  touching the outcome, which used to paint one run's dot on another. */
  runOutcomeRunId: string | null
  toasts: Toast[]
  pushToast: (message: string, tone?: ToastTone, opts?: PushToastOpts) => void
  dismissToast: (id: string) => void
  dismissAllToasts: () => void
  /** Clear active workspace and leave /workspaces/:id for the Workspaces picker (path-era). */
  closeProject: () => void
  /** Bumped when workspace is cleared — DataView resets selection / path scope. */
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
  /**
   * Graph waiting for the Editor. `fromRunId` = the graph is that run's
   * recorded graph (Editor compares later edits against it); `snapshot` =
   * opened as the run's exact, read-only snapshot (Save becomes Save as new).
   */
  loadGraphIntoBuilder: (graph: GraphIR, opts?: { fromRunId?: string; snapshot?: boolean }) => void
  consumePendingGraph: () => GraphIR | null
  /** Run the Editor's canvas was opened from (set with the pending graph). */
  editorRunContext: { runId: string; snapshot: boolean } | null
  setEditorRunContext: (ctx: { runId: string; snapshot: boolean } | null) => void
  /** Active dataset project(+version) linked into Editor (Projects → Open in Editor). */
  builderDataset: { project: string; version?: string } | null
  setBuilderDataset: (ctx: { project: string; version?: string } | null) => void
}


/** Close workspace: leave /workspaces/:id for picker or library. */
function stripProjectFromWorkspacePath() {
  const { pathname } = window.location
  if (pathname.startsWith('/workspaces/')) {
    navigatePath(paths.workspaces(), true)
    return
  }
  if (pathname.startsWith('/library/models') || pathname.startsWith('/deploy/ship')) {
    navigatePath(paths.workspaces(), true)
  }
}

function panelPathSegment(
  panel?: 'logs' | 'artifacts' | 'lineage' | 'debug' | 'checkpoints' | null,
): 'logs' | 'outputs' | 'lineage' | 'details' | 'checkpoints' | undefined {
  if (!panel) return undefined
  if (panel === 'artifacts') return 'outputs'
  // Legacy Summary (`debug`) → Overview lineage path.
  if (panel === 'debug') return 'lineage'
  return panel
}

/** Last workspace the user had open (cleared by Switch / the Workspaces picker). */
export function readPersistedActiveProject(): string | null {
  try {
    return localStorage.getItem(ACTIVE_PROJECT_KEY)?.trim() || null
  } catch {
    return null
  }
}

/**
 * Workspace id from the address bar. On a *global* route (Templates, Library,
 * Admin, Agent inbox, …) the URL carries no workspace, so a cold load of
 * `/templates` used to show "No workspace open" even though one was open a
 * moment ago. There we resume the last active workspace from localStorage;
 * App validates it against `GET /projects` on boot and clears it if it was
 * deleted. `/workspaces` (the picker) and `/` never resume.
 */
function readInitialProject(): string | null {
  if (typeof window === 'undefined') return null
  const { pathname, search } = window.location
  const fromUrl = parsePathname(pathname, search).workspaceId
  if (fromUrl) return fromUrl
  const first = pathname.split('/').filter(Boolean)[0]
  if (!first || first === 'workspaces' || first === 'login') return null
  return readPersistedActiveProject()
}

function readInitialView(): AppView {
  if (typeof window === 'undefined') return 'projects'
  if (window.location.pathname && window.location.pathname !== '/') {
    return parsePathname(window.location.pathname, window.location.search).view
  }
  return 'projects'
}

function landRunPanel(
  get: () => AppState,
  set: (partial: Partial<AppState>) => void,
  runId: string,
  panel: 'lineage' | 'artifacts',
) {
  const W = get().activeProject || ''
  const seg = panel === 'artifacts' ? 'outputs' : 'lineage'
  if (W) navigatePath(paths.runPanel(W, runId, seg))
  else navigatePath(paths.workspaces())
  set({
    view: 'runs',
    focusRunId: runId,
    lastRunId: runId,
    lastRunProject: get().activeProject,
    focusRunsTab: 'history',
    focusRunPanel: panel,
  })
}

function landRunsList(get: () => AppState, set: (partial: Partial<AppState>) => void) {
  const W = get().activeProject || ''
  if (W) navigatePath(paths.runs(W))
  else navigatePath(paths.workspaces())
  set({ view: W ? 'runs' : 'projects', focusRunsTab: 'history' })
}

export const useAppStore = create<AppState>((set, get) => ({
  view: readInitialView(),
  setView: (view) => set({ view }),
  focusRunId: null,
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
    // Run id wins even when an artifact id is also present (old Library path).
    if (rid) {
      landRunPanel(get, set, rid, 'lineage')
      return
    }
    if (aid) {
      void (async () => {
        const resolved = await resolveArtifactRunId(aid)
        if (resolved) {
          landRunPanel(get, set, resolved, 'lineage')
          return
        }
        get().pushToast('Artifact not found — open a run’s Lineage instead', 'error')
        landRunsList(get, set)
      })()
      return
    }
    landRunsList(get, set)
  },
  openArtifacts: ({ runId, artifactId, project } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const aid = artifactId?.trim() || ''
    const rid = runId?.trim() || ''
    if (rid) {
      landRunPanel(get, set, rid, 'artifacts')
      return
    }
    if (aid) {
      void (async () => {
        const resolved = await resolveArtifactRunId(aid)
        if (resolved) {
          landRunPanel(get, set, resolved, 'artifacts')
          return
        }
        get().pushToast('Artifact not found — use Runs → Run outputs', 'error')
        landRunsList(get, set)
      })()
      return
    }
    landRunsList(get, set)
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
  openEdge: ({ project, version, runId } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const W = proj || get().activeProject || ''
    if (!W) {
      navigatePath(paths.workspaces())
      set({ view: 'projects' })
      return
    }
    const base = paths.ship(W)
    // version/runId were accepted here but silently dropped — callers like
    // ProjectsView's "Use in Ship" passed a run_id that never made it into
    // the URL, so the Ship wizard always landed on "project + source run
    // required" even though the caller had a specific run in hand.
    const qs = new URLSearchParams()
    if (version?.trim()) qs.set('version', version.trim())
    if (runId?.trim()) qs.set('run_id', runId.trim())
    const query = qs.toString()
    navigatePath(query ? `${base}?${query}` : base)
    set({ view: 'edge' })
  },
  openData: ({ mode, project, version, label } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const W = proj || get().activeProject || ''
    set({ view: 'data' })
    // No workspace → shared library catalog (secondary CTA), not Models/Ship globals.
    const base = W ? paths.datasets(W) : paths.libraryDatasets()
    const qs = new URLSearchParams()
    if (mode) qs.set('mode', mode)
    if (version?.trim()) qs.set('version', version.trim())
    if (label?.trim()) qs.set('label', label.trim())
    if (mode === 'ingest' || mode === 'merge') qs.set('manage', '1')
    const q = qs.toString()
    navigatePath(q ? `${base}?${q}` : base)
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
  activeProject: readInitialProject(),
  setActiveProject: (name) => {
    const next = name?.trim() || null
    persistActiveProject(next)
    if (next === null) {
      set((s) => ({
        activeProject: null,
        dataUnscopeEpoch: s.dataUnscopeEpoch + 1,
        builderDataset: null,
        focusRunId: null,
        focusRunPanel: null,
        lastRunId: null,
        lastRunProject: null,
        runOutcome: 'idle' as const,
        statusMessage: null,
        isRunning: false,
      }))
      stripProjectFromWorkspacePath()
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
      focusRunPanel: null,
      lastRunId: null,
      lastRunProject: null,
      runOutcome: 'idle' as const,
      statusMessage: null,
      isRunning: false,
    }))
    stripProjectFromWorkspacePath()
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
  setLastRunId: (lastRunId) =>
    set((s) => ({
      lastRunId,
      lastRunProject: lastRunId ? s.activeProject : null,
      // Editor sets 'running' before the run id arrives — carry it onto the new id.
      runOutcomeRunId: s.isRunning || s.runOutcome === 'running' ? lastRunId : s.runOutcomeRunId,
    })),
  statusMessage: null,
  setStatusMessage: (statusMessage) => set({ statusMessage }),
  runOutcome: 'idle',
  runOutcomeRunId: null,
  setRunOutcome: (runOutcome) => set((s) => ({ runOutcome, runOutcomeRunId: s.lastRunId })),
  toasts: [],
  pushToast: (message, tone = 'info', opts) => {
    const id = crypto.randomUUID()
    set((s) => ({
      toasts: [
        ...s.toasts,
        {
          id,
          // Never show a raw JSON error body / bare error code in an error toast.
          message: tone === 'error' || message.trim().startsWith('{') ? humanizeErrorText(message) : message,
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
  loadGraphIntoBuilder: (graph, opts) => {
    navigatePath(paths.editor(get().activeProject || 'workspace'), true)
    set({
      pendingGraph: graph,
      view: 'builder',
      editorRunContext: opts?.fromRunId ? { runId: opts.fromRunId, snapshot: Boolean(opts.snapshot) } : null,
    })
  },
  editorRunContext: null,
  setEditorRunContext: (editorRunContext) => set({ editorRunContext }),
  consumePendingGraph: () => {
    const g = get().pendingGraph
    if (g) set({ pendingGraph: null })
    return g
  },
  builderDataset: null,
  setBuilderDataset: (builderDataset) => set({ builderDataset }),
}))
