import { describe, expect, it } from 'vitest'
import { findStep, groupTemplates, groupTitle, isTemplateRunnable, phaseRank, templateMissing } from './templateGroups'

describe('runnable', () => {
  it('prefers backend fields and falls back to the client computation', () => {
    expect(templateMissing({ name: 'a', missing_node_types: ['x'] }, () => ['y'])).toEqual(['x'])
    expect(templateMissing({ name: 'a' }, () => ['y'])).toEqual(['y'])
    expect(isTemplateRunnable({ name: 'a', runnable: false }, [])).toBe(false)
    expect(isTemplateRunnable({ name: 'a' }, [])).toBe(true)
    expect(isTemplateRunnable({ name: 'a' }, ['x'])).toBe(false)
  })
})

describe('groupTemplates', () => {
  it('collapses a group into ordered steps at its first position', () => {
    const list = [
      { name: 'alpha' },
      { name: 'ex-06-train', group: 'speech-commands-e2e', phase: 'train', step_title: 'Train model' },
      { name: 'beta' },
      { name: 'ex-06-prepare', group: 'speech-commands-e2e', phase: 'prepare', step_title: 'Prepare dataset' },
    ]
    const entries = groupTemplates(list)
    expect(entries.map((e) => (e.kind === 'single' ? e.tpl.name : e.group))).toEqual([
      'alpha',
      'speech-commands-e2e',
      'beta',
    ])
    const g = entries[1]
    expect(g.kind).toBe('group')
    if (g.kind === 'group') {
      expect(g.title).toBe('Speech commands E2E')
      expect(g.steps.map((s) => [s.step, s.title])).toEqual([
        [1, 'Prepare dataset'],
        [2, 'Train model'],
      ])
    }
    expect(findStep(entries, 'ex-06-train')?.step.step).toBe(2)
    expect(findStep(entries, 'alpha')).toBeNull()
  })

  it('keeps single-member groups as singles', () => {
    expect(groupTemplates([{ name: 'a', group: 'g' }])[0].kind).toBe('single')
  })

  it('ranks phases', () => {
    expect(phaseRank(2)).toBe(2)
    expect(phaseRank('step-1')).toBe(1)
    expect(phaseRank('prepare')).toBeLessThan(phaseRank('train'))
    expect(groupTitle('ex-06-speech-commands-e2e')).toBe('Speech commands E2E')
  })
})
