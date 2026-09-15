import { describe, expect, it } from 'vitest'
import { ApiError, apiUrl } from './client'

describe('api client', () => {
  it('apiUrl joins base and path', () => {
    expect(apiUrl('/nodes')).toMatch(/\/nodes$/)
    expect(apiUrl('runs', { limit: 2 })).toContain('limit=2')
  })

  it('ApiError carries status and path', () => {
    const err = new ApiError('nope', 401, '/runs')
    expect(err.status).toBe(401)
    expect(err.path).toBe('/runs')
    expect(err.message).toBe('nope')
  })
})
