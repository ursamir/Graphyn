import { describe, expect, it } from 'vitest'
import { buildCrashReport } from './crashReport'

describe('buildCrashReport', () => {
  it('includes view, message and trimmed stack', () => {
    const err = new TypeError('S.filter is not a function')
    const text = buildCrashReport('Datasets', err, 'at A\nat B')
    expect(text).toContain('"Datasets" page failed')
    expect(text).toContain('TypeError: S.filter is not a function')
    expect(text).toContain('at A\nat B')
  })
})
