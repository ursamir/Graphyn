import { describe, expect, it } from 'vitest'
import {
  comparableRegression,
  friendlyArtifactName,
  groupStepsByLane,
  isComparableRun,
  pathTableColumns,
  pathTablePrimaryName,
  pathTableRows,
  pathTiming,
  recordSummaryParts,
  runFailureReason,
  stepPickerOptions,
} from './runOverview'
import type { PathResult } from './runResults'

function path(letter: string, metrics: Record<string, number>, extra: Partial<PathResult> = {}): PathResult {
  const primaryName = ['test_accuracy', 'accuracy'].find((k) => k in metrics)
  return {
    pathId: `path-${letter.toLowerCase()}`,
    letter,
    description: '',
    nodeIds: [`trainer_${letter}`, `eval_${letter}`],
    metrics,
    primary: primaryName ? { name: primaryName, value: metrics[primaryName] } : null,
    ...extra,
  }
}

describe('path comparison table', () => {
  const paths = [
    path('A', { test_accuracy: 0.8, roc_auc: 0.9, loss: 0.4, epochs: 30 }, { description: 'MobileNet · lr 0.002' }),
    path('B', { test_accuracy: 0.867, val_accuracy: 0.85, loss: 0.3 }, { metricsNodeId: 'eval_B' }),
    path('C', {}),
  ]

  it('picks key metric columns (preferred order, no counters, no primary)', () => {
    expect(pathTableColumns(paths, 'test_accuracy')).toEqual(['roc_auc', 'val_accuracy', 'loss'])
    expect(pathTableColumns(paths, 'test_accuracy', 2)).toEqual(['roc_auc', 'val_accuracy'])
  })

  it('builds one row per path with best marker and focus node', () => {
    const primaryName = pathTablePrimaryName(paths)
    expect(primaryName).toBe('test_accuracy')
    const rows = pathTableRows({
      paths,
      columns: ['roc_auc', 'loss'],
      primaryName,
      timingOf: (p) => (p.letter === 'A' ? { trainingMs: 1000, totalMs: 1500 } : null),
    })
    expect(rows.map((r) => r.label)).toEqual(['Path A', 'Path B', 'Path C'])
    expect(rows[0]).toMatchObject({ description: 'MobileNet · lr 0.002', primaryValue: 0.8, values: { roc_auc: 0.9, loss: 0.4 }, trainingMs: 1000, best: false, focusNodeId: 'eval_A' })
    expect(rows[1]).toMatchObject({ primaryValue: 0.867, values: { loss: 0.3 }, best: true, focusNodeId: 'eval_B', trainingMs: null })
    expect(rows[2]).toMatchObject({ primaryValue: null, values: {}, best: false })
  })

  it('never marks best with a single scored path', () => {
    const rows = pathTableRows({ paths: [path('A', { accuracy: 0.5 }), path('B', {})], columns: [], primaryName: 'accuracy' })
    expect(rows.some((r) => r.best)).toBe(false)
  })

  it('sums training and total time per path', () => {
    const d: Record<string, number> = { builder: 10, trainer_1: 2000, eval: 300 }
    const t: Record<string, string> = { builder: 'model_builder', trainer_1: 'trainer', eval: 'evaluator' }
    expect(pathTiming(['builder', 'trainer_1', 'eval', 'missing'], (id) => d[id], (id) => t[id])).toEqual({ trainingMs: 2000, totalMs: 2310 })
    expect(pathTiming(['eval'], (id) => d[id], (id) => t[id])).toEqual({ trainingMs: null, totalMs: 300 })
    expect(pathTiming([], () => null, () => null)).toEqual({ trainingMs: null, totalMs: null })
  })
})

describe('comparable regression', () => {
  const metricOf = (row: Record<string, unknown>) => {
    const m = row.metrics as Record<string, number> | undefined
    return m && typeof m.test_accuracy === 'number' ? { name: 'test_accuracy', value: m.test_accuracy } : null
  }
  const twoPaths = { summary: { paths: [{ path_id: 'path-a' }, { path_id: 'path-b' }] } }
  const rows: Array<Record<string, unknown>> = [
    { run_id: 'cur', graph_name: 'kws', created_at: '2026-10-04T10:00:00Z', ...twoPaths, metrics: { test_accuracy: 0.756 } },
    { run_id: 'other-graph', graph_name: 'edge-deploy', created_at: '2026-10-03T10:00:00Z', metrics: { test_accuracy: 0.99 } },
    { run_id: 'one-path', graph_name: 'kws', created_at: '2026-10-03T09:00:00Z', summary: { paths: [{ path_id: 'path-a' }] }, metrics: { test_accuracy: 0.95 } },
    { run_id: 'same', meta: { graph_name: 'kws' }, created_at: '2026-10-02T10:00:00Z', ...twoPaths, metrics: { test_accuracy: 0.8 } },
    { run_id: 'later', graph_name: 'kws', created_at: '2026-10-05T10:00:00Z', ...twoPaths, metrics: { test_accuracy: 0.9 } },
  ]
  const base = { runId: 'cur', graphName: 'kws', pathCount: 2, createdAt: '2026-10-04T10:00:00Z', current: { name: 'test_accuracy', value: 0.756 }, rows, metricOf }

  it('only compares with earlier runs of the same pipeline and path count', () => {
    const r = comparableRegression({ ...base, backend: null })
    expect(r?.previousRunId).toBe('same')
    expect(r?.delta).toBeCloseTo(-0.044)
  })

  it('drops a backend regression whose previous run is another pipeline', () => {
    const r = comparableRegression({
      ...base,
      backend: { delta: -0.234, previousValue: 0.99, previousRunId: 'other-graph', metricName: 'test_accuracy' },
    })
    expect(r?.previousRunId).toBe('same')
  })

  it('keeps a backend regression when its previous run is comparable', () => {
    const backend = { delta: -0.04, previousValue: 0.8, previousRunId: 'same', metricName: 'test_accuracy' }
    expect(comparableRegression({ ...base, backend })).toBe(backend)
  })

  it('returns null without a comparable run', () => {
    expect(comparableRegression({ ...base, graphName: 'nothing-else', backend: null })).toBeNull()
    expect(comparableRegression({ ...base, graphName: '', backend: null })).toBeNull()
    expect(comparableRegression({ ...base, current: null, backend: null })).toBeNull()
  })

  it('treats unknown path counts as comparable', () => {
    expect(isComparableRun({ graph_name: 'kws' }, { graphName: 'kws', pathCount: 2 })).toBe(true)
    expect(isComparableRun({ graph_name: 'kws', ...twoPaths }, { graphName: 'kws', pathCount: null })).toBe(true)
    expect(isComparableRun({ graph_name: 'kws', ...twoPaths }, { graphName: 'kws', pathCount: 3 })).toBe(false)
  })
})

describe('groupStepsByLane', () => {
  const items = ['ingest', 'features', 'a1', 'a2', 'b1', 'b2', 'b3']
  it('numbers steps within each group', () => {
    const laneOf = new Map([
      ['ingest', 'shared'],
      ['features', 'shared'],
      ['a1', 'A'],
      ['a2', 'A'],
      ['b1', 'B'],
      ['b2', 'B'],
      ['b3', 'B'],
    ])
    const groups = groupStepsByLane(items, (s) => s, { kind: 'fork', branches: [['a1', 'a2'], ['b1', 'b2', 'b3']], laneOf }, new Map([['A', { letter: 'A', description: 'MobileNet · lr 0.002' }]]))
    expect(groups.map((g) => g.label)).toEqual(['Shared', 'Path A (MobileNet · lr 0.002)', 'Path B'])
    expect(groups.map((g) => g.rows.map((r) => r.index))).toEqual([[1, 2], [1, 2], [1, 2, 3]])
  })

  it('linear runs get one unlabeled group', () => {
    const groups = groupStepsByLane(['x', 'y'], (s) => s, { kind: 'linear', branches: [], laneOf: new Map() })
    expect(groups).toEqual([{ key: 'all', label: null, rows: [{ item: 'x', index: 1 }, { item: 'y', index: 2 }] }])
  })
})

describe('friendlyArtifactName', () => {
  it('names compiled untrained models', () => {
    const n = friendlyArtifactName('workspace/runs/x/model_builder_0/compiled_0123456789abcdef0123456789abcdef.keras')
    expect(n).toEqual({ label: 'Untrained model (architecture)', raw: 'compiled_0123456789abcdef0123456789abcdef.keras', renamed: true })
  })
  it('shortens long hex runs and keeps normal names', () => {
    expect(friendlyArtifactName('pred_0123456789abcdef0123.json').label).toBe('pred_01234567….json')
    expect(friendlyArtifactName('model.keras')).toEqual({ label: 'model.keras', raw: 'model.keras', renamed: false })
  })
})

describe('runFailureReason', () => {
  it('reads row / meta / failure shapes, first line, with error type', () => {
    expect(runFailureReason({ error: 'Boom\nTraceback …' })).toBe('Boom')
    expect(runFailureReason({ meta: { error: 'disk full', error_type: 'OSError' } })).toBe('OSError: disk full')
    expect(runFailureReason({ failure: { message: 'no data', error_type: 'ValueError' } })).toBe('ValueError: no data')
    expect(runFailureReason({ status: 'failed' })).toBeNull()
  })
  it('truncates long messages', () => {
    const r = runFailureReason({ error: 'x'.repeat(300) }, 20)
    expect(r?.length).toBe(20)
    expect(r?.endsWith('…')).toBe(true)
  })
})

describe('recordSummaryParts', () => {
  it('summarizes verify state, chain, seed and gaps', () => {
    expect(recordSummaryParts({ hasProve: true, gapCount: 2, chainPosition: 12, seed: 42, verify: { ok: true } })).toEqual({
      verdict: 'Verified ✓',
      tone: 'ok',
      details: ['chain #12', 'seed 42', '2 not recorded'],
    })
    expect(recordSummaryParts({ hasProve: true, gapCount: 0, chainPosition: null, seed: null }).verdict).toBe('Not verified')
    expect(recordSummaryParts({ hasProve: false, gapCount: 1, chainPosition: null, seed: null }).tone).toBe('warn')
    expect(recordSummaryParts({ hasProve: true, gapCount: 0, chainPosition: null, seed: null, verify: { ok: false } }).verdict).toBe(
      'Verification found changes',
    )
  })
})

describe('stepPickerOptions', () => {
  it('groups by lane with path prefixes and drops opaque ids', () => {
    const laneOf = new Map([
      ['ingest', 'shared'],
      ['trainer_b', 'B'],
      ['trainer_a', 'A'],
    ])
    const opts = stepPickerOptions(
      [
        { id: 'ingest', label: 'Dataset Ingest', status: 'completed' },
        { id: 'trainer_a', label: 'Trainer · Path A', status: 'failed' },
        { id: 'trainer_b', label: 'Trainer · Path B' },
        { id: '0123456789abcdef0123456789abcdef', label: 'x' },
      ],
      laneOf,
    )
    expect(opts.map((o) => o.label)).toEqual(['All steps', 'Shared · Dataset Ingest', 'Path A · Trainer', 'Path B · Trainer'])
    expect(opts[1].description).toBe('done')
  })
})
