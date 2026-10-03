import { describe, expect, it } from 'vitest'
import { pickLatestResult, regressionTone } from './latestResult'

describe('pickLatestResult', () => {
  const runs = [
    { run_id: 'r3', status: 'failed', metrics: { accuracy: 0.9 } },
    { run_id: 'r2', status: 'completed' },
    {
      run_id: 'r1',
      status: 'completed',
      summary: { primary_metric: { name: 'test_accuracy', value: 0.561 } },
      regression: { delta: -0.02, best_previous_value: 0.58, best_previous_run_id: 'r0' },
    },
  ]
  it('skips failed and metric-less runs and links the model', () => {
    const res = pickLatestResult(runs, [{ name: 'kws', stages: { staging: { run_id: 'r1' } } }])
    expect(res?.run.run_id).toBe('r1')
    expect(res?.metric).toEqual({ name: 'test_accuracy', value: 0.561 })
    expect(res?.modelName).toBe('kws')
    expect(regressionTone(res!.regression)).toBe('worse')
  })
  it('returns null without results', () => {
    expect(pickLatestResult([{ run_id: 'x' }])).toBeNull()
    expect(regressionTone(null)).toBeNull()
    expect(regressionTone({ delta: 0.01, previousValue: null, previousRunId: null })).toBe('better')
  })
})
