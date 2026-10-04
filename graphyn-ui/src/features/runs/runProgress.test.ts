import { describe, expect, it } from 'vitest'
import {
  collapseProgressRows,
  finishedNodeIds,
  formatProgressLine,
  latestProgressByNode,
  parseProgress,
  progressBadgeText,
  progressSeries,
  sparklinePoints,
} from './runProgress'

const ev = (epoch: number, extra: Record<string, unknown> = {}) => ({
  type: 'node_progress',
  node_id: 'trainer_0',
  node_type: 'trainer',
  epoch,
  epochs: 30,
  loss: 1 / epoch,
  val_accuracy: 0.5 + epoch / 100,
  ...extra,
})

describe('parseProgress', () => {
  it('parses objects and JSON strings, derives pct', () => {
    const p = parseProgress(JSON.stringify(ev(3)))
    expect(p?.nodeId).toBe('trainer_0')
    expect(p?.pct).toBeCloseTo(10)
    expect(parseProgress({ type: 'node_end', node_id: 'x' })).toBeNull()
    expect(parseProgress({ type: 'node_progress' })).toBeNull()
    expect(parseProgress(ev(1, { pct: 42 }))?.pct).toBe(42)
  })
  it('formats a compact line', () => {
    expect(formatProgressLine(parseProgress(ev(3))!, 'Trainer · Path A')).toBe(
      'Trainer · Path A · epoch 3/30 · loss 0.333 · val acc 53%',
    )
    expect(progressBadgeText(parseProgress(ev(3))!)).toBe('epoch 3/30 · val acc 53%')
    expect(formatProgressLine(parseProgress({ type: 'node_progress', node_id: 'a', message: 'warming up' })!)).toBe('warming up')
  })
})

describe('collapse', () => {
  it('keeps one entry per node with history; other rows untouched', () => {
    const rows = [{ m: 'start' }, ev(1), { m: 'other' }, ev(2), ev(3), { ...ev(1), node_id: 'trainer_1' }]
    const out = collapseProgressRows(rows, (r) => r)
    expect(out.map((o) => o.kind)).toEqual(['row', 'progress', 'row', 'progress'])
    const first = out[1]
    expect(first.kind === 'progress' && first.progress.epoch).toBe(3)
    expect(first.kind === 'progress' && first.count).toBe(3)
    expect(first.kind === 'progress' && progressSeries(first.history)?.name).toBe('val acc')
  })
  it('latest per node minus finished', () => {
    const rows = [ev(1), ev(2), { type: 'node_end', node_id: 'trainer_0' }]
    expect(latestProgressByNode(rows).get('trainer_0')?.epoch).toBe(2)
    expect(finishedNodeIds(rows).has('trainer_0')).toBe(true)
  })
  it('sparkline points span the box', () => {
    expect(sparklinePoints([0, 1], 10, 4)).toBe('0.0,4.0 10.0,0.0')
    expect(sparklinePoints([1], 10, 4)).toBe('')
  })
})
