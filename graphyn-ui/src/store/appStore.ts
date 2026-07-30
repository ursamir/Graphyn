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
  openRun: (id: string) => void
  catalog: NodeCatalogEntry[]
  setCatalog: (catalog: NodeCatalogEntry[]) => void
  refreshCatalog: (() => Promise<void>) | null
  setRefreshCatalog: (fn: () => Promise<void>) => void
  seed: number
  setSeed: (seed: number) => void
  logs: Array<{ message: string; level: string; ts: string }>
  addLog: (message: string, level?: string) => void
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
  getCanvasGraph: (() => unknown) | null
  setGetCanvasGraph: (fn: (() => unknown) | null) => void
  /** Graph waiting to paint once Builder mounts (Templates → Builder handoff). */
  pendingGraph: GraphIR | null
  loadGraphIntoBuilder: (graph: GraphIR) => void
  consumePendingGraph: () => GraphIR | null
}

export const useAppStore = create<AppState>((set, get) => ({
  view: 'builder',
  setView: (view) => set({ view }),
  focusRunId: null,
  openRun: (id) => {
    window.history.replaceState(null, '', `#/runs/${id}`)
    set({ view: 'runs', focusRunId: id, lastRunId: id })
  },
  catalog: [],
  setCatalog: (catalog) => set({ catalog }),
  refreshCatalog: null,
  setRefreshCatalog: (fn) => set({ refreshCatalog: fn }),
  seed: 42,
  setSeed: (seed) => set({ seed }),
  logs: [],
  addLog: (message, level = 'info') =>
    set((s) => ({
      logs: [...s.logs, { message, level, ts: new Date().toISOString() }].slice(-500),
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
}))
