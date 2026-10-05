import { describe, expect, it } from 'vitest'
import { focusMatchesNode } from '../../lib/format'
import {
  defaultOpenGroups,
  imageOutputsForNode,
  lastLogsForNode,
  orderOutputGroupsByImportance,
  pathGroupSummary,
  pickDefaultOutput,
  stepConfigEntries,
  trackedFilesLabel,
} from './stepDetails'

describe('path group summary', () => {
  it('joins path, description, steps, time and primary metric', () => {
    expect(
      pathGroupSummary({
        letter: 'C',
        description: 'MobileNet · lr 0.002',
        stepCount: 4,
        totalMs: 271_000,
        primary: { name: 'test_accuracy', value: 0.756 },
      }),
    ).toEqual(['Path C', 'MobileNet · lr 0.002', '4 steps', '4m 31s', expect.stringMatching(/75\.6%|0\.756/)])
  })
  it('omits unknown parts', () => {
    expect(pathGroupSummary({ letter: 'A', stepCount: 1 })).toEqual(['Path A', '1 step'])
  })
})

describe('default open groups', () => {
  it('opens shared + best path only', () => {
    const open = defaultOpenGroups({ keys: ['shared', 'A', 'B', 'C'], bestLane: 'C' })
    expect([...open].sort()).toEqual(['C', 'shared'])
  })
  it('opens failed paths instead of the best', () => {
    const open = defaultOpenGroups({ keys: ['shared', 'A', 'B'], bestLane: 'A', failedLanes: ['B'] })
    expect(open.has('B')).toBe(true)
    expect(open.has('A')).toBe(false)
  })
  it('always opens the focused step lane and linear groups', () => {
    expect(defaultOpenGroups({ keys: ['all'] }).has('all')).toBe(true)
    expect(defaultOpenGroups({ keys: ['shared', 'A', 'B'], bestLane: 'A', focusLane: 'B' }).has('B')).toBe(true)
  })
})

describe('step config entries', () => {
  const schema = {
    properties: {
      epochs: { type: 'integer', default: 10 },
      lr: { type: 'number', default: 0.001 },
      batch_size: { type: 'integer', default: 32 },
      arch: { type: 'string' },
    },
  }
  it('flags changed-from-default first, then unknown, then equal, then defaults used', () => {
    const rows = stepConfigEntries({ epochs: 10, lr: 0.002, arch: 'mobilenet', _ui: { x: 1 } }, schema)
    expect(rows.map((r) => r.key)).toEqual(['lr', 'arch', 'epochs', 'batch_size'])
    expect(rows[0]).toMatchObject({ value: '0.002', changed: true, defaultValue: '0.001' })
    expect(rows[1].changed).toBeNull()
    expect(rows[2].changed).toBe(false)
    expect(rows[3]).toMatchObject({ value: '32', fromDefault: true })
  })
  it('works without a schema and formats objects', () => {
    expect(stepConfigEntries({ labels: ['yes', 'no'] }, null)).toEqual([
      { key: 'labels', value: '["yes","no"]', changed: null },
    ])
    expect(stepConfigEntries(undefined, null)).toEqual([])
  })
})

describe('step logs + images', () => {
  it('keeps the last N matching rows and the total', () => {
    const rows = Array.from({ length: 30 }, (_, i) => ({ i, hint: i % 2 ? 'trainer_0' : 'evaluator_0' }))
    const res = lastLogsForNode(rows, 'trainer_0', (r) => r.hint, focusMatchesNode, 5)
    expect(res.total).toBe(15)
    expect(res.rows.map((r) => r.i)).toEqual([21, 23, 25, 27, 29])
  })
  it('lists image outputs of the step, confusion matrix first', () => {
    const files = [
      { name: 'training_curves.png', path: 'a/training_curves.png', node_id: 'evaluator_c' },
      { name: 'confusion_matrix.png', path: 'a/confusion_matrix.png', node_id: 'evaluator_c' },
      { name: 'metrics.json', path: 'a/metrics.json', node_id: 'evaluator_c' },
      { name: 'other.png', path: 'b/other.png', node_id: 'evaluator_a' },
    ]
    expect(imageOutputsForNode(files, 'evaluator_c', focusMatchesNode).map((f) => f.name)).toEqual([
      'confusion_matrix.png',
      'training_curves.png',
    ])
  })
})

describe('run outputs importance', () => {
  const info: Record<string, { nodeType: string; lane: string | null }> = {
    dataset_ingest: { nodeType: 'dataset_ingest', lane: 'shared' },
    feature_extractor: { nodeType: 'mfcc', lane: 'shared' },
    trainer_a: { nodeType: 'trainer', lane: 'A' },
    evaluator_a: { nodeType: 'evaluator', lane: 'A' },
    trainer_c: { nodeType: 'trainer', lane: 'C' },
    evaluator_c: { nodeType: 'evaluator', lane: 'C' },
    edge_optimizer_c: { nodeType: 'edge_optimizer', lane: 'C' },
  }
  it('puts the best path evaluator/trainer/optimizer first and ingest last', () => {
    const order = [
      'dataset_ingest',
      'feature_extractor',
      'trainer_a',
      'evaluator_a',
      'trainer_c',
      'evaluator_c',
      'edge_optimizer_c',
      'run',
    ]
    expect(orderOutputGroupsByImportance(order, (id) => info[id], 'C')).toEqual([
      'evaluator_c',
      'trainer_c',
      'edge_optimizer_c',
      'evaluator_a',
      'trainer_a',
      'feature_extractor',
      'run',
      'dataset_ingest',
    ])
  })
  it('preselects metrics / plot / model of the first important group', () => {
    const groups = [
      [
        { name: 'predictions.csv', path: 'e/predictions.csv' },
        { name: 'confusion_matrix.png', path: 'e/confusion_matrix.png' },
        { name: 'metrics.json', path: 'e/metrics.json' },
      ],
      [{ name: '1.wav', path: 'i/1.wav' }],
    ]
    expect(pickDefaultOutput(groups)?.name).toBe('metrics.json')
    expect(pickDefaultOutput([[{ name: '1.wav', path: 'x' }], [{ name: 'model.tflite', path: 'm' }]])?.name).toBe(
      'model.tflite',
    )
    expect(pickDefaultOutput([[{ name: '1.wav', path: 'x' }]])?.name).toBe('1.wav')
    expect(pickDefaultOutput([])).toBeNull()
  })
  it('labels tracked files', () => {
    expect(trackedFilesLabel(21)).toBe('21 tracked files')
    expect(trackedFilesLabel(0)).toBeNull()
  })
})

describe('verify strip summary', () => {
  it('counts passed checks across groups', async () => {
    const { verifyStripSummary } = await import('./runRecord')
    const item = (state: 'pass' | 'changed') => ({ key: state + Math.random(), group: 'g', label: '', target: '', nodeId: '', state, detail: '' })
    const pass = verifyStripSummary(
      [
        { state: 'pass', items: [item('pass'), item('pass')] },
        { state: 'pass', items: [] },
      ],
      true,
      'ok',
    )
    expect(pass).toMatchObject({ verdict: 'Verified ✓', passed: 3, total: 3, tone: 'ok' })
    const changed = verifyStripSummary([{ state: 'changed', items: [item('pass'), item('changed')] }], false, 'changed')
    expect(changed).toMatchObject({ passed: 1, total: 2, tone: 'warn' })
    expect(verifyStripSummary([], null, 'unsealed').tone).toBe('warn')
  })
})
