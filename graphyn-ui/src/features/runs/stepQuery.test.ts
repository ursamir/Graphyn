import { describe, expect, it } from 'vitest'
import { parseStepParam, searchWithoutStep, stepQuery } from './stepQuery'

describe('step query param', () => {
  it('parses ?step= (and the ?node= alias)', () => {
    expect(parseStepParam('?step=trainer_b')).toBe('trainer_b')
    expect(parseStepParam('step=trainer%23c3f1')).toBe('trainer#c3f1')
    expect(parseStepParam('?status=active&node=eval_0')).toBe('eval_0')
    expect(parseStepParam('?step=%20')).toBeNull()
    expect(parseStepParam('')).toBeNull()
    expect(parseStepParam(undefined)).toBeNull()
  })

  it('strips the step but keeps other params', () => {
    expect(searchWithoutStep('?step=a&status=active')).toBe('?status=active')
    expect(searchWithoutStep('?step=a')).toBe('')
    expect(searchWithoutStep('')).toBe('')
  })

  it('builds a step suffix', () => {
    expect(stepQuery('trainer_b')).toBe('?step=trainer_b')
    expect(stepQuery('a b')).toBe('?step=a%20b')
    expect(stepQuery(null)).toBe('')
  })
})
