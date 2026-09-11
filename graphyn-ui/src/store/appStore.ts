import { create } from 'zustand'
import type { GraphIR, NodeCatalogEntry } from '../types/graph'

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
  | 'trace'
  | 'edge'
  | 'experiments'
  | 'proposals'

export type ToastTone = 'info' | 'success' | 'error'

export type RunOutcome = 'idle' | 'running' | 'succeeded' | 'failed' | 'cancelled'

interface Toast {
  id: string
  message: string
  tone: ToastTone
  createdAt: number
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

interface AppState {
  view: AppView
  setView: (view: AppView) => void
  focusRunId: string | null
  focusArtifactId: string | null
  openRun: (id: string, opts?: { project?: string }) => void
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
  statusMessage: string | null
  setStatusMessage: (msg: string | null) => void
  runOutcome: RunOutcome
  setRunOutcome: (outcome: RunOutcome) => void
  toasts: Toast[]
  pushToast: (message: string, tone?: ToastTone) => void
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
  /** Active dataset project(+version) linked into Builder (Projects → Open in Builder). */
  builderDataset: { project: string; version?: string } | null
  setBuilderDataset: (ctx: { project: string; version?: string } | null) => void
}


/** Strip ?project= from Data/Projects hashes so global library is not left scoped. */
function stripProjectFromWorkspaceHash() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const pathOnly = raw.split('?')[0] || ''
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  if (!params.has('project')) return
  params.delete('project')
  if (
    pathOnly === 'data' ||
    pathOnly.startsWith('data/') ||
    pathOnly === 'projects' ||
    pathOnly.startsWith('projects/')
  ) {
    const qs = params.toString()
    replaceHash(qs ? `#/${pathOnly}?${qs}` : `#/${pathOnly}`)
  }
}

/** replaceState does not fire hashchange — notify mounted views to re-parse query. */
function replaceHash(hash: string) {
  window.history.replaceState(null, '', hash)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export const useAppStore = create<AppState>((set, get) => ({
  // Cold start → Projects (workspace picker). Builder/Run hard-gate without a project.
  view: readStoredActiveProject() ? 'builder' : 'projects',
  setView: (view) => set({ view }),
  focusRunId: null,
  focusArtifactId: null,
  openRun: (id, opts) => {
    const proj = opts?.project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    replaceHash(`#/runs/${id}`)
    set({ view: 'runs', focusRunId: id, lastRunId: id })
  },
  openTrace: ({ artifactId, runId, project }) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const params = new URLSearchParams()
    if (artifactId?.trim()) params.set('artifact_id', artifactId.trim())
    if (runId?.trim()) params.set('run_id', runId.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/trace?${qs}` : '#/trace')
    set({ view: 'trace' })
  },
  openArtifacts: ({ runId, artifactId, project } = {}) => {
    const proj = project?.trim() || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const params = new URLSearchParams()
    if (runId?.trim()) params.set('run_id', runId.trim())
    const aid = artifactId?.trim() || ''
    if (aid) params.set('artifact_id', aid)
    const qs = params.toString()
    replaceHash(qs ? `#/artifacts?${qs}` : '#/artifacts')
    set({ view: 'artifacts', focusArtifactId: aid || null })
  },
  openExperiments: ({ runIds } = {}) => {
    const params = new URLSearchParams()
    const ids = (runIds ?? []).map((id) => id.trim()).filter(Boolean)
    if (ids.length === 1) params.set('run_id', ids[0])
    else if (ids.length > 1) params.set('run_id', ids.join(','))
    const qs = params.toString()
    replaceHash(qs ? `#/experiments?${qs}` : '#/experiments')
    set({ view: 'experiments' })
  },
  openProposals: ({ id } = {}) => {
    const params = new URLSearchParams()
    if (id?.trim()) params.set('id', id.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/proposals?${qs}` : '#/proposals')
    set({ view: 'proposals' })
  },
  openEdge: ({ project, version, runId } = {}) => {
    const params = new URLSearchParams()
    if (project?.trim()) params.set('project', project.trim())
    if (version?.trim()) params.set('version', version.trim())
    if (runId?.trim()) params.set('run_id', runId.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/edge?${qs}` : '#/edge')
    set({ view: 'edge' })
  },
  openData: ({ mode, project, version, label } = {}) => {
    const params = new URLSearchParams()
    if (mode) params.set('mode', mode)
    if (project?.trim()) params.set('project', project.trim())
    if (version?.trim()) params.set('version', version.trim())
    if (label?.trim()) params.set('label', label.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/data?${qs}` : '#/data')
    set({ view: 'data' })
  },
  openProjects: ({ project, tab } = {}) => {
    const params = new URLSearchParams()
    const name = project?.trim()
    if (name) {
      params.set('project', name)
      persistActiveProject(name)
      set({ activeProject: name })
    }
    if (tab?.trim()) params.set('tab', tab.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/projects?${qs}` : '#/projects')
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
  setLastRunId: (lastRunId) => set({ lastRunId }),
  statusMessage: null,
  setStatusMessage: (statusMessage) => set({ statusMessage }),
  runOutcome: 'idle',
  setRunOutcome: (runOutcome) => set({ runOutcome }),
  toasts: [],
  pushToast: (message, tone = 'info') => {
    const id = crypto.randomUUID()
    set((s) => ({
      toasts: [...s.toasts, { id, message, tone, createdAt: Date.now() }].slice(-MAX_TOASTS),
    }))
    // Drop oldest timers when capped
    const remaining = new Set(get().toasts.map((t) => t.id))
    for (const tid of [...toastTimers.keys()]) {
      if (!remaining.has(tid)) clearToastTimer(tid)
    }
    clearToastTimer(id)
    const ttl = TOAST_TTL_MS[tone] ?? 3500
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
    window.history.replaceState(null, '', '#/builder')
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
