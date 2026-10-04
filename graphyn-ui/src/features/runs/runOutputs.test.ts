import { describe, expect, it } from 'vitest'
import {
  executionOrderFromRun,
  guessNodeFromPath,
  isPackageRun,
  isInternalRunFile,
  artifactSlugFromPath,
  listRunModelCandidates,
  looksLikeOpaqueId,
  naturalCompare,
  normalizeOutputsResponse,
  orderOutputGroups,
  runHasModelOutput,
  runLevelFileCue,
  shortOutputPath,
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

  it('drops opaque hex ids from group order', () => {
    const order = orderOutputGroups(
      ['realtime_inference_4'],
      ['run', 'c63a89bfa4dd45fd9aa6d2a55abcdef0', 'realtime_inference_4'],
    )
    expect(order).toEqual(['realtime_inference_4', 'run'])
  })
})

describe('guessNodeFromPath', () => {
  const runId = 'c63a89bfa4dd45fd9aa6d2a55abcdef0'

  it('does not treat outputs_index.json as /out under the run id', () => {
    expect(
      guessNodeFromPath(`runs/${runId}/outputs_index.json`, [], undefined, { runId }),
    ).toBe('run')
    expect(
      guessNodeFromPath(`workspace/runs/${runId}/outputs_index.json`, [], undefined, { runId }),
    ).toBe('run')
  })

  it('keeps stamped node_id and real node path segments', () => {
    expect(
      guessNodeFromPath('artifacts/x/0.wav', [], { node_id: 'realtime_inference_4' }, { runId }),
    ).toBe('realtime_inference_4')
    expect(guessNodeFromPath('nodes/audio_exporter_3/out/a.wav', [], undefined, { runId })).toBe(
      'audio_exporter_3',
    )
  })

  it('maps opaque API node_id to run', () => {
    expect(looksLikeOpaqueId(runId)).toBe(true)
    expect(
      guessNodeFromPath(`runs/${runId}/meta.json`, [], { node_id: runId }, { runId }),
    ).toBe('run')
  })
})

describe('internal files + short paths', () => {
  const runId = 'c63a89bfa4dd45fd9aa6d2a55abcdef0'

  it('hides outputs_index.json from listings', () => {
    expect(isInternalRunFile(`runs/${runId}/outputs_index.json`)).toBe(true)
    const out = normalizeOutputsResponse([
      { name: 'outputs_index.json', path: `runs/${runId}/outputs_index.json`, size: 1, kind: 'json' },
      { name: 'meta.json', path: `runs/${runId}/meta.json`, size: 1, kind: 'json' },
    ])
    expect(out.files.map((f) => f.name)).toEqual(['meta.json'])
  })

  it('shortens runs/<id>/… paths for card subtitles', () => {
    expect(shortOutputPath(`workspace/runs/${runId}/meta.json`, { runId })).toBe('meta.json')
    expect(shortOutputPath(`runs/${runId}/outputs_index.json`)).toBe('outputs_index.json')
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

  it('is true only for model files, model-typed artifacts, or registered models', () => {
    expect(runHasModelOutput({ files: [{ name: 'model.tflite', path: 'a/model.tflite', kind: 'binary' }] })).toBe(true)
    expect(runHasModelOutput({ artifacts: [{ artifact_type: 'keras_model' }] })).toBe(true)
    expect(runHasModelOutput({ registeredModels: 1 })).toBe(true)
    // Trainer / metrics alone — workflow ran, but no model artifact to promote.
    expect(runHasModelOutput({ nodeStats: [{ node_id: 'trainer_3', node_type: 'trainer' }] })).toBe(false)
    expect(runHasModelOutput({ metrics: { val_accuracy: 0.9 } })).toBe(false)
  })

  it('is false for Ship / deploy package runs even with an optimized model file', () => {
    const files = [{ name: 'model.tflite', path: 'a/model.tflite', kind: 'model' }]
    expect(
      runHasModelOutput({ files, graphNodeTypes: ['python_code', 'edge_optimizer', 'deployment_packager'] }),
    ).toBe(false)
    expect(runHasModelOutput({ files, graphName: 'edge-deploy' })).toBe(false)
    expect(runHasModelOutput({ files, artifacts: [{ artifact_type: 'deployment_package' }] })).toBe(false)
  })

  it('needs a trained model: untrained-only runs do not count', () => {
    expect(runHasModelOutput({ modelKinds: ['compiled_untrained'] })).toBe(false)
    expect(runHasModelOutput({ modelKinds: ['compiled_untrained', 'trained'] })).toBe(true)
    expect(
      runHasModelOutput({ files: [{ name: 'compiled_abc123.keras', path: 'm/compiled_abc123.keras', kind: 'model' }] }),
    ).toBe(false)
  })
})

describe('isPackageRun', () => {
  it('detects package graphs only', () => {
    expect(isPackageRun({ graphNodeTypes: ['trainer', 'evaluator'] })).toBe(false)
    expect(isPackageRun({ graphNodeTypes: ['deployment_packager'] })).toBe(true)
  })
})

describe('artifactSlugFromPath', () => {
  it('reads pack slug from artifacts/<slug>/runs/…', () => {
    expect(
      artifactSlugFromPath(
        'artifacts/optimized/runs/2280ec7127774d9f9bdeb528126f5344/model.tflite',
      ),
    ).toBe('optimized')
    expect(
      artifactSlugFromPath(
        'workspace/artifacts/speech-commands/runs/abc/tflite/model.tflite',
      ),
    ).toBe('speech-commands')
  })

  it('skips content-addressed blob dirs', () => {
    expect(artifactSlugFromPath('artifacts/b0d99d938dcb48198e686326f8a92c69/data')).toBeUndefined()
  })
})

describe('listRunModelCandidates', () => {
  it('splits dual-branch trainers into separate candidates', () => {
    const c = listRunModelCandidates({
      files: [
        { name: 'model.keras', path: 'trainer_0/model.keras', kind: 'model', node_id: 'trainer_0' },
        {
          name: 'model.keras',
          path: 'trainer_b66a5330/model.keras',
          kind: 'model',
          node_id: 'trainer_b66a5330',
        },
      ],
      labelFor: (id) => (id === 'trainer_0' ? 'Trainer #0' : 'Trainer #b66a5330'),
    })
    expect(c.map((x) => x.id)).toEqual(['trainer_0', 'trainer_b66a5330'])
    expect(c.map((x) => x.label)).toEqual(['Trainer #0', 'Trainer #b66a5330'])
  })

  it('attaches workspace pack slug from pack-layout paths', () => {
    const c = listRunModelCandidates({
      files: [
        {
          name: 'model.tflite',
          path: 'artifacts/optimized/runs/2280ec7127774d9f9bdeb528126f5344/model.tflite',
          kind: 'model',
          node_id: 'edge_optimizer_f683f74c',
        },
        {
          name: 'model.tflite',
          path: 'artifacts/speech-commands/runs/2280ec7127774d9f9bdeb528126f5344/tflite/model.tflite',
          kind: 'model',
          node_id: 'edge_optimizer_0',
        },
      ],
    })
    expect(c.find((x) => x.id === 'edge_optimizer_f683f74c')?.artifactSlug).toBe('optimized')
    expect(c.find((x) => x.id === 'edge_optimizer_0')?.artifactSlug).toBe('speech-commands')
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

describe('runLevelFileCue', () => {
  it('maps journal filenames to plain titles', () => {
    expect(runLevelFileCue('graph.json').title).toBe('Pipeline graph')
    expect(runLevelFileCue('meta.json').title).toBe('Run summary')
    expect(runLevelFileCue('logs.json').title).toBe('Event log')
    expect(runLevelFileCue('prove.json').title).toBe('Reproducibility record')
    expect(runLevelFileCue('weird.bin').title).toBe('weird.bin')
  })
})
