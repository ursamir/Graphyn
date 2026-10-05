import { describe, expect, it } from 'vitest'
import {
  activityDetail,
  buildActivityItems,
  homeSummaryLine,
  isExceptionStatus,
  runErrorLine,
  runStatusWord,
  workspaceStatusLabel,
} from './homeActivity'

const ok = (id: string, extra: Record<string, unknown> = {}) => ({ run_id: id, status: 'succeeded', graph_name: 'speech-commands-e2e', ...extra })
const bad = (id: string, error = 'boom', extra: Record<string, unknown> = {}) => ({ run_id: id, status: 'failed', graph_name: 'speech-commands-e2e', error, ...extra })

describe('runStatusWord', () => {
  it('uses the shared vocabulary', () => {
    expect(runStatusWord('SUCCEEDED')).toBe('Done')
    expect(runStatusWord('completed')).toBe('Done')
    expect(runStatusWord('failed')).toBe('Failed')
    expect(runStatusWord('running')).toBe('Running')
    expect(runStatusWord('')).toBe('Unknown')
    expect(isExceptionStatus('succeeded')).toBe(false)
    expect(isExceptionStatus('failed')).toBe(true)
  })
})

describe('activityDetail', () => {
  it('shows best metric and path count for successes', () => {
    const run = ok('a', {
      summary: { primary_metric: { name: 'test_accuracy', value: 0.756 }, paths: [{}, {}] },
    })
    expect(activityDetail(run)).toEqual({ text: 'Test accuracy 75.6% · best of 2 paths', tone: 'muted' })
  })
  it('shows the first error line for failures', () => {
    expect(activityDetail(bad('b', 'KeyError: x\nTraceback …'))).toEqual({ text: 'KeyError: x', tone: 'error' })
    expect(runErrorLine({ error: { message: 'nested' } })).toBe('nested')
  })
  it('prefixes replays', () => {
    expect(activityDetail(ok('c', { replay_of: 'abcdef0123456789' }))?.text).toBe('replay of abcdef01')
  })
  it('returns null with nothing to say', () => {
    expect(activityDetail(ok('d'))).toBeNull()
  })
})

describe('buildActivityItems', () => {
  it('collapses consecutive identical failures', () => {
    const runs = [ok('1'), bad('2'), bad('3'), bad('4'), bad('5', 'other'), ok('6')]
    const items = buildActivityItems(runs)
    expect(items.map((i) => (i.kind === 'run' ? i.run.run_id : `+${i.runs.length}`))).toEqual(['1', '2', '+2', '5', '6'])
  })
  it('expands a group on request and respects max', () => {
    const runs = [bad('1'), bad('2'), bad('3')]
    const items = buildActivityItems(runs, 8, new Set(['more-1']))
    expect(items.map((i) => (i.kind === 'run' ? i.run.run_id : 'more'))).toEqual(['1', '2', '3'])
    expect(buildActivityItems([ok('1'), ok('2'), ok('3')], 2)).toHaveLength(2)
  })
})

describe('homeSummaryLine', () => {
  it('builds one line', () => {
    expect(homeSummaryLine({ pipelines: 1, runs: 8 })).toBe('1 pipeline · 8 runs')
    expect(homeSummaryLine({ pipelines: 3, runs: 30, runsCapped: true })).toBe('3 pipelines · 30+ runs')
    expect(homeSummaryLine({ pipelines: 0, runs: 1, lastRun: { ...ok('x'), created_at: undefined } })).toBe(
      '0 pipelines · 1 run · last run Speech commands (E2E) Done',
    )
  })
})

describe('workspaceStatusLabel', () => {
  it('only says Getting started without runs', () => {
    expect(workspaceStatusLabel('draft', false)).toBe('Getting started')
    expect(workspaceStatusLabel('draft', true)).toBeNull()
    expect(workspaceStatusLabel('draft', false, true)).toBeNull()
    expect(workspaceStatusLabel('ready', true)).toBe('Ready')
  })
})
