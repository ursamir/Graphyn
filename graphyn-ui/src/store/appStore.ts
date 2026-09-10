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

interface Toast {
  id: string
  message: string
  tone: ToastTone
}

interface AppState {
  view: AppView
  setView: (view: AppView) => void
  focusRunId: string | null
  focusArtifactId: string | null
  openRun: (id: string) => void
  openTrace: (opts: { artifactId?: string; runId?: string }) => void
  openArtifacts: (opts?: { runId?: string; artifactId?: string }) => void
  openExperiments: (opts?: { runIds?: string[] }) => void
  openProposals: (opts?: { id?: string }) => void
  openEdge: (opts?: { project?: string; version?: string }) => void
  openData: (opts?: {
    mode?: 'inputs' | 'outputs' | 'ingest' | 'merge'
    project?: string
    version?: string
    label?: string
  }) => void
  openProjects: (opts?: { project?: string; tab?: string }) => void
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
  toasts: Toast[]
  pushToast: (message: string, tone?: ToastTone) => void
  dismissToast: (id: string) => void
  bootError: string | null
  bootStatus: number | null
  setBootError: (message: string | null, status?: number | null) => void
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


/** replaceState does not fire hashchange — notify mounted views to re-parse query. */
function replaceHash(hash: string) {
  window.history.replaceState(null, '', hash)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export const useAppStore = create<AppState>((set, get) => ({
  view: 'builder',
  setView: (view) => set({ view }),
  focusRunId: null,
  focusArtifactId: null,
  openRun: (id) => {
    replaceHash(`#/runs/${id}`)
    set({ view: 'runs', focusRunId: id, lastRunId: id })
  },
  openTrace: ({ artifactId, runId }) => {
    const params = new URLSearchParams()
    if (artifactId?.trim()) params.set('artifact_id', artifactId.trim())
    if (runId?.trim()) params.set('run_id', runId.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/trace?${qs}` : '#/trace')
    set({ view: 'trace' })
  },
  openArtifacts: ({ runId, artifactId } = {}) => {
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
  openEdge: ({ project, version } = {}) => {
    const params = new URLSearchParams()
    if (project?.trim()) params.set('project', project.trim())
    if (version?.trim()) params.set('version', version.trim())
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
    if (project?.trim()) params.set('project', project.trim())
    if (tab?.trim()) params.set('tab', tab.trim())
    const qs = params.toString()
    replaceHash(qs ? `#/projects?${qs}` : '#/projects')
    set({ view: 'projects' })
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
  toasts: [],
  pushToast: (message, tone = 'info') =>
    set((s) => ({
      toasts: [...s.toasts, { id: crypto.randomUUID(), message, tone }].slice(-5),
    })),
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  bootError: null,
  bootStatus: null,
  setBootError: (bootError, bootStatus = null) => set({ bootError, bootStatus: bootStatus ?? null }),
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
