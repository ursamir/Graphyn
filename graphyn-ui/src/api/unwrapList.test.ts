import { describe, expect, it, vi } from 'vitest'
import { fetchAllPages, unwrapList } from './unwrapList'

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

describe('fetchAllPages', () => {
  it('returns bare array as the full list', async () => {
    const fetchPage = vi.fn(async () => [{ id: 1 }, { id: 2 }])
    await expect(fetchAllPages(fetchPage, 50)).resolves.toEqual([{ id: 1 }, { id: 2 }])
    expect(fetchPage).toHaveBeenCalledTimes(1)
  })

  it('follows next_offset until exhausted', async () => {
    const fetchPage = vi.fn(async (offset: number) => {
      if (offset === 0) {
        return { items: [{ id: 1 }], total: 2, limit: 1, offset: 0, next_offset: 1 }
      }
      return { items: [{ id: 2 }], total: 2, limit: 1, offset: 1, next_offset: null }
    })
    await expect(fetchAllPages<{ id: number }>(fetchPage, 1)).resolves.toEqual([
      { id: 1 },
      { id: 2 },
    ])
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })
})
