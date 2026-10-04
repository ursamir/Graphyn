import { describe, expect, it } from 'vitest'
import { errorMessageFromBody, humanizeErrorText } from './errorText'

describe('errorMessageFromBody', () => {
  it('reads {code, message} and nested detail/error objects', () => {
    expect(errorMessageFromBody({ code: 'run_not_found', message: "Run '96505918' not found" })).toBe(
      "Run '96505918' not found",
    )
    expect(errorMessageFromBody({ detail: { code: 'run_not_found', message: 'Run x not found' } })).toBe(
      'Run x not found',
    )
    expect(errorMessageFromBody({ error: { code: 'bad', message: 'Bad thing' }, detail: { code: 'bad' } })).toBe(
      'Bad thing',
    )
  })
  it('falls back to humanized codes and string detail', () => {
    expect(errorMessageFromBody({ detail: 'boom' })).toBe('boom')
    expect(errorMessageFromBody({ detail: { error: 'run_not_found', run_id: 'abc' } })).toBe(
      'Run not found (run_id=abc)',
    )
    expect(errorMessageFromBody({ error: { code: 'labels_mismatch' }, detail: { expected: ['a'] } })).toBe(
      'Labels mismatch',
    )
    expect(errorMessageFromBody({ error: 'not_found', detail: 'no such run' })).toBe('Not found: no such run')
  })
  it('joins pydantic validation lists', () => {
    expect(
      errorMessageFromBody({ detail: [{ loc: ['body', 'name'], msg: 'field required' }] }),
    ).toBe('name: field required')
  })
  it('returns null for unreadable bodies', () => {
    expect(errorMessageFromBody(null)).toBeNull()
    expect(errorMessageFromBody({ foo: 1 })).toBeNull()
  })
})

describe('humanizeErrorText', () => {
  it('replaces a raw JSON message with its human message', () => {
    expect(humanizeErrorText('{"code":"run_not_found","message":"Run \'96505918\' not found"}')).toBe(
      "Run '96505918' not found",
    )
    expect(humanizeErrorText('Register failed: {"detail":{"code":"x","message":"Nope"}}')).toBe(
      'Register failed: Nope',
    )
  })
  it('humanizes code lists', () => {
    expect(humanizeErrorText('run_not_found:96505918 · no_node_stats_or_artifacts')).toBe(
      'Run not found (96505918) · No node stats or artifacts',
    )
  })
  it('leaves normal text alone', () => {
    expect(humanizeErrorText('Something broke')).toBe('Something broke')
    expect(humanizeErrorText('weird {not json}')).toBe('weird {not json}')
  })
})
