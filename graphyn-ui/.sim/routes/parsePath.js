"use strict";Object.defineProperty(exports, "__esModule", {value: true});/**
 * Parse pathname → view / workspace / run / panel for path↔store sync.
 */
















const PANEL_SET = new Set(['logs', 'outputs', 'lineage', 'details', 'checkpoints'])

/** Map panel path segment → FocusRunPanel store value (artifacts for outputs). */
 function panelToFocus(panel) {
  if (!panel) return null
  if (panel === 'outputs') return 'artifacts'
  if (panel === 'details') return 'debug'
  return panel
} exports.panelToFocus = panelToFocus;

 function parsePathname(pathname, search = '') {
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  const qs = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)

  if (parts.length === 0) {
    return { view: 'projects' }
  }

  const [a, b, c, d, e] = parts

  if (a === 'login' || a === 'settings' || a === '404') {
    return { view: 'projects' }
  }

  if (a === 'workspaces') {
    if (!b) return { view: 'projects' }
    const W = decodeURIComponent(b)
    if (!c) return { view: 'projects', workspaceId: W }
    if (c === 'editor') return { view: 'builder', workspaceId: W }
    if (c === 'runs') {
      if (d === 'live') return { view: 'runs', workspaceId: W, runsTab: 'live' }
      if (d === 'compare') {
        const ids = (qs.get('ids') || '')
          .split(',')
          .map((x) => decodeURIComponent(x.trim()))
          .filter(Boolean)
        return { view: 'experiments', workspaceId: W, runsTab: 'compare', compareIds: ids }
      }
      if (d) {
        const runId = decodeURIComponent(d)
        const panel = e && PANEL_SET.has(e ) ? (e ) : undefined
        return { view: 'runs', workspaceId: W, runId, panel, runsTab: 'history' }
      }
      return { view: 'runs', workspaceId: W, runsTab: 'history' }
    }
    if (c === 'models') {
      return {
        view: 'models' ,
        workspaceId: W,
        modelName: d ? decodeURIComponent(d) : undefined,
      }
    }
    if (c === 'datasets') return { view: 'data', workspaceId: W }
    if (c === 'ship') {
      return {
        view: 'edge',
        workspaceId: W,
        shipTab: d === 'devices' ? 'devices' : 'package',
      }
    }
    if (c === 'agent') return { view: 'builder', workspaceId: W }
    return { view: 'projects', workspaceId: W }
  }

  if (a === 'templates') return { view: 'templates' }
  if (a === 'agent' && b === 'inbox') {
    return { view: 'proposals', proposalId: c ? decodeURIComponent(c) : undefined }
  }
  if (a === 'library') {
    if (b === 'datasets') return { view: 'data' }
    if (b === 'plugins') return { view: 'plugins' }
    if (b === 'artifacts') return { view: 'artifacts' }
    if (b === 'models') return { view: 'models'  }
  }
  if (a === 'deploy') {
    if (b === 'ship') return { view: 'edge' }
    if (b === 'workers') return { view: 'workers' }
  }
  if (a === 'admin') {
    if (b === 'secrets') return { view: 'secrets' }
    if (b === 'ops') return { view: 'system' }
    if (b === 'access') return { view: 'access'  }
  }

  return { view: 'projects' }
} exports.parsePathname = parsePathname;

/** History API navigation that notifies listeners (store + App sync). */
 function navigatePath(path, replace = false) {
  if (replace) window.history.replaceState(null, '', path)
  else window.history.pushState(null, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
} exports.navigatePath = navigatePath;
