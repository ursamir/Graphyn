import { describe, expect, it } from 'vitest'
import { canvasPathView } from './canvasPaths'

const n = (id: string, nodeType: string, label: string, config: Record<string, unknown> = {}) => ({
  id,
  data: { nodeType, label, config },
})

describe('canvasPathView', () => {
  it('labels fork copies by path with descriptions', () => {
    const nodes = [
      n('db_0', 'dataset_builder', 'Dataset Builder'),
      n('model_builder_0', 'model_builder', 'Model Builder', { architecture: 'ds_cnn' }),
      n('trainer_0', 'trainer', 'Trainer', { epochs: 50 }),
      n('model_builder_c3f15543', 'model_builder', 'Model Builder', { architecture: 'simple_cnn' }),
      n('trainer_b66a5330', 'trainer', 'Trainer', { epochs: 30 }),
    ]
    const edges = [
      { source: 'db_0', target: 'model_builder_0' },
      { source: 'model_builder_0', target: 'trainer_0' },
      { source: 'db_0', target: 'model_builder_c3f15543' },
      { source: 'model_builder_c3f15543', target: 'trainer_b66a5330' },
    ]
    const v = canvasPathView(nodes, edges)
    expect(v.pathOf.get('trainer_0')).toEqual({ letter: 'A', description: 'DS-CNN · 50 epochs' })
    expect(v.pathOf.get('trainer_b66a5330')).toEqual({ letter: 'B', description: 'Simple CNN · 30 epochs' })
    expect(v.pathOf.has('db_0')).toBe(false)
    expect(v.labelOf.get('model_builder_c3f15543')).toBe('Model Builder · Path B')
    expect(v.labelOf.get('db_0')).toBe('Dataset Builder')
  })

  it('adds the effective learning rate when paths differ by it (trainer wins)', () => {
    const nodes = [
      n('db', 'dataset_builder', 'Dataset Builder'),
      n('mb_b', 'model_builder', 'Model Builder', { architecture: 'mobilenet', learning_rate: 0.001 }),
      n('tr_b', 'trainer', 'Trainer', { epochs: 30 }),
      n('mb_c', 'model_builder', 'Model Builder', { architecture: 'mobilenet', learning_rate: 0.002 }),
      n('tr_c', 'trainer', 'Trainer', { epochs: 30, learning_rate: 0.0005 }),
    ]
    const edges = [
      { source: 'db', target: 'mb_b' },
      { source: 'mb_b', target: 'tr_b' },
      { source: 'db', target: 'mb_c' },
      { source: 'mb_c', target: 'tr_c' },
    ]
    const v = canvasPathView(nodes, edges)
    expect(v.pathOf.get('tr_b')?.description).toBe('MobileNet · 30 epochs · lr 0.001')
    expect(v.pathOf.get('tr_c')?.description).toBe('MobileNet · 30 epochs · lr 5e-4')
  })

  it('linear graphs get no paths', () => {
    const v = canvasPathView([n('a', 'x', 'A'), n('b', 'y', 'B')], [{ source: 'a', target: 'b' }])
    expect(v.pathOf.size).toBe(0)
    expect(v.labelOf.get('b')).toBe('B')
  })

  it('workflow branches get no path badges; shared unlabeled types show the id', () => {
    const nodes = [
      n('check', 'if_switch', 'IF Switch'),
      n('approved', 'set_map', 'Set / Map'),
      n('auto', 'set_map', 'Set / Map'),
      n('note', 'set_map', 'My note'),
    ]
    const edges = [
      { source: 'check', target: 'approved' },
      { source: 'check', target: 'auto' },
    ]
    const v = canvasPathView(nodes, edges)
    expect(v.pathOf.size).toBe(0)
    expect(v.titleOf.get('approved')).toEqual({ title: 'approved', subtitle: 'Set / Map' })
    expect(v.titleOf.get('auto')?.title).toBe('auto')
    expect(v.titleOf.has('note')).toBe(false)
    expect(v.titleOf.has('check')).toBe(false)
  })
})
