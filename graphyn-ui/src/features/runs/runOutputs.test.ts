import { describe, expect, it } from 'vitest'
import {
  executionOrderFromRun,
  naturalCompare,
  normalizeOutputsResponse,
  orderOutputGroups,
  runHasModelOutput,
  sortFilesNatural,
} from './runOutputs'

const f = (name: string, node_id?: string) => ({ name, path: `x/${name}`, size: 1, kind: 'audio', node_id })

describe('normalizeOutputsResponse', () => {
  it('accepts the legacy bare list', () => {
    const out = normalizeOutputsResponse([f('a.wav')])
    expect(out.files).toHaveLength(1)
    expect(out.truncated).toBe(false)
    expect(out.truncatedByNode).toEqual({})
  })

  it('reads with_meta {items, truncated, truncated_by_node}', () => {
    const out = normalizeOutputsResponse({
      items: [f('a.wav', 'seg'), f('b.wav', 'seg')],
      truncated: true,
      max_items: 400,
      truncated_by_node: { seg: { shown: 2, total: 900 } },
    })
    expect(out.files).toHaveLength(2)
    expect(out.truncated).toBe(true)
    expect(out.truncatedByNode.seg).toEqual({ shown: 2, total: 900 })
  })

  it('derives truncation from total_by_node when that is all the server sends', () => {
    const out = normalizeOutputsResponse({ items: [f('a.wav', 'n1')], total_by_node: { n1: 5, n2: 0 } })
    expect(out.truncatedByNode).toEqual({ n1: { shown: 1, total: 5 } })
    expect(out.truncated).toBe(true)
  })

  it('tolerates junk', () => {
    expect(normalizeOutputsResponse(null).files).toEqual([])
    expect(normalizeOutputsResponse({ detail: 'x' }).files).toEqual([])
  })
})

describe('natural sort', () => {
  it('orders numbers numerically', () => {
    const names = ['10.wav', '0.wav', '100.wav', '1.wav', '2.wav']
    expect(sortFilesNatural(names.map((n) => f(n))).map((x) => x.name)).toEqual([
      '0.wav',
      '1.wav',
      '2.wav',
      '10.wav',
      '100.wav',
    ])
    expect(naturalCompare('nohash_2', 'nohash_10')).toBeLessThan(0)
  })
})

describe('execution order + group order', () => {
  it('prefers node_stats.node_index, then graph, then journal', () => {
    const order = executionOrderFromRun({
      nodeStats: [
        { node_id: 'audio_conditioner_1', node_index: 1 },
        { node_id: 'dataset_ingest_0', node_index: 0 },
      ],
      graphNodes: [{ id: 'dataset_ingest_0' }, { id: 'segmenter_2' }],
      events: [{ type: 'node_start', node_id: 'trainer_3' }],
    })
    expect(order).toEqual(['dataset_ingest_0', 'audio_conditioner_1', 'segmenter_2', 'trainer_3'])
  })

  it('keeps nodes with no files, appends unknown groups, run-level last', () => {
    const order = orderOutputGroups(
      ['dataset_ingest_0', 'audio_conditioner_1', 'segmenter_2'],
      ['run', 'audio_conditioner_1', 'dataset_ingest_0', 'zzz'],
    )
    expect(order).toEqual(['dataset_ingest_0', 'audio_conditioner_1', 'segmenter_2', 'zzz', 'run'])
  })
})

describe('runHasModelOutput', () => {
  it('is false for a preprocess-only run', () => {
    expect(
      runHasModelOutput({
        files: [{ name: 'a.wav', path: 'x/a.wav', kind: 'audio' }, { name: 'manifest.json', path: 'm.json', kind: 'json' }],
        artifacts: [{ artifact_type: 'audio_samples', node_type: 'segmenter', node_id: 'segmenter_2' }],
        metrics: { num_samples: 10, segments: 40 },
        nodeStats: [{ node_id: 'dataset_ingest_0', node_type: 'dataset_ingest' }],
      }),
    ).toBe(false)
  })

  it('is true for model files, trainer nodes, training metrics, or registered models', () => {
    expect(runHasModelOutput({ files: [{ name: 'model.tflite', path: 'a/model.tflite', kind: 'binary' }] })).toBe(true)
    expect(runHasModelOutput({ nodeStats: [{ node_id: 'trainer_3', node_type: 'trainer' }] })).toBe(true)
    expect(runHasModelOutput({ metrics: { val_accuracy: 0.9 } })).toBe(true)
    expect(runHasModelOutput({ artifacts: [{ artifact_type: 'keras_model' }] })).toBe(true)
    expect(runHasModelOutput({ registeredModels: 1 })).toBe(true)
  })
})

describe('server listing order', () => {
  it('re-sorts a lexicographic server listing (0,1,10,100,2) naturally', () => {
    const names = ['0.wav', '1.wav', '10.wav', '100.wav', '2.wav']
    const files = names.map((name) => ({ name, path: `n/${name}`, size: 1, kind: 'audio' }))
    expect(sortFilesNatural(files).map((f) => f.name)).toEqual(['0.wav', '1.wav', '2.wav', '10.wav', '100.wav'])
    // already natural (backend switched): unchanged
    expect(sortFilesNatural(sortFilesNatural(files)).map((f) => f.name)).toEqual(['0.wav', '1.wav', '2.wav', '10.wav', '100.wav'])
  })
})
