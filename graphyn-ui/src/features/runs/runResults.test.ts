import { describe, expect, it } from 'vitest'
import { computePipelineShape } from './runNodes'
import {
  datasetFromRun,
  datasetSentence,
  defaultModelOption,
  describeBranch,
  fallbackPathResults,
  guessModelKind,
  isRegression,
  lanePathMap,
  listRowMetric,
  normalizeRunModels,
  pathDisplayName,
  pathsFromSummary,
  perClassRows,
  confusionMatrix,
  pickBestPath,
  rankModelOptions,
  regressionFromHistory,
  runTitle,
  scalarMetrics,
  slugifyModelName,
  suggestModelName,
} from './runResults'
import { primaryMetric } from '../../lib/metrics'

const graph = {
  nodes: [
    { id: 'ingest_0', node_type: 'dataset_ingest', config: { path: 'workspace/datasets/input/speech-commands' } },
    { id: 'db_0', node_type: 'dataset_builder' },
    { id: 'mb_0', node_type: 'model_builder', config: { architecture: 'ds_cnn' } },
    { id: 'tr_0', node_type: 'trainer', config: { epochs: 50 } },
    { id: 'ev_0', node_type: 'evaluator' },
    { id: 'mb_1', node_type: 'model_builder', config: { architecture: 'simple_cnn' } },
    { id: 'tr_1', node_type: 'trainer', config: { epochs: 30 } },
    { id: 'ev_1', node_type: 'evaluator' },
  ],
  edges: [
    ['ingest_0', 'db_0'],
    ['db_0', 'mb_0'],
    ['mb_0', 'tr_0'],
    ['tr_0', 'ev_0'],
    ['db_0', 'mb_1'],
    ['mb_1', 'tr_1'],
    ['tr_1', 'ev_1'],
  ].map(([src_id, dst_id]) => ({ src_id, dst_id })),
}
const ids = graph.nodes.map((n) => n.id)

describe('runTitle', () => {
  it('prefers display_name, then humanized graph name', () => {
    expect(runTitle({ display_name: 'Speech · train', graph_name: 'x' })).toBe('Speech · train')
    expect(runTitle({ meta: { display_name: 'From meta' } })).toBe('From meta')
    expect(runTitle({ graph_name: 'speech_commands_train' })).toBe('Speech commands train')
    expect(runTitle({ graph_name: 'pipeline', run_id: '2280ec7127774d9f' })).toMatch(/^Run /)
  })
})

describe('paths', () => {
  it('describes a branch from architecture + epochs', () => {
    expect(describeBranch(['mb_0', 'tr_0', 'ev_0'], graph.nodes)).toBe('DS-CNN · 50 epochs')
    expect(describeBranch(['ev_0'], graph.nodes)).toBe('')
  })

  it('builds fallback paths from evaluator metrics and picks the best', () => {
    const shape = computePipelineShape(ids, graph.edges)
    expect(shape.kind).toBe('fork')
    const paths = fallbackPathResults({
      shape,
      graphNodes: graph.nodes,
      metricsByNode: {
        ev_0: { test_accuracy: 0.5611111, per_class: { a: {} }, roc_auc: 0.85 },
        ev_1: { test_accuracy: 0.5 },
      },
    })
    expect(paths.map((p) => pathDisplayName(p))).toEqual([
      'Path A (DS-CNN · 50 epochs)',
      'Path B (Simple CNN · 30 epochs)',
    ])
    expect(paths[0].metrics).toEqual({ test_accuracy: 0.5611111, roc_auc: 0.85 })
    expect(paths[0].metricsNodeId).toBe('ev_0')
    expect(pickBestPath(paths)?.letter).toBe('A')
    expect(lanePathMap(shape, paths).get('B')?.description).toBe('Simple CNN · 30 epochs')
    expect(listRowMetric({ primary: null, paths })).toBe('Test accuracy 56.1% · 2 paths')
  })

  it('reads backend summary paths', () => {
    const paths = pathsFromSummary({
      meta: {
        summary: {
          paths: [
            { path_id: 'path-a', label: 'DS-CNN · 50 epochs', node_ids: ['tr_0'], metrics: { test_accuracy: 0.561, per_class: {} } },
            { path_id: 'path-b', label: 'Path B', node_ids: ['tr_1'], metrics: { test_accuracy: 0.5 } },
          ],
          best_path_id: 'path-b',
        },
      },
    })
    expect(paths.map((p) => [p.letter, p.description, p.primary?.value])).toEqual([
      ['A', 'DS-CNN · 50 epochs', 0.561],
      ['B', '', 0.5],
    ])
    expect(pickBestPath(paths, 'path-b')?.letter).toBe('B')
  })

  it('scalarMetrics drops nested values', () => {
    expect(scalarMetrics({ a: 1, b: 'x', c: [1], d: { e: 1 }, f: true })).toEqual({ a: 1 })
  })
})

describe('dataset', () => {
  it('uses backend summary.dataset with phase-aware wording', () => {
    const ds = datasetFromRun({ run: { summary: { dataset: { source_path: 'a/b/speech', clip_count: 1201 } } } })
    expect(ds && datasetSentence(ds)).toBe('Used 1,201 clips from speech')
    expect(ds && datasetSentence(ds, 'speech_commands_e2e_train_ml')).toBe('Trained on 1,201 clips from speech')
    expect(ds && datasetSentence(ds, 'speech_commands_e2e_preprocess')).toBe('Processed 1,201 clips from speech')
  })
  it('falls back to ingest node_end count + configured path', () => {
    const ds = datasetFromRun({
      events: [{ type: 'node_end', node_id: 'ingest_0', node_type: 'dataset_ingest', output_count: 1200 }],
      graphNodes: graph.nodes,
    })
    expect(ds).toEqual({ count: 1200, source: 'workspace/datasets/input/speech-commands', fallbackUsed: false })
  })
})

describe('regression', () => {
  const rows = [
    { run_id: 'old1', graph_name: 'g', created_at: '2026-01-01T00:00:00Z', metrics: { test_accuracy: 0.867 } },
    { run_id: 'old2', graph_name: 'g', created_at: '2026-01-02T00:00:00Z', metrics: { test_accuracy: 0.7 } },
    { run_id: 'other', graph_name: 'h', created_at: '2026-01-02T00:00:00Z', metrics: { test_accuracy: 0.99 } },
    { run_id: 'newer', graph_name: 'g', created_at: '2026-02-01T00:00:00Z', metrics: { test_accuracy: 0.95 } },
  ]
  it('compares with the best earlier run of the same pipeline', () => {
    const r = regressionFromHistory({
      runId: 'cur',
      graphName: 'g',
      createdAt: '2026-01-10T00:00:00Z',
      current: { name: 'test_accuracy', value: 0.561 },
      rows,
      metricOf: (row) => primaryMetric(row),
    })
    expect(r?.previousRunId).toBe('old1')
    expect(r?.delta).toBeCloseTo(-0.306)
    expect(r && isRegression(r)).toBe(true)
  })
  it('returns null without history', () => {
    expect(
      regressionFromHistory({ runId: 'x', graphName: 'z', current: { name: 'accuracy', value: 1 }, rows, metricOf: primaryMetric }),
    ).toBeNull()
  })
})

describe('evaluator detail', () => {
  it('per-class rows and confusion matrix', () => {
    const m = { per_class: { yes: { precision: 1, recall: 0.9, f1: 0.947 }, down: { precision: 0.5 } }, confusion_matrix: [[1, 2], [3, 4]] }
    expect(perClassRows(m).map((r) => r.label)).toEqual(['down', 'yes'])
    expect(confusionMatrix(m)).toEqual([[1, 2], [3, 4]])
    expect(confusionMatrix({ confusion_matrix: 'x' })).toBeNull()
  })
})

describe('models', () => {
  it('guesses kinds from path / node type', () => {
    expect(guessModelKind('a/models/compiled_0ffd19ab5ebe.keras', 'model_builder')).toBe('compiled_untrained')
    expect(guessModelKind('a/compiled_0ffd19ab5ebe4388.keras')).toBe('compiled_untrained')
    expect(guessModelKind('a/trainer_0/model.keras', 'trainer')).toBe('trained')
    expect(guessModelKind('a/tflite/model.tflite', 'edge_optimizer')).toBe('optimized')
  })

  it('never defaults to an untrained model and prefers the best path', () => {
    const opts = normalizeRunModels({
      models: [
        { path: 'artifacts/x/runs/r/models/compiled_ab12cd34.keras', node_type: 'model_builder', kind: 'compiled_untrained', path_id: 'path-a' },
        { path: 'artifacts/x/runs/r/trainer_1/model.keras', kind: 'trained', path_id: 'path-b', size_bytes: 10 },
        { path: 'artifacts/x/runs/r/trainer_0/model.keras', kind: 'trained', path_id: 'path-a', suggested_name: 'speech-dscnn' },
        { path: 'artifacts/x/runs/r/tflite/model.tflite', kind: 'optimized', path_id: 'path-a' },
      ],
    })
    expect(opts[1].slug).toBe('x')
    expect(defaultModelOption(opts, 'path-a')?.path).toContain('trainer_0')
    expect(defaultModelOption(opts, 'path-b')?.path).toContain('trainer_1')
    expect(rankModelOptions(opts, 'path-a').map((o) => o.kind)).toEqual(['trained', 'optimized', 'trained', 'compiled_untrained'])
    expect(defaultModelOption([opts[0]])).toBeNull()
    expect(suggestModelName(opts[2], 'g')).toBe('speech-dscnn')
  })

  it('suggests a slug from graph + path', () => {
    expect(suggestModelName(null, 'speech_commands_e2e', 'DS-CNN · 50 epochs')).toBe('speech-commands-e2e-ds-cnn-50-epochs')
    expect(slugifyModelName('', '')).toBe('model')
  })
})
