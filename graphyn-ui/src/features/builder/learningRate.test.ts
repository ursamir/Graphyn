import { describe, expect, it } from 'vitest'
import { formatLr, learningRateLinks, learningRateNote } from './learningRate'
import { nodeSummary } from './editorChrome'

const n = (id: string, nodeType: string, label: string, config: Record<string, unknown> = {}) => ({
  id,
  data: { nodeType, label, config },
})

// Path C of the Example 06 fork: Model builder lr 0.002 → Trainer lr 0.001.
const pathC = () => ({
  nodes: [
    n('db', 'dataset_builder', 'Dataset Builder'),
    n('mb', 'model_builder', 'Model Builder', { architecture: 'mobilenet', learning_rate: 0.002 }),
    n('tr', 'trainer', 'Trainer', { epochs: 30, learning_rate: 0.001 }),
    n('ev', 'evaluator', 'Evaluator'),
  ],
  edges: [
    { source: 'db', target: 'mb' },
    { source: 'db', target: 'tr' },
    { source: 'mb', target: 'tr' },
    { source: 'tr', target: 'ev' },
  ],
})

describe('learningRateLinks', () => {
  it('a set Trainer learning rate wins over the Model builder', () => {
    const { nodes, edges } = pathC()
    const m = learningRateLinks(nodes, edges)
    expect(m.get('tr')).toMatchObject({ role: 'trainer', effective: 0.001, source: 'trainer', builderLr: 0.002, otherId: 'mb' })
    expect(m.get('mb')).toMatchObject({ role: 'builder', effective: 0.001, source: 'trainer', builderLr: 0.002, otherId: 'tr' })
    expect(m.has('db')).toBe(false)
  })

  it('an empty Trainer learning rate keeps the Model builder value', () => {
    const { nodes, edges } = pathC()
    nodes[2] = n('tr', 'trainer', 'Trainer', { epochs: 30, learning_rate: '' })
    const m = learningRateLinks(nodes, edges)
    expect(m.get('tr')).toMatchObject({ effective: 0.002, source: 'model_builder', trainerLr: null })
    expect(m.get('mb')).toMatchObject({ effective: 0.002, source: 'model_builder' })
  })

  it('isolated node types and unpaired nodes', () => {
    const m = learningRateLinks(
      [n('mb', 'Isolated_model_builder', 'MB', { learning_rate: 0.01 }), n('tr', 'Isolated_trainer', 'T'), n('t2', 'trainer', 'Lonely')],
      [{ source: 'mb', target: 'tr' }],
    )
    expect(m.get('tr')?.effective).toBe(0.01)
    expect(m.has('t2')).toBe(false)
  })

  it('builder feeding trainers with different values has no single effective lr', () => {
    const m = learningRateLinks(
      [n('mb', 'model_builder', 'MB', { learning_rate: 0.002 }), n('a', 'trainer', 'A', { learning_rate: 0.01 }), n('b', 'trainer', 'B')],
      [{ source: 'mb', target: 'a' }, { source: 'mb', target: 'b' }],
    )
    expect(m.get('mb')?.effective).toBeNull()
    expect(m.get('a')?.effective).toBe(0.01)
    expect(m.get('b')?.effective).toBe(0.002)
  })
})

describe('learningRateNote', () => {
  it('explains which value training uses', () => {
    const { nodes, edges } = pathC()
    const m = learningRateLinks(nodes, edges)
    expect(learningRateNote(m.get('tr'))).toBe("Wins over Model Builder's 0.002 — training uses 0.001.")
    expect(learningRateNote(m.get('mb'))).toBe('Not used for training — Trainer sets 0.001, which wins.')
    nodes[2] = n('tr', 'trainer', 'Trainer', {})
    const m2 = learningRateLinks(nodes, edges)
    expect(learningRateNote(m2.get('tr'))).toBe("Empty — training uses Model Builder's 0.002.")
    expect(learningRateNote(m2.get('mb'))).toBe('Used for training (Trainer leaves its learning rate empty).')
    expect(learningRateNote(undefined)).toBeNull()
  })

  it('formats small rates compactly', () => {
    expect(formatLr(0.002)).toBe('0.002')
    expect(formatLr(0.0001)).toBe('1e-4')
  })
})

describe('nodeSummary with an effective learning rate', () => {
  it('shows the effective lr instead of the node’s own', () => {
    const cfg = { architecture: 'mobilenet', learning_rate: 0.002 }
    expect(nodeSummary({ nodeType: 'model_builder', config: cfg })).toBe('MobileNet · lr 0.002')
    expect(nodeSummary({ nodeType: 'model_builder', config: cfg, learningRate: 0.001 })).toBe('MobileNet · lr 0.001')
  })
})
