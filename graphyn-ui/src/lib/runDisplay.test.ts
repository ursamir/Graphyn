import { describe, expect, it } from 'vitest'
import {
  isRunStatusException,
  resolveFullRunId,
  runDisplayName,
  runStatusLabel,
  runStatusTone,
  shortId,
} from './runDisplay'

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

describe('runStatusLabel / runStatusTone', () => {
  it.each([
    ['succeeded', 'Done', 'done'],
    ['completed', 'Done', 'done'],
    ['SUCCESS', 'Done', 'done'],
    ['failed', 'Failed', 'failed'],
    ['error', 'Failed', 'failed'],
    ['running', 'Running', 'running'],
    ['in_progress', 'Running', 'running'],
    ['queued', 'Queued', 'queued'],
    ['pending', 'Queued', 'queued'],
    ['cancelled', 'Cancelled', 'cancelled'],
    ['canceled', 'Cancelled', 'cancelled'],
    ['paused', 'Paused', 'paused'],
    ['archived', 'Archived', 'archived'],
    ['awaiting_approval', 'Awaiting approval', 'needs-action'],
  ])('%s → %s', (raw, label, tone) => {
    expect(runStatusLabel(raw)).toBe(label)
    expect(runStatusTone(raw)).toBe(tone)
  })

  it('sentence-cases unknown statuses and handles empty', () => {
    expect(runStatusLabel('skipped')).toBe('Skipped')
    expect(runStatusLabel('not_run')).toBe('Not run')
    expect(runStatusLabel('')).toBe('Unknown')
    expect(runStatusLabel(null)).toBe('Unknown')
    expect(runStatusTone('skipped')).toBe('unknown')
  })

  it('only exceptions get a coloured badge', () => {
    for (const s of ['failed', 'running', 'queued', 'cancelled', 'paused', 'needs_action']) {
      expect(isRunStatusException(s)).toBe(true)
    }
    for (const s of ['succeeded', 'completed', 'archived', '', 'skipped']) {
      expect(isRunStatusException(s)).toBe(false)
    }
  })
})

describe('shortId', () => {
  it('keeps 8 chars by default', () => {
    expect(shortId('96505918a1b2c3d4')).toBe('96505918')
    expect(shortId('abc')).toBe('abc')
    expect(shortId('96505918a1b2c3d4', 12)).toBe('96505918a1b2')
    expect(shortId('')).toBe('—')
    expect(shortId(null)).toBe('—')
  })
})
