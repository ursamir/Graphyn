import { describe, expect, it } from 'vitest'
import { countErrorRows, dedupeErrorRows, errorCore } from './logDedupe'

type Row = { message: string; level: string }
const r = (message: string, level = 'info'): Row => ({ message, level })
const text = (x: Row) => x.message
const lvl = (x: Row) => x.level

describe('log error dedupe', () => {
  it('drops the pipeline error that restates the node failure', () => {
    const rows = [
      r('Audio Conditioner · started'),
      r('Audio Conditioner · failed · Sample rate should be over 0', 'error'),
      r('Sample rate should be over 0', 'error'),
      r('Pipeline finished with errors', 'error'),
    ]
    const out = dedupeErrorRows(rows, text, lvl)
    expect(out.map(text)).toEqual([
      'Audio Conditioner · started',
      'Audio Conditioner · failed · Sample rate should be over 0',
      'Pipeline finished with errors',
    ])
    expect(countErrorRows(out, text, lvl)).toBe(1)
  })
  it('keeps distinct errors and the same error from a later node', () => {
    const rows = [
      r('A · failed · boom', 'error'),
      r('B · started'),
      r('B · failed · boom', 'error'),
      r('other problem', 'error'),
    ]
    expect(dedupeErrorRows(rows, text, lvl)).toHaveLength(4)
  })
  it('extracts the core message', () => {
    expect(errorCore('X · failed · Bad Thing')).toBe('bad thing')
    expect(errorCore('Bad Thing')).toBe('bad thing')
  })
})
