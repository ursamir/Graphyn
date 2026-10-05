import { describe, expect, it } from 'vitest'
import { applyTemplateFilter, templateFilterValue, type TemplateFilterState } from './templateFilter'

const base: TemplateFilterState = { filter: 'all', runnableOnly: true, plugins: [] }

describe('templateFilterValue', () => {
  it('encodes the state', () => {
    expect(templateFilterValue(base)).toBe('runnable')
    expect(templateFilterValue({ ...base, runnableOnly: false })).toBe('all')
    expect(templateFilterValue({ ...base, filter: 'examples' })).toBe('examples')
    expect(templateFilterValue({ ...base, plugins: ['asr'] })).toBe('plugin:asr')
    expect(templateFilterValue({ ...base, plugins: ['asr', 'pii'] })).toBe('plugins')
  })
})

describe('applyTemplateFilter', () => {
  it('round-trips and resets other dimensions', () => {
    for (const v of ['runnable', 'all', 'examples', 'saved', 'plugin:asr']) {
      expect(templateFilterValue(applyTemplateFilter(v, base))).toBe(v)
    }
    expect(applyTemplateFilter('plugin:asr', { filter: 'saved', runnableOnly: true, plugins: [] })).toEqual({
      filter: 'all',
      runnableOnly: false,
      plugins: ['asr'],
    })
    expect(applyTemplateFilter('plugins', { ...base, plugins: ['a', 'b'] }).plugins).toEqual(['a', 'b'])
  })
})
