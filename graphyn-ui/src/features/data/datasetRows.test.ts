import { describe, expect, it } from 'vitest'
import { normalizeDatasetRows } from './datasetRows'

describe('normalizeDatasetRows', () => {
  it('passes bare arrays through (records only)', () => {
    expect(normalizeDatasetRows([{ path: 'a' }, 3, null])).toEqual([{ path: 'a' }])
  })

  it('unwraps list envelopes', () => {
    expect(normalizeDatasetRows({ items: [{ path: 'x' }] })).toEqual([{ path: 'x' }])
  })

  it('prefers samples from the detail object and joins file sizes', () => {
    const rows = normalizeDatasetRows(
      {
        project: 'p',
        version: 'v1',
        files: [{ path: 'train/yes/a.wav', size: 10 }],
        samples: [{ path: 'p/v1/train/yes/a.wav', split: 'train', label: 'yes' }],
      },
      { project: 'p', version: 'v1' },
    )
    expect(rows).toEqual([{ path: 'p/v1/train/yes/a.wav', split: 'train', label: 'yes', size_bytes: 10 }])
  })

  it('falls back to manifest files qualified by project/version', () => {
    const rows = normalizeDatasetRows({ project: 'p', version: 'v1', files: [{ path: 'labels.csv', size: 5 }], samples: [] })
    expect(rows).toEqual([{ path: 'p/v1/labels.csv', size_bytes: 5 }])
  })

  it('maps lean files with split/label when samples are empty', () => {
    const rows = normalizeDatasetRows(
      {
        project: 'p',
        version: 'v1',
        files: [{ path: 'train/yes/a.wav', size: 10, split: 'train', label: 'yes' }],
        samples: [],
      },
      { project: 'p', version: 'v1' },
    )
    expect(rows).toEqual([
      { path: 'p/v1/train/yes/a.wav', size_bytes: 10, split: 'train', label: 'yes' },
    ])
  })

  it('returns [] for junk', () => {
    expect(normalizeDatasetRows(null)).toEqual([])
    expect(normalizeDatasetRows('nope')).toEqual([])
    expect(normalizeDatasetRows({ project: 'p' })).toEqual([])
  })
})
