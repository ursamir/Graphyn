import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { parsePathname, resolveRouteAlias } from './parsePath'
import { navHighlightFor, navSectionFor, NAV_SECTIONS } from './navSections'

describe('resolveRouteAlias — global pages', () => {
  it.each([
    ['/plugins', '/library/plugins'],
    ['/library', '/library/plugins'],
    ['/ops', '/admin/ops'],
    ['/admin', '/admin/ops'],
    ['/system', '/admin/ops'],
    ['/admin/system', '/admin/ops'],
    ['/credentials', '/admin/credentials'],
    ['/secrets', '/admin/credentials'],
    ['/access', '/admin/access'],
    ['/workers', '/deploy/workers'],
    ['/deploy', '/deploy/workers'],
    ['/admin/workers', '/deploy/workers'],
    ['/inbox', '/agent/inbox'],
    ['/agent', '/agent/inbox'],
    ['/proposals/p-1', '/agent/inbox/p-1'],
    ['/library/templates', '/templates'],
    ['/Plugins/', '/library/plugins'],
  ])('%s → %s', (from, to) => {
    expect(resolveRouteAlias(from, null)).toBe(to)
    expect(resolveRouteAlias(from, 'demo')).toBe(to)
  })
})

describe('resolveRouteAlias — workspace pages', () => {
  it.each([
    ['/runs', '/workspaces/demo/runs'],
    ['/editor', '/workspaces/demo/editor'],
    ['/builder', '/workspaces/demo/editor'],
    ['/models', '/workspaces/demo/models'],
    ['/ship', '/workspaces/demo/ship'],
    ['/datasets', '/workspaces/demo/datasets'],
    ['/home', '/workspaces/demo'],
    ['/compare', '/workspaces/demo/runs/compare'],
    ['/devices', '/workspaces/demo/ship/devices'],
    ['/runs/abcDEF12/logs', '/workspaces/demo/runs/abcDEF12/logs'],
    ['/models/kws', '/workspaces/demo/models/kws'],
  ])('%s → %s (with workspace)', (from, to) => {
    expect(resolveRouteAlias(from, 'demo')).toBe(to)
  })

  it('encodes the workspace id', () => {
    expect(resolveRouteAlias('/runs', 'my ws')).toBe('/workspaces/my%20ws/runs')
  })

  it('falls back to the picker (or shared datasets) without a workspace', () => {
    expect(resolveRouteAlias('/runs', null)).toBe('/workspaces')
    expect(resolveRouteAlias('/editor', undefined)).toBe('/workspaces')
    expect(resolveRouteAlias('/home', '')).toBe('/workspaces')
    expect(resolveRouteAlias('/datasets', null)).toBe('/library/datasets')
  })
})

describe('resolveRouteAlias — /workspaces/:id/<x>', () => {
  it.each([
    ['/workspaces/demo/templates', '/templates'],
    ['/workspaces/demo/plugins', '/library/plugins'],
    ['/workspaces/demo/ops', '/admin/ops'],
    ['/workspaces/demo/credentials', '/admin/credentials'],
    ['/workspaces/demo/inbox', '/agent/inbox'],
    ['/workspaces/demo/builder', '/workspaces/demo/editor'],
    ['/workspaces/demo/data', '/workspaces/demo/datasets'],
    ['/workspaces/demo/edge', '/workspaces/demo/ship'],
    ['/workspaces/demo/home', '/workspaces/demo'],
    ['/workspaces/demo/compare', '/workspaces/demo/runs/compare'],
  ])('%s → %s', (from, to) => {
    expect(resolveRouteAlias(from, 'demo')).toBe(to)
  })

  it('leaves real workspace routes alone', () => {
    for (const p of ['/workspaces/demo', '/workspaces/demo/runs', '/workspaces/demo/editor', '/workspaces/demo/ship/devices']) {
      expect(resolveRouteAlias(p, 'demo')).toBeNull()
    }
  })
})

describe('resolveRouteAlias — unknown stays unknown', () => {
  it.each(['/nonsense', '/plugins/foo/bar', '/library/nope', '/agent/what', '/workspaces/demo/junk'])(
    '%s → null',
    (p) => {
      expect(resolveRouteAlias(p, 'demo')).toBeNull()
    },
  )
})

describe('parsePathname with aliases', () => {
  const store = new Map<string, string>()
  beforeEach(() => {
    store.clear()
    ;(globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    }
  })
  afterEach(() => {
    delete (globalThis as { localStorage?: unknown }).localStorage
  })

  it('redirects global aliases with a canonical URL', () => {
    expect(parsePathname('/plugins')).toMatchObject({ view: 'plugins', canonical: '/library/plugins' })
    expect(parsePathname('/ops')).toMatchObject({ view: 'system', canonical: '/admin/ops' })
    expect(parsePathname('/plugins').notFound).toBeUndefined()
  })

  it('scopes workspace aliases to the remembered workspace', () => {
    store.set('graphyn.activeProject', 'demo')
    expect(parsePathname('/runs')).toMatchObject({
      view: 'runs',
      workspaceId: 'demo',
      canonical: '/workspaces/demo/runs',
    })
    expect(parsePathname('/editor')).toMatchObject({ view: 'builder', workspaceId: 'demo' })
  })

  it('parses saved-pipeline Editor links', () => {
    expect(parsePathname('/workspaces/demo/editor/pipelines/train%20ml')).toMatchObject({
      view: 'builder',
      workspaceId: 'demo',
      editorPipeline: 'train ml',
      editorEnv: undefined,
    })
    expect(parsePathname('/workspaces/demo/editor/pipelines/p/staging')).toMatchObject({
      editorPipeline: 'p',
      editorEnv: 'staging',
    })
  })

  it('lands workspace aliases on the picker without a workspace', () => {
    expect(parsePathname('/models')).toMatchObject({ view: 'projects', canonical: '/workspaces' })
  })

  it('/workspaces/:id/templates opens Templates (not Home)', () => {
    expect(parsePathname('/workspaces/demo/templates')).toMatchObject({
      view: 'templates',
      canonical: '/templates',
    })
  })

  it('keeps a real 404 for unknown paths', () => {
    expect(parsePathname('/nonsense')).toMatchObject({ view: 'projects', notFound: true })
    expect(parsePathname('/workspaces/demo/junk')).toMatchObject({ notFound: true, workspaceId: 'demo' })
  })

  it('does not touch real routes', () => {
    expect(parsePathname('/library/plugins')).toEqual({ view: 'plugins' })
    expect(parsePathname('/admin/ops')).toEqual({ view: 'system' })
    expect(parsePathname('/templates')).toEqual({ view: 'templates' })
  })
})

describe('sidebar sections', () => {
  it('groups Work / Library / Admin', () => {
    expect(NAV_SECTIONS.map((s) => s.title)).toEqual(['Work', 'Library', 'Admin'])
    expect(NAV_SECTIONS[0].items.map((i) => i.label)).toEqual([
      'Home',
      'Editor',
      'Runs',
      'Models',
      'Ship',
      'Datasets',
    ])
    expect(NAV_SECTIONS[1].items.map((i) => i.label)).toEqual(['Templates', 'Plugins'])
    expect(NAV_SECTIONS[2].collapsible).toBe(true)
    expect(NAV_SECTIONS[2].items.map((i) => i.label)).toEqual([
      'Agent inbox',
      'Worker fleet',
      'Credentials',
      'Ops',
      'Access',
    ])
  })

  it('highlights the parent row for nested views', () => {
    expect(navHighlightFor('experiments')).toBe('runs')
    expect(navHighlightFor('devices')).toBe('edge')
    expect(navHighlightFor('system')).toBe('system')
    expect(navHighlightFor(null)).toBeNull()
    expect(navSectionFor('system')).toBe('admin')
    expect(navSectionFor('experiments')).toBe('work')
    expect(navSectionFor('plugins')).toBe('library')
  })

  it('/admin/ops resolves to a view that highlights Ops in Admin', () => {
    const view = parsePathname('/admin/ops').view
    expect(navHighlightFor(view)).toBe('system')
    expect(navSectionFor(view)).toBe('admin')
  })
})
