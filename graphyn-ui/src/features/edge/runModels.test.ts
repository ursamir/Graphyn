import { describe, expect, it } from 'vitest'
import {
  checkLabelsAgainstModel,
  inferModelFormat,
  normalizeRunModels,
  parseLabelsCsv,
  pickDefaultRunModel,
  runModelSummary,
  runModelsFromOutputs,
} from './runModels'

describe('normalizeRunModels', () => {
  it('reads {models: [...]} and skips rows without a path', () => {
    const rows = normalizeRunModels({
      run_id: 'r',
      models: [
        { path: 'workspace/artifacts/x/trainer_0/model.keras', kind: 'trained', size_bytes: 2048, labels: ['a', 'b'] },
        { kind: 'trained' },
      ],
    })
    expect(rows).toHaveLength(1)
    expect(rows[0].format).toBe('keras')
    expect(rows[0].labels).toEqual(['a', 'b'])
  })
  it('tolerates junk', () => {
    expect(normalizeRunModels(null)).toEqual([])
    expect(normalizeRunModels({ detail: 'Not Found' })).toEqual([])
  })
})

describe('runModelsFromOutputs', () => {
  it('finds model files and collapses saved_model internals', () => {
    const rows = runModelsFromOutputs([
      { path: 'workspace/artifacts/a/trainer_0/model.keras', size: 10, node_id: 'trainer_0' },
      { path: 'workspace/artifacts/a/trainer_0/saved_model/saved_model.pb', size: 5 },
      { path: 'workspace/artifacts/a/trainer_0/saved_model/variables/variables.index', size: 5 },
      { path: 'workspace/artifacts/a/edge_optimizer_0/model.tflite', node_id: 'edge_optimizer_0' },
      { path: 'workspace/artifacts/a/metrics.json' },
    ])
    expect(rows.map((r) => r.format)).toEqual(['keras', 'saved_model', 'tflite'])
    expect(rows[2].kind).toBe('optimized')
  })
})

describe('pickDefaultRunModel', () => {
  const models = normalizeRunModels([
    { path: 'workspace/artifacts/a/model_builder_0/model.keras', kind: 'compiled_untrained', path_id: 'path-a' },
    { path: 'workspace/artifacts/a/trainer_0/model.keras', kind: 'trained', path_id: 'path-a' },
    { path: 'workspace/artifacts/b/trainer_1/model.keras', kind: 'trained', path_id: 'path-b' },
    { path: 'workspace/artifacts/b/opt/model.tflite', kind: 'optimized', path_id: 'path-b' },
  ])
  it('honours a preferred path', () => {
    expect(pickDefaultRunModel(models, { preferredPath: 'artifacts/b/trainer_1/model.keras' })?.path).toBe(
      'workspace/artifacts/b/trainer_1/model.keras',
    )
  })
  it('prefers the best path trained model, never untrained', () => {
    expect(pickDefaultRunModel(models, { bestPathId: 'path-b' })?.path).toBe('workspace/artifacts/b/trainer_1/model.keras')
    expect(pickDefaultRunModel(models)?.path).toBe('workspace/artifacts/a/trainer_0/model.keras')
    expect(pickDefaultRunModel([])).toBeNull()
  })
})

describe('labels', () => {
  it('parses csv', () => {
    expect(parseLabelsCsv('yes, no ,,up\ndown')).toEqual(['yes', 'no', 'up', 'down'])
  })
  it('detects order and set mismatches', () => {
    const model = ['down', 'go', 'no', 'stop', 'up', 'yes']
    expect(checkLabelsAgainstModel(model, model)).toEqual({ status: 'ok' })
    expect(checkLabelsAgainstModel(model, ['yes', 'no', 'up', 'down', 'go', 'stop']).status).toBe('order')
    const set = checkLabelsAgainstModel(model, ['yes', 'no'])
    expect(set.status).toBe('set')
    expect(checkLabelsAgainstModel(undefined, ['a']).status).toBe('unknown')
  })
})

describe('summary', () => {
  it('formats kind/format/size/metric', () => {
    expect(inferModelFormat('x/saved_model/')).toBe('saved_model')
    expect(
      runModelSummary({ path: 'm.keras', kind: 'trained', format: 'keras', size_bytes: 2048, metrics: { test_accuracy: 0.5611 } }),
    ).toBe('Trained · keras · 2.0 KB · Test accuracy 56.1%')
  })
})
