import { describe, expect, it } from 'vitest'
import { displayNodeLabel, focusMatchesNode, formatLogClock, humanNodeLabel, instanceIdCue } from './format'

describe('formatLogClock', () => {
  it('formats ISO timestamps as local HH:MM:SS', () => {
    const clock = formatLogClock('2026-10-07T10:20:30.000Z')
    expect(clock).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })
  it('passes through HH:MM:SS fragments', () => {
    expect(formatLogClock('14:32:01')).toBe('14:32:01')
  })
  it('returns empty for missing/invalid', () => {
    expect(formatLogClock(null)).toBe('')
    expect(formatLogClock('not-a-date')).toBe('')
  })
})

describe('focusMatchesNode', () => {
  it('matches exact ids only for graph instance ids', () => {
    expect(focusMatchesNode('trainer_0', 'trainer_0')).toBe(true)
    expect(focusMatchesNode('trainer_0', 'trainer_b66a5330')).toBe(false)
    expect(focusMatchesNode('evaluator_0', 'evaluator_2cf59b6d')).toBe(false)
  })

  it('soft-matches bare type labels onto instances (logs filters), not the reverse', () => {
    expect(focusMatchesNode('Trainer', 'trainer_0')).toBe(true)
    expect(focusMatchesNode('trainer', 'trainer_b66a5330')).toBe(true)
    // Instance focus is exact-only — bare "Trainer" must not re-merge siblings.
    expect(focusMatchesNode('trainer_0', 'Trainer')).toBe(false)
    expect(focusMatchesNode('trainer_b66a5330', 'Trainer')).toBe(false)
    expect(focusMatchesNode('trainer_b66a5330', humanNodeLabel('trainer_0'))).toBe(false)
  })
})

describe('instanceIdCue / displayNodeLabel', () => {
  it('extracts numeric and hex cues like the builder canvas', () => {
    expect(instanceIdCue('trainer_0', 'trainer')).toBe('0')
    expect(instanceIdCue('trainer_b66a5330', 'trainer')).toBe('b66a5330')
    expect(instanceIdCue('trainer', 'trainer')).toBe(null)
  })
  it('humanNodeLabel strips instance tails; displayNodeLabel can restore #cue', () => {
    expect(humanNodeLabel('trainer_0')).toBe('Trainer')
    expect(humanNodeLabel('trainer_b66a5330')).toBe('Trainer')
    expect(displayNodeLabel('trainer_0', { withCue: true })).toBe('Trainer #0')
    expect(displayNodeLabel('trainer_b66a5330', { label: 'Trainer', withCue: true })).toBe(
      'Trainer #b66a5330',
    )
  })
})

