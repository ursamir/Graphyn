import { describe, expect, it } from 'vitest'
import { journalToLogEntries } from './journalLog'

describe('journalToLogEntries', () => {
  it('formats journal events like the live stream', () => {
    const out = journalToLogEntries(
      [
        { type: 'pipeline_start', total_nodes: 2, timestamp: '2026-01-01T00:00:00Z' },
        { time: '2026-01-01T00:00:01Z', level: 'INFO', message: '[0] dataset_ingest — cache hit' },
        { type: 'node_progress', node_id: 'trainer_0', epoch: 2, epochs: 10, loss: 0.5 },
        { type: 'node_error', node_id: 'trainer_0', node_type: 'trainer', error: 'boom' },
        { type: 'error', already_reported: true, message: 'boom' },
        { type: 'done' },
      ],
      { labelFor: () => 'Trainer · Path A' },
    )
    expect(out.map((e) => e.level)).toEqual(['info', 'info', 'progress', 'error', 'error'])
    expect(out[0].message).toBe('Pipeline starting · 2 nodes')
    expect(out[2].message).toBe('Trainer · Path A · epoch 2/10 · loss 0.500')
    expect(out[4].message).toBe('Pipeline finished with errors')
    expect(out[2].raw).toContain('node_progress')
  })
  it('caps to the limit', () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ type: 'node_start', node_id: `n${i}` }))
    expect(journalToLogEntries(many, { limit: 5 })).toHaveLength(5)
  })
})

describe('relabelLine', () => {
  it('swaps the generic node name for the path label', async () => {
    const { relabelLine } = await import('./journalLog')
    const ev = { node_id: 'trainer_b66a5330', node_type: 'trainer' }
    expect(relabelLine('Trainer · started', ev, () => 'Trainer · Path B')).toBe('Trainer · Path B · started')
    expect(relabelLine('Trainer · started', ev, () => undefined)).toBe('Trainer · started')
    expect(relabelLine('Other text', ev, () => 'Trainer · Path B')).toBe('Other text')
  })
  it('prefers the backend node_label (description dropped)', async () => {
    const { relabelLine } = await import('./journalLog')
    const ev = { node_id: 'trainer_24212f65', node_type: 'trainer', node_label: 'Trainer · Path C (MobileNet · lr 0.002)' }
    expect(relabelLine('Trainer · started', ev, () => 'Trainer · Path B')).toBe('Trainer · Path C · started')
    expect(relabelLine('Trainer · started', ev)).toBe('Trainer · Path C · started')
  })
})
