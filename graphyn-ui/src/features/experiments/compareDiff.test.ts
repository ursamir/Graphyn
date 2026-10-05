import { describe, expect, it } from 'vitest'
import {
  bestValueIndex,
  compareDiffCsv,
  diffSummarySentence,
  formatDiffValue,
  groupSettings,
  metricCell,
  parseCompareDiff,
  resultGroups,
  runColumnTitle,
} from './compareDiff'

const RAW = {
  runs: [
    { run_id: 'aaaaaaaa1111', short: 'aaaaaaaa', name: 'Speech run', started_at: '2026-10-04T08:00:00Z', status: 'succeeded', graph_hash: 'g1', seed: 42, sealed: true },
    { run_id: 'bbbbbbbb2222', name: '', status: 'failed', graph_hash: 'g2', seed: 42, sealed: true },
  ],
  summary: { settings_changed: 2, data_same: true, code_same: true, environment_same: false, graph_same: false, seed_same: true },
  settings: [
    { node_id: 'trainer_a', node_type: 'trainer', node_label: 'Trainer', path_id: 'A', path_label: 'Path A', key: 'epochs', values: [10, 30], present: [true, true], differs: true, default: 10 },
    { node_id: 'trainer_a', node_type: 'trainer', node_label: 'Trainer', path_id: 'A', path_label: 'Path A', key: 'learning_rate', values: [0.001, 0.002], present: [true, true], differs: true },
    { node_id: 'eval_b', node_type: 'evaluator', node_label: 'Evaluator', path_id: 'B', path_label: 'Path B', key: 'k', values: [null, 1], present: [false, true], differs: true },
  ],
  data: [],
  code: [],
  environment: [{ key: 'python', values: ['3.11', '3.12'], differs: true }],
  metrics: {
    paths: [
      { path_id: 'A', path_label: 'Path A · MobileNet', path_labels: ['Path A', 'Path A'], best: [true, false], metric: 'loss', values: [0.4, 0.3], differs: true },
      { path_id: 'A', path_label: 'Path A · MobileNet', path_labels: ['Path A', 'Path A'], best: [true, false], metric: 'test_accuracy', values: [0.756, 0.8], differs: true },
    ],
    headline: [{ metric: 'test_accuracy', values: [0.756, 0.8], path_labels: ['Path A', 'Path A'] }],
    primary_metric: { name: 'test_accuracy', value: 0.8 },
  },
  include_all: false,
}

describe('compare diff', () => {
  it('builds the summary sentence', () => {
    const d = parseCompareDiff(RAW)!
    expect(diffSummarySentence(d.summary)).toBe('2 settings changed · same data · same code · different environment · same seed')
    expect(diffSummarySentence({ ...d.summary, settingsChanged: 0, environmentSame: null })).toBe(
      'same settings · same data · same code · same seed',
    )
    expect(diffSummarySentence({ ...d.summary, settingsChanged: 1 })).toMatch(/^1 setting changed/)
  })

  it('parses runs, primary metric and settings groups', () => {
    const d = parseCompareDiff(RAW)!
    expect(d.primaryMetric).toBe('test_accuracy')
    expect(d.runs[1].short).toBe('bbbbbbbb')
    expect(runColumnTitle(d.runs[0])).toEqual({ short: 'aaaaaaaa', name: 'Speech run', status: 'Done' })
    expect(runColumnTitle(d.runs[1])).toMatchObject({ name: 'Run bbbbbbbb', status: 'Failed' })
    const groups = groupSettings(d.settings)
    expect(groups.map((g) => g.title)).toEqual(['Path A · Trainer', 'Path B · Evaluator'])
    expect(groups[0].rows[0]).toMatchObject({ hasDefault: true, default: 10 })
    expect(groups[0].rows[1].hasDefault).toBe(false)
    expect(groups[1].rows[0].present).toEqual([false, true])
  })

  it('orders results primary-first and picks the best value', () => {
    const d = parseCompareDiff(RAW)!
    const g = resultGroups(d)
    expect(g).toHaveLength(1)
    expect(g[0].rows.map((r) => r.metric)).toEqual(['test_accuracy', 'loss'])
    expect(bestValueIndex('test_accuracy', [0.756, 0.8])).toBe(1)
    expect(bestValueIndex('loss', [0.4, 0.3])).toBe(1)
    expect(bestValueIndex('loss', [0.4, 0.4])).toBeNull()
    expect(bestValueIndex('loss', [0.4, null])).toBeNull()
    expect(metricCell('test_accuracy', 0.756)).toBe('75.6%')
    expect(metricCell('loss', null)).toBe('—')
  })

  it('falls back to headline metrics for single-path runs', () => {
    const d = parseCompareDiff({ ...RAW, metrics: { ...RAW.metrics, paths: [] } })!
    const g = resultGroups(d)
    expect(g[0]).toMatchObject({ pathId: 'run', pathLabel: 'Whole run' })
    expect(g[0].rows[0].differs).toBe(true)
  })

  it('formats values and CSV; rejects empty payloads', () => {
    expect(formatDiffValue(null)).toBe('—')
    expect(formatDiffValue([1, 2])).toBe('[1,2]')
    expect(formatDiffValue('')).toBe('""')
    const csv = compareDiffCsv(parseCompareDiff(RAW)!)
    expect(csv.split('\n')[0]).toBe('section,item,key,aaaaaaaa1111,bbbbbbbb2222')
    expect(csv).toContain('settings,Path A · Trainer,epochs,10,30')
    expect(parseCompareDiff({ runs: [] })).toBeNull()
    expect(parseCompareDiff('x')).toBeNull()
  })
})
