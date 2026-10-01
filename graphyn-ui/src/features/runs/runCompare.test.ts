import { describe, expect, it } from 'vitest'
import { compareParamRows, flattenNodeConfigParams, mergeRunParams } from './runCompare'

describe('compare params from graph.json', () => {
  const g1 = {
    parameters: { lr: 0.1, ui: { positions: {} } },
    nodes: [{ id: 'cond', config: { target_sample_rate: 16000, opts: { b: 1, a: 2 } } }],
  }
  const g2 = { nodes: [{ id: 'cond', config: { target_sample_rate: 8000, opts: { a: 2, b: 1 } } }] }
  it('flattens node configs as node_id.field and graph params as graph.key (no ui)', () => {
    expect(flattenNodeConfigParams(g1)).toEqual({
      'graph.lr': 0.1,
      'cond.target_sample_rate': 16000,
      'cond.opts': '{"a":2,"b":1}',
    })
  })
  it('marks differing rows; missing counts as different', () => {
    const rows = compareParamRows([{ params: flattenNodeConfigParams(g1) }, { params: flattenNodeConfigParams(g2) }])
    const by = Object.fromEntries(rows.map((r) => [r.key, r.differs]))
    expect(by).toEqual({ 'cond.opts': false, 'cond.target_sample_rate': true, 'graph.lr': true })
    expect(compareParamRows([{ params: {} }, { params: null }])).toEqual([])
    expect(compareParamRows([{ params: { a: 1 } }, { params: { a: 1 } }], { onlyDiffering: true })).toEqual([])
  })
  it('experiment params win over node config params', () => {
    expect(mergeRunParams({ 'cond.x': 'exp' }, { nodes: [{ id: 'cond', config: { x: 'graph', y: 1 } }] })).toEqual({
      'cond.x': 'exp',
      'cond.y': 1,
    })
  })
})
