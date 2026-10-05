import { describe, expect, it } from 'vitest'
import {
  deleteWorkspaceSummary,
  isArchivedWorkspace,
  partitionArchived,
  showsWorkspaceId,
  workspaceTitle,
} from './workspaceAdmin'

describe('archived filtering', () => {
  const list = [
    { name: 'a', status: 'draft' },
    { name: 'b', status: 'archived' },
    { name: 'c' },
    { name: 'd', status: ' Archived ' },
  ]

  it('detects archived status case-insensitively', () => {
    expect(isArchivedWorkspace({ status: 'archived' })).toBe(true)
    expect(isArchivedWorkspace({ status: 'ARCHIVED' })).toBe(true)
    expect(isArchivedWorkspace({ status: 'ready' })).toBe(false)
    expect(isArchivedWorkspace({})).toBe(false)
    expect(isArchivedWorkspace(null)).toBe(false)
  })

  it('hides archived by default and counts them', () => {
    const r = partitionArchived(list, false)
    expect(r.visible.map((p) => p.name)).toEqual(['a', 'c'])
    expect(r.archivedCount).toBe(2)
  })

  it('shows everything when toggled', () => {
    const r = partitionArchived(list, true)
    expect(r.visible.map((p) => p.name)).toEqual(['a', 'b', 'c', 'd'])
    expect(r.archivedCount).toBe(2)
  })
})

describe('workspace title', () => {
  it('prefers a non-empty display name', () => {
    expect(workspaceTitle({ name: 'kws', display_name: 'Keyword spotting' })).toBe('Keyword spotting')
    expect(showsWorkspaceId({ name: 'kws', display_name: 'Keyword spotting' })).toBe(true)
  })
  it('falls back to the id', () => {
    expect(workspaceTitle({ name: 'kws', display_name: '  ' })).toBe('kws')
    expect(workspaceTitle({ name: 'kws' })).toBe('kws')
    expect(showsWorkspaceId({ name: 'kws', display_name: 'kws' })).toBe(false)
  })
})

describe('delete summary', () => {
  it('lists removed and kept items with counts', () => {
    const s = deleteWorkspaceSummary({ pipelines: 2, datasetVersions: 1, schedules: 0, linkedInputs: 0 })
    expect(s.removed[0]).toBe('2 pipelines (drafts and published versions)')
    expect(s.removed[1]).toBe('1 dataset output version')
    expect(s.removed.some((l) => /schedule/.test(l))).toBe(false)
    expect(s.kept).toContain('Run history and run outputs (artifacts)')
    expect(s.kept).toContain('Registered models and Ship packages')
    expect(s.kept[s.kept.length - 1]).toBe('Shared dataset folders')
  })
  it('mentions schedules and linked folders when present', () => {
    const s = deleteWorkspaceSummary({ pipelines: 1, datasetVersions: 0, schedules: 3, linkedInputs: 1 })
    expect(s.removed[0]).toBe('1 pipeline (drafts and published versions)')
    expect(s.removed).toContain('3 schedules disabled (kept, marked orphaned)')
    expect(s.kept[s.kept.length - 1]).toBe('Shared dataset folders (1 folder in use: unlinked, not deleted)')
  })
})
