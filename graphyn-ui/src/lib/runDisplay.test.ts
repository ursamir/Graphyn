import { describe, expect, it } from 'vitest'
import { runDisplayName } from './runDisplay'

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
