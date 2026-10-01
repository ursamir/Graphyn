import { describe, expect, it } from 'vitest'
import { naturalCompare } from './naturalSort'

const sorted = (xs: string[]) => [...xs].sort(naturalCompare)

describe('naturalCompare', () => {
  it('orders numeric suffixes naturally', () => {
    expect(sorted(['nohash_10.wav', 'nohash_2.wav', 'nohash_1.wav'])).toEqual([
      'nohash_1.wav',
      'nohash_2.wav',
      'nohash_10.wav',
    ])
  })

  it('keeps hex-like ids in plain lexicographic order', () => {
    const files = [
      '0c540988_nohash_0.wav',
      '03401e93_nohash_0.wav',
      '9a7c1f83_nohash_0.wav',
      '0a7c2a8d_nohash_0.wav',
      '03401e93_nohash_1.wav',
    ]
    expect(sorted(files)).toEqual([
      '03401e93_nohash_0.wav',
      '03401e93_nohash_1.wav',
      '0a7c2a8d_nohash_0.wav',
      '0c540988_nohash_0.wav',
      '9a7c1f83_nohash_0.wav',
    ])
  })

  it('still compares plain numbers numerically and is case-insensitive', () => {
    expect(sorted(['v12', 'v9', 'V100'])).toEqual(['v9', 'v12', 'V100'])
    expect(naturalCompare('file_1234567', 'file_123456789')).toBeLessThan(0)
    expect(naturalCompare('a', 'a')).toBe(0)
  })
})
