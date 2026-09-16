import { describe, expect, it } from 'vitest'
import { resolveLegacyHash } from './legacyHash'
import { paths } from './paths'

describe('paths', () => {
  it('builds workspace-scoped editor and run panel URLs', () => {
    expect(paths.editor('demo')).toBe('/workspaces/demo/editor')
    expect(paths.editor('demo', 'p1', 'staging')).toBe(
      '/workspaces/demo/editor/pipelines/p1/staging',
    )
    expect(paths.runPanel('demo', 'r1', 'lineage')).toBe(
      '/workspaces/demo/runs/r1/lineage',
    )
    expect(paths.runsCompare('demo', ['a', 'b'])).toBe(
      '/workspaces/demo/runs/compare?ids=a,b',
    )
    expect(paths.login('/workspaces')).toBe('/login?returnTo=%2Fworkspaces')
    expect(paths.libraryArtifacts({ artifactId: 'x' })).toBe(
      '/library/artifacts?artifactId=x',
    )
  })

  it('encodes workspace ids', () => {
    expect(paths.workspace('a/b')).toBe('/workspaces/a%2Fb')
  })
})

describe('resolveLegacyHash', () => {
  it('maps projects and project query', () => {
    expect(resolveLegacyHash('#/projects')).toBe('/workspaces')
    expect(resolveLegacyHash('#/projects?project=W')).toBe('/workspaces/W')
  })

  it('uses activeProject when hash needs a workspace', () => {
    expect(resolveLegacyHash('#/builder', { activeProject: 'W' })).toBe(
      '/workspaces/W/editor',
    )
    expect(resolveLegacyHash('#/runs/abc', { activeProject: 'W' })).toBe(
      '/workspaces/W/runs/abc',
    )
    expect(resolveLegacyHash('#/runs?tab=compare', { activeProject: 'W' })).toBe(
      '/workspaces/W/runs/compare',
    )
    expect(resolveLegacyHash('#/trace?run_id=r1', { activeProject: 'W' })).toBe(
      '/workspaces/W/runs/r1/lineage',
    )
  })

  it('falls back when workspace is missing', () => {
    expect(resolveLegacyHash('#/builder')).toBe('/workspaces')
    expect(resolveLegacyHash('#/runs/abc')).toBe('/workspaces?run=abc')
    expect(resolveLegacyHash('#/data')).toBe('/library/datasets')
    expect(resolveLegacyHash('#/edge')).toBe('/deploy/ship')
  })

  it('maps global legacy surfaces', () => {
    expect(resolveLegacyHash('#/proposals')).toBe('/agent/inbox')
    expect(resolveLegacyHash('#/plugins')).toBe('/library/plugins')
    expect(resolveLegacyHash('#/system')).toBe('/admin/ops')
    expect(resolveLegacyHash('#/workers')).toBe('/deploy/workers')
    expect(resolveLegacyHash('#/secrets')).toBe('/admin/secrets')
    expect(resolveLegacyHash('#/templates')).toBe('/templates')
    expect(resolveLegacyHash('#/artifacts')).toBe('/library/artifacts')
    expect(resolveLegacyHash('#/trace?artifact_id=a1')).toBe(
      '/library/artifacts?artifactId=a1',
    )
    expect(resolveLegacyHash('#/experiments', { activeProject: 'W' })).toBe(
      '/workspaces/W/runs/compare',
    )
  })

  it('returns null for empty or unknown hashes', () => {
    expect(resolveLegacyHash('')).toBeNull()
    expect(resolveLegacyHash('#/')).toBeNull()
    expect(resolveLegacyHash('#/nope')).toBeNull()
  })
})
