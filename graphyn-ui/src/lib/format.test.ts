import { describe, expect, it } from 'vitest'
import { focusMatchesNode, humanNodeLabel } from './format'

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

