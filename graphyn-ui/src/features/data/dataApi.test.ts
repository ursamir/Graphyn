import { describe, expect, it } from 'vitest'
import {
  DEFAULT_UPLOAD_LIMITS,
  classifyPick,
  isSnapshotProject,
  planBatches,
  stripPickedRoot,
  zipPath,
} from './dataApi'

describe('classifyPick', () => {
  it('accepts allowlisted types and archives, rejects others', () => {
    expect(classifyPick({ name: 'a.WAV', size: 1 })).toBe('ok')
    expect(classifyPick({ name: 'set/x.csv', size: 1 })).toBe('ok')
    expect(classifyPick({ name: 'data.tar.gz', size: 1 })).toBe('archive')
    expect(classifyPick({ name: 'tool.exe', size: 1 })).toBe('unsupported')
    expect(classifyPick({ name: 'x/.DS_Store', size: 1 })).toBe('unsupported')
    expect(classifyPick({ name: 'big.wav', size: DEFAULT_UPLOAD_LIMITS.max_request_bytes + 1 })).toBe('too_large')
  })
})

describe('planBatches', () => {
  it('splits by count and by bytes', () => {
    const limits = { ...DEFAULT_UPLOAD_LIMITS, max_request_bytes: 100, max_files: 3 }
    const files = [40, 40, 40, 10, 10, 10, 10].map((size, i) => ({ name: `${i}.wav`, size }))
    const batches = planBatches(files, limits)
    expect(batches).toEqual([[0, 1], [2, 3, 4], [5, 6]])
  })
  it('never returns empty batches', () => {
    expect(planBatches([])).toEqual([])
  })
})

describe('stripPickedRoot', () => {
  it('drops the picked folder', () => {
    expect(stripPickedRoot(['pick/a.wav', 'pick/sub/b.wav'], false)).toEqual(['a.wav', 'sub/b.wav'])
    expect(stripPickedRoot(['root/yes/a.wav', 'root/n.csv'], true)).toEqual(['yes/a.wav', 'n.csv'])
  })
  it('keeps a class folder picked directly as the label', () => {
    expect(stripPickedRoot(['yes/a.wav', 'yes/b.wav'], true)).toEqual(['yes/a.wav', 'yes/b.wav'])
  })
  it('leaves plain files alone', () => {
    expect(stripPickedRoot(['a.wav', 'b.wav'], false)).toEqual(['a.wav', 'b.wav'])
  })
})

describe('zipPath / snapshots', () => {
  it('builds label and version paths', () => {
    expect(zipPath({ label: 'kw' })).toBe('/data/inputs/kw/zip')
    expect(zipPath({ project: '_inputs/kw', version: 'v1' })).toBe('/data/outputs/_inputs/kw/v1/zip')
    expect(zipPath({ project: 'a b', version: 'v2' })).toBe('/data/outputs/a%20b/v2/zip')
  })
  it('recognises snapshot projects', () => {
    expect(isSnapshotProject('_inputs/kw')).toBe(true)
    expect(isSnapshotProject('_inputs')).toBe(false)
    expect(isSnapshotProject('proj')).toBe(false)
  })
})
