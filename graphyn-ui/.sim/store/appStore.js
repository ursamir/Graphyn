"use strict";Object.defineProperty(exports, "__esModule", {value: true}); function _nullishCoalesce(lhs, rhsFn) { if (lhs != null) { return lhs; } else { return rhsFn(); } } function _optionalChain(ops) { let lastAccessLHS = undefined; let value = ops[0]; let i = 1; while (i < ops.length) { const op = ops[i]; const fn = ops[i + 1]; i += 2; if ((op === 'optionalAccess' || op === 'optionalCall') && value == null) { return undefined; } if (op === 'access' || op === 'optionalAccess') { lastAccessLHS = value; value = fn(value); } else if (op === 'call' || op === 'optionalCall') { value = fn((...args) => value.call(lastAccessLHS, ...args)); lastAccessLHS = undefined; } } return value; }var _zustand = require('zustand');

var _paths = require('../routes/paths');
var _parsePath = require('../routes/parsePath');








































const MAX_TOASTS = 3
const TOAST_TTL_MS = {
  info: 3500,
  success: 3000,
  error: 6000,
}

const toastTimers = new Map()

function clearToastTimer(id) {
  const t = toastTimers.get(id)
  if (t) {
    clearTimeout(t)
    toastTimers.delete(id)
  }
}

const ACTIVE_PROJECT_KEY = 'graphyn.activeProject'

function readStoredActiveProject() {
  try {
    const v = localStorage.getItem(ACTIVE_PROJECT_KEY)
    const t = (v || '').trim()
    return t || null
  } catch (e) {
    return null
  }
}

function persistActiveProject(name) {
  try {
    if (name && name.trim()) localStorage.setItem(ACTIVE_PROJECT_KEY, name.trim())
    else localStorage.removeItem(ACTIVE_PROJECT_KEY)
  } catch (e2) {
    /* ignore quota / private mode */
  }
}

/** Detail panel on the Run page (Prefect-style tabs on one surface). */


















































































/** Close workspace: leave /workspaces/:id for picker or library. */
function stripProjectFromWorkspaceHash() {
  const { pathname } = window.location
  if (pathname.startsWith('/workspaces/')) {
    _parsePath.navigatePath.call(void 0, _paths.paths.workspaces(), true)
    return
  }
  if (pathname.startsWith('/library/datasets')) {
    _parsePath.navigatePath.call(void 0, _paths.paths.libraryDatasets(), true)
  }
}

function panelPathSegment(
  panel,
) {
  if (!panel) return undefined
  if (panel === 'artifacts') return 'outputs'
  if (panel === 'debug') return 'details'
  return panel
}

function readInitialView() {
  if (typeof window === 'undefined') return 'projects'
  if (window.location.pathname && window.location.pathname !== '/') {
    return _parsePath.parsePathname.call(void 0, window.location.pathname, window.location.search).view
  }
  return readStoredActiveProject() ? 'builder' : 'projects'
}

 const useAppStore = _zustand.create((set, get) => ({
  view: readInitialView(),
  setView: (view) => set({ view }),
  focusRunId: null,
  focusArtifactId: null,
  focusRunPanel: null,
  clearFocusRunPanel: () => set({ focusRunPanel: null }),
  focusRunsTab: 'history',
  setFocusRunsTab: (focusRunsTab) => set({ focusRunsTab }),
  openRun: (id, opts) => {
    const proj = _optionalChain([opts, 'optionalAccess', _ => _.project, 'optionalAccess', _2 => _2.trim, 'call', _3 => _3()]) || get().activeProject || ''
    if (_optionalChain([opts, 'optionalAccess', _4 => _4.project, 'optionalAccess', _5 => _5.trim, 'call', _6 => _6()])) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const W = proj || get().activeProject || ''
    const seg = panelPathSegment(_optionalChain([opts, 'optionalAccess', _7 => _7.panel]))
    if (W) _parsePath.navigatePath.call(void 0, seg ? _paths.paths.runPanel(W, id, seg) : _paths.paths.run(W, id))
    else _parsePath.navigatePath.call(void 0, _paths.paths.workspaces())
    set({
      view: 'runs',
      focusRunId: id,
      lastRunId: id,
      lastRunProject: proj || get().activeProject || null,
      focusRunsTab: 'history',
      focusRunPanel: _nullishCoalesce(_optionalChain([opts, 'optionalAccess', _8 => _8.panel]), () => ( null)),
    })
  },
  openTrace: ({ artifactId, runId, project }) => {
    const proj = _optionalChain([project, 'optionalAccess', _9 => _9.trim, 'call', _10 => _10()]) || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const aid = _optionalChain([artifactId, 'optionalAccess', _11 => _11.trim, 'call', _12 => _12()]) || ''
    const rid = _optionalChain([runId, 'optionalAccess', _13 => _13.trim, 'call', _14 => _14()]) || ''
    const W = get().activeProject || ''
    if (rid && !aid) {
      if (W) _parsePath.navigatePath.call(void 0, _paths.paths.runPanel(W, rid, 'lineage'))
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
    _parsePath.navigatePath.call(void 0, _paths.paths.libraryArtifacts(aid ? { artifactId: aid } : undefined))
    set({ view: aid ? 'artifacts' : 'trace', focusArtifactId: aid || null })
  },
  openArtifacts: ({ runId, artifactId, project } = {}) => {
    const proj = _optionalChain([project, 'optionalAccess', _15 => _15.trim, 'call', _16 => _16()]) || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const aid = _optionalChain([artifactId, 'optionalAccess', _17 => _17.trim, 'call', _18 => _18()]) || ''
    const rid = _optionalChain([runId, 'optionalAccess', _19 => _19.trim, 'call', _20 => _20()]) || ''
    const W = get().activeProject || ''
    if (rid && !aid) {
      if (W) _parsePath.navigatePath.call(void 0, _paths.paths.runPanel(W, rid, 'outputs'))
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
    _parsePath.navigatePath.call(void 0, _paths.paths.libraryArtifacts(aid ? { artifactId: aid } : undefined))
    set({ view: 'artifacts', focusArtifactId: aid || null })
  },
  openExperiments: ({ runIds } = {}) => {
    const W = get().activeProject || ''
    const ids = (_nullishCoalesce(runIds, () => ( []))).map((id) => id.trim()).filter(Boolean)
    if (W) _parsePath.navigatePath.call(void 0, _paths.paths.runsCompare(W, ids.length ? ids : undefined))
    else _parsePath.navigatePath.call(void 0, _paths.paths.workspaces())
    set({ view: 'runs', focusRunsTab: 'compare' })
  },
  openProposals: ({ id } = {}) => {
    _parsePath.navigatePath.call(void 0, _optionalChain([id, 'optionalAccess', _21 => _21.trim, 'call', _22 => _22()]) ? _paths.paths.proposal(id.trim()) : _paths.paths.agentInbox())
    set({ view: 'proposals' })
  },
  openEdge: ({ project } = {}) => {
    const proj = _optionalChain([project, 'optionalAccess', _23 => _23.trim, 'call', _24 => _24()]) || ''
    if (proj) {
      persistActiveProject(proj)
      set({ activeProject: proj })
    }
    const W = proj || get().activeProject || ''
    _parsePath.navigatePath.call(void 0, W ? _paths.paths.ship(W) : _paths.paths.deployShip())
    set({ view: 'edge' })
  },
  openData: ({ project } = {}) => {
    const W = _optionalChain([project, 'optionalAccess', _25 => _25.trim, 'call', _26 => _26()]) || get().activeProject || ''
    if (W) _parsePath.navigatePath.call(void 0, _paths.paths.datasets(W))
    else _parsePath.navigatePath.call(void 0, _paths.paths.libraryDatasets())
    set({ view: 'data' })
  },
  openProjects: ({ project } = {}) => {
    const name = _optionalChain([project, 'optionalAccess', _27 => _27.trim, 'call', _28 => _28()])
    if (name) {
      persistActiveProject(name)
      set({ activeProject: name })
      _parsePath.navigatePath.call(void 0, _paths.paths.workspace(name))
    } else {
      _parsePath.navigatePath.call(void 0, _paths.paths.workspaces())
    }
    set({ view: 'projects' })
  },
  activeProject: readStoredActiveProject(),
  setActiveProject: (name) => {
    const next = _optionalChain([name, 'optionalAccess', _29 => _29.trim, 'call', _30 => _30()]) || null
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
        runOutcome: 'idle' ,
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
      runOutcome: 'idle' ,
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
    get().openProjects({ project: n, tab: _optionalChain([opts, 'optionalAccess', _31 => _31.tab]) })
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
          actionLabel: _optionalChain([opts, 'optionalAccess', _32 => _32.actionLabel]),
          onAction: _optionalChain([opts, 'optionalAccess', _33 => _33.onAction]),
        },
      ].slice(-MAX_TOASTS),
    }))
    // Drop oldest timers when capped
    const remaining = new Set(get().toasts.map((t) => t.id))
    for (const tid of [...toastTimers.keys()]) {
      if (!remaining.has(tid)) clearToastTimer(tid)
    }
    clearToastTimer(id)
    const ttl = _nullishCoalesce(_optionalChain([opts, 'optionalAccess', _34 => _34.ttlMs]), () => ( (_optionalChain([opts, 'optionalAccess', _35 => _35.actionLabel]) ? 10000 : _nullishCoalesce(TOAST_TTL_MS[tone], () => ( 3500)))))
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
  setBootError: (bootError, bootStatus = null) => set({ bootError, bootStatus: _nullishCoalesce(bootStatus, () => ( null)) }),
  backendMode: null,
  setBackendMode: (backendMode) => set({ backendMode }),
  settingsOpen: false,
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  getCanvasGraph: null,
  setGetCanvasGraph: (fn) => set({ getCanvasGraph: fn }),
  pendingGraph: null,
  loadGraphIntoBuilder: (graph) => {
    _parsePath.navigatePath.call(void 0, _paths.paths.editor(get().activeProject || 'workspace'), true)
    set({ pendingGraph: graph, view: 'builder' })
  },
  consumePendingGraph: () => {
    const g = get().pendingGraph
    if (g) set({ pendingGraph: null })
    return g
  },
  builderDataset: null,
  setBuilderDataset: (builderDataset) => set({ builderDataset }),
})); exports.useAppStore = useAppStore
