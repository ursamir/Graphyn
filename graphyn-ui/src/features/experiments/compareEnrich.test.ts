import { describe, expect, it } from 'vitest'
import { compareHasRows, enrichCompareParams } from './compareEnrich'

describe('enrichCompareParams', () => {
  it('adds node config params from graphs; experiment params win', () => {
    const payload = {
      param_keys: ['lr'],
      metric_keys: [],
      runs: [
        { run_id: 'a', parameters: { lr: 0.1 } },
        { run_id: 'b', parameters: { lr: 0.2 } },
      ],
    }
    const graphs = new Map([
      ['a', { nodes: [{ id: 'trainer_0', config: { epochs: 5 } }] }],
      ['b', { nodes: [{ id: 'trainer_0', config: { epochs: 10 } }] }],
    ])
    const out = enrichCompareParams(payload, graphs)
    expect(out.param_keys).toEqual(['lr', 'trainer_0.epochs'])
    expect(out.runs[0].parameters).toEqual({ lr: 0.1, 'trainer_0.epochs': 5 })
    expect(out.runs[1].parameters['trainer_0.epochs']).toBe(10)
  })

  it('tolerates missing graphs', () => {
    const out = enrichCompareParams({ param_keys: [], runs: [{ run_id: 'a' }] }, new Map())
    expect(out.param_keys).toEqual([])
    expect(compareHasRows(out)).toBe(false)
    expect(compareHasRows({ metric_keys: ['acc'] })).toBe(true)
    expect(compareHasRows(null)).toBe(false)
  })
})
