// CommonJS harness: sucrase emitted CJS. Stub browser globals then exercise the real store.
const listeners = { popstate: [] }
let curPath = '/workspaces/demo/runs'
let curSearch = ''
const store = {}
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v) },
  removeItem: (k) => { delete store[k] },
}
global.crypto = { randomUUID: () => 'x' + Math.random() }
class PopStateEvent { constructor(type) { this.type = type } }
global.PopStateEvent = PopStateEvent
global.window = {
  get location() { return { pathname: curPath, search: curSearch } },
  history: {
    pushState: (_s, _t, p) => { const [a, b] = String(p).split('?'); curPath = a; curSearch = b ? '?' + b : '' },
    replaceState: (_s, _t, p) => { const [a, b] = String(p).split('?'); curPath = a; curSearch = b ? '?' + b : '' },
  },
  addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn) },
  removeEventListener: (t, fn) => { listeners[t] = (listeners[t] || []).filter((f) => f !== fn) },
  dispatchEvent: (ev) => { for (const fn of [...(listeners[ev.type] || [])]) fn(ev) },
}
global.document = { title: '' }

const { useAppStore } = require('./store/appStore.js')
const { parsePathname, panelToFocus } = require('./routes/parsePath.js')

// Faithful copy of App.tsx:414-441 `apply`
let applyCalls = 0
const apply = () => {
  applyCalls++
  if (applyCalls > 200) throw new Error('RUNAWAY: apply() re-entered ' + applyCalls + ' times')
  const s = useAppStore.getState()
  const parsed = parsePathname(window.location.pathname, window.location.search)
  if (parsed.workspaceId) {
    const cur = useAppStore.getState().activeProject
    if (cur !== parsed.workspaceId) s.setActiveProject(parsed.workspaceId)
  }
  if (parsed.runsTab === 'compare' || parsed.view === 'experiments') {
    s.openExperiments(parsed.compareIds && parsed.compareIds.length ? { runIds: parsed.compareIds } : {})
    return
  }
  if (parsed.runId) {
    s.openRun(parsed.runId, { project: parsed.workspaceId, panel: panelToFocus(parsed.panel) ?? undefined })
    return
  }
  if (parsed.view) s.setView(parsed.view)
}
window.addEventListener('popstate', apply)

function trial(name, fn) {
  applyCalls = 0
  try { fn(); console.log(`${name}: OK (apply calls=${applyCalls}, path=${curPath}${curSearch})`) }
  catch (e) { console.log(`${name}: ${e.message} (path=${curPath}${curSearch})`) }
}

useAppStore.getState().setActiveProject('demo')
trial('A. RunsView goCompareTab -> openExperiments', () => useAppStore.getState().openExperiments({ runIds: ['r1'] }))
curPath = '/workspaces/demo/runs'; curSearch = ''
trial('B. openRun (deep link / row click)', () => useAppStore.getState().openRun('run-123', { project: 'demo', panel: 'logs' }))
curPath = '/workspaces/demo/runs'; curSearch = ''
trial('C. browser Back onto a compare URL', () => { curPath = '/workspaces/demo/runs/compare'; curSearch = '?ids=r1,r2'; window.dispatchEvent(new PopStateEvent('popstate')) })
