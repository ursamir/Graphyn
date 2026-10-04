import { describe, expect, it } from 'vitest'
import { compareParamRows, flattenNodeConfigParams, isRunScopedPathParam, mergeRunParams, paramKeyLabel } from './runCompare'

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


describe('run-scoped path params', () => {
  const ids = ['aaaaaaaa11112222333344445555666677', 'bbbbbbbb11112222333344445555666677']
  it('hides output paths that only differ by run id', () => {
    expect(
      isRunScopedPathParam(
        'trainer_0.output_path',
        ids.map((id) => `workspace/artifacts/x/runs/${id}/trainer_0`),
        ids,
      ),
    ).toBe(true)
  })
  it('keeps real differences', () => {
    expect(isRunScopedPathParam('trainer_0.epochs', [50, 30], ids)).toBe(false)
    expect(isRunScopedPathParam('ingest_0.path', ['datasets/a', 'datasets/b'], ids)).toBe(false)
  })
  it('labels node keys', () => {
    const m = new Map([['trainer_24212f65', 'Trainer · Path C']])
    expect(paramKeyLabel('trainer_24212f65.epochs', m)).toBe('Trainer · Path C · epochs')
    expect(paramKeyLabel('graph.seed', m)).toBe('graph.seed')
  })
})
