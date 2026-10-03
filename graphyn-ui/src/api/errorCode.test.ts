import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { apiErrorCode, apiErrorDetail } from './errorCode'

describe('apiErrorCode', () => {
  it('reads error.code and detail.code', () => {
    expect(apiErrorCode(new ApiError('x', 422, '/m', { error: { code: 'labels_mismatch' }, detail: { expected: ['a'] } }))).toBe(
      'labels_mismatch',
    )
    expect(apiErrorCode(new ApiError('x', 409, '/m', { detail: { code: 'run_not_succeeded' } }))).toBe('run_not_succeeded')
    expect(apiErrorCode(new ApiError('x', 500, '/m', { detail: 'boom' }))).toBeNull()
    expect(apiErrorCode(new Error('plain'))).toBeNull()
  })
  it('reads detail object', () => {
    expect(apiErrorDetail(new ApiError('x', 422, '/m', { detail: { expected: ['a'] } }))).toEqual({ expected: ['a'] })
  })
})
