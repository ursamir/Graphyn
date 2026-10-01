import { describe, expect, it } from 'vitest'
import { extractRunFailure, failureProposalSummary, pipelineNodesFromRun, topoOrderGraph } from './runNodes'

const graph = {
  // deliberately not in topological order
  nodes: [
    { id: 'exp', node_type: 'AudioExporter' },
    { id: 'ingest', node_type: 'DatasetIngest' },
    { id: 'seg', node_type: 'Segmenter', label: 'My Segmenter' },
    { id: 'cond', node_type: 'AudioConditioner' },
  ],
  edges: [
    { src_id: 'ingest', dst_id: 'cond' },
    { src_id: 'cond', dst_id: 'seg' },
    { src_id: 'seg', dst_id: 'exp' },
  ],
}

describe('pipelineNodesFromRun', () => {
  it('lists every graph node in execution order, not-run → skipped on a failed run', () => {
    const events = [
      { type: 'node_start', node_id: 'ingest' },
      { type: 'node_end', node_id: 'ingest' },
      { type: 'node_start', node_id: 'cond' },
      { type: 'node_error', node_id: 'cond', error: 'Sample rate should be over 0' },
    ]
    const items = pipelineNodesFromRun({ graph, events, runStatus: 'failed' })
    expect(items.map((i) => [i.id, i.status])).toEqual([
      ['ingest', 'succeeded'],
      ['cond', 'failed'],
      ['seg', 'skipped'],
      ['exp', 'skipped'],
    ])
    expect(items[2].label).toBe('My Segmenter')
  })
  it('cancelled run: in-flight node cancelled, rest skipped; live run leaves them blank', () => {
    const events = [{ type: 'node_start', node_id: 'ingest' }]
    expect(pipelineNodesFromRun({ graph, events, runStatus: 'cancelled' }).map((i) => i.status)).toEqual([
      'cancelled',
      'skipped',
      'skipped',
      'skipped',
    ])
    expect(pipelineNodesFromRun({ graph, events, runStatus: 'running' }).map((i) => i.status)).toEqual([
      'running',
      undefined,
      undefined,
      undefined,
    ])
  })
  it('falls back to node_stats then journal order without a graph', () => {
    const items = pipelineNodesFromRun({
      nodeStats: [
        { node_id: 'b', node_index: 1, status: 'completed' },
        { node_id: 'a', node_index: 0, status: 'completed' },
      ],
      events: [{ type: 'node_start', node_id: 'c' }],
      runStatus: 'failed',
    })
    expect(items.map((i) => [i.id, i.status])).toEqual([
      ['a', 'succeeded'],
      ['b', 'succeeded'],
      ['c', 'failed'],
    ])
  })
  it('topological order is stable for parallel branches', () => {
    const g = {
      nodes: [{ id: 'a' }, { id: 'c' }, { id: 'b' }, { id: 'd' }],
      edges: [
        { src_id: 'a', dst_id: 'b' },
        { src_id: 'a', dst_id: 'c' },
        { src_id: 'b', dst_id: 'd' },
        { src_id: 'c', dst_id: 'd' },
      ],
    }
    expect(topoOrderGraph(g)).toEqual(['a', 'c', 'b', 'd'])
  })
})

describe('extractRunFailure', () => {
  it('reads the node error from the event error field, not message', () => {
    const f = extractRunFailure({
      events: [
        { type: 'node_start', node_id: 'cond', message: 'starting' },
        { type: 'node_error', node_id: 'cond', node_type: 'AudioConditioner', error: 'Sample rate should be over 0' },
        { type: 'error', error: 'Sample rate should be over 0' },
      ],
    })
    expect(f).toEqual({ nodeId: 'cond', nodeType: 'AudioConditioner', error: 'Sample rate should be over 0' })
    expect(failureProposalSummary('dc0b784a-1234', f)).toBe(
      'Fix failed run dc0b784a at node cond (AudioConditioner): Sample rate should be over 0',
    )
  })
  it('parses JSON-in-message rows and falls back to detail / debug', () => {
    expect(
      extractRunFailure({ events: [{ message: JSON.stringify({ type: 'node_error', node_id: 'x', error_message: 'bad' }) }] }),
    ).toMatchObject({ nodeId: 'x', error: 'bad' })
    expect(extractRunFailure({ events: [], detail: { error: 'top level' } })?.error).toBe('top level')
    expect(extractRunFailure({ debug: { recent_errors: [{ message: 'from debug', node_id: 'n' }] } })).toMatchObject({
      nodeId: 'n',
      error: 'from debug',
    })
    expect(extractRunFailure({})).toBeNull()
    expect(failureProposalSummary('abcdef0123', null)).toContain('no error message was recorded')
  })
})
