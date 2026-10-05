import { describe, expect, it } from 'vitest'
import { outputSelectionKnown } from './outputSelection'

describe('outputSelectionKnown', () => {
  const outputs = [
    { project: 'e06-verify-1', versions: ['v1'] },
    { project: '_inputs/speech-commands', versions: ['v1', 'v2'] },
  ]

  it('accepts a real project/version pair', () => {
    expect(outputSelectionKnown(outputs, 'e06-verify-1', 'v1')).toBe(true)
    expect(outputSelectionKnown(outputs, '_inputs/speech-commands', 'v2')).toBe(true)
  })

  it('rejects leftover version on another project (404 storm case)', () => {
    expect(outputSelectionKnown(outputs, 'e06-verify-1', 'v2')).toBe(false)
    expect(outputSelectionKnown(outputs, 'e08-verify-1', 'v1')).toBe(false)
  })

  it('rejects empty', () => {
    expect(outputSelectionKnown(outputs, '', 'v1')).toBe(false)
    expect(outputSelectionKnown([], 'e06-verify-1', 'v1')).toBe(false)
  })
})
