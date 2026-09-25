import { describe, expect, it } from 'vitest'
import { unwrapList } from './unwrapList'

describe('unwrapList', () => {
  it('returns bare arrays unchanged', () => {
    expect(unwrapList([{ id: 1 }])).toEqual([{ id: 1 }])
  })

  it('unwraps envelope items', () => {
    expect(
      unwrapList({ items: [{ id: 1 }], total: 1, limit: 50, offset: 0, next_offset: null }),
    ).toEqual([{ id: 1 }])
  })

  it('returns empty for unknown shapes', () => {
    expect(unwrapList(null)).toEqual([])
    expect(unwrapList({})).toEqual([])
    expect(unwrapList('x')).toEqual([])
  })
})
