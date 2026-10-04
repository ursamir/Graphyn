import { describe, expect, it } from 'vitest'
import { resolveFullRunId, runDisplayName } from './runDisplay'

describe('runDisplayName', () => {
  it('prefers display_name', () => {
    expect(runDisplayName({ display_name: 'Speech commands E2E · train', graph_name: 'pipeline' })).toBe(
      'Speech commands E2E · train',
    )
    expect(runDisplayName({ meta: { display_name: 'X' } })).toBe('X')
  })
  it('humanizes graph names, hides generic ones', () => {
    expect(runDisplayName({ graph_name: 'ex-06-speech-commands-e2e' })).toBe('Speech commands (E2E)')
    expect(runDisplayName({ graph_name: 'pipeline', run_id: 'abcdef1234567890' })).toBe('Run abcdef12')
    expect(runDisplayName(null)).toBe('Run')
  })
})

describe('resolveFullRunId', () => {
  const full = '96505918a1b2c3d4e5f60718293a4b5c'
  it('expands a prefix from the detail run_id', () => {
    expect(resolveFullRunId('96505918', { run_id: full })).toBe(full)
    expect(resolveFullRunId('96505918', { meta: { run_id: full } })).toBe(full)
  })
  it('keeps the requested id when the detail does not extend it', () => {
    expect(resolveFullRunId(full, { run_id: full })).toBe(full)
    expect(resolveFullRunId('96505918', { run_id: 'deadbeef00' })).toBe('96505918')
    expect(resolveFullRunId('96505918', null)).toBe('96505918')
    expect(resolveFullRunId('96505918', {})).toBe('96505918')
  })
})
