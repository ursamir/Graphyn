import { describe, expect, it } from 'vitest'
import {
  branchContextByNode,
  branchingNodesOf,
  graphHasMlPaths,
  handledErrorNodes,
  handledErrorText,
  handledErrorsLabel,
  isMlMultiPath,
  skipReasonText,
  skipReasonsByNode,
  splitRunErrors,
  stepDisplayNames,
  stripPathSuffix,
} from './runFlow'
import { computePipelineShape, topoOrderGraph } from './runNodes'
import { groupStepsByLane } from './runOverview'
import { fallbackPathResults, type PathResult } from './runResults'
import { resilienceByNode } from './runWorkflow'

// qa-workflow/order_router (coordinator's real webhook workflow).
const workflow = {
  nodes: [
    { id: 'hook', node_type: 'webhook_trigger' },
    { id: 'check', node_type: 'if_switch' },
    { id: 'gate', node_type: 'hitl_approve' },
    { id: 'approved', node_type: 'set_map' },
    { id: 'rejected', node_type: 'set_map' },
    { id: 'auto', node_type: 'set_map' },
    { id: 'lookup', node_type: 'http_request' },
    { id: 'bad_call', node_type: 'http_request', on_error: { mode: 'route' } },
    { id: 'caught', node_type: 'set_map' },
    { id: 'after_bad', node_type: 'set_map' },
  ],
  edges: [
    { src_id: 'hook', src_port: 'body', dst_id: 'check', dst_port: 'value' },
    { src_id: 'check', src_port: 'true', dst_id: 'gate', dst_port: 'input' },
    { src_id: 'check', src_port: 'false', dst_id: 'auto', dst_port: 'input' },
    { src_id: 'gate', src_port: 'approved', dst_id: 'approved', dst_port: 'input' },
    { src_id: 'gate', src_port: 'rejected', dst_id: 'rejected', dst_port: 'input' },
    { src_id: 'hook', src_port: 'body', dst_id: 'lookup', dst_port: 'body' },
    { src_id: 'hook', src_port: 'body', dst_id: 'bad_call', dst_port: 'body' },
    { src_id: 'bad_call', src_port: 'error', dst_id: 'caught', dst_port: 'input' },
    { src_id: 'bad_call', src_port: 'output', dst_id: 'after_bad', dst_port: 'input' },
  ],
}

// Example 06-style ML sweep: shared ingest → dataset_builder, then 3 trained paths.
const mlGraph = {
  nodes: [
    { id: 'ingest', node_type: 'dataset_ingest' },
    { id: 'db', node_type: 'dataset_builder' },
    ...['a', 'b', 'c'].flatMap((p) => [
      { id: `mb_${p}`, node_type: 'model_builder' },
      { id: `tr_${p}`, node_type: 'trainer' },
      { id: `ev_${p}`, node_type: 'evaluator' },
    ]),
  ],
  edges: [
    { src_id: 'ingest', dst_id: 'db' },
    ...['a', 'b', 'c'].flatMap((p) => [
      { src_id: 'db', dst_id: `mb_${p}` },
      { src_id: `mb_${p}`, dst_id: `tr_${p}` },
      { src_id: `tr_${p}`, dst_id: `ev_${p}` },
    ]),
  ],
}

const typeOf = (g: { nodes: Array<{ id: string; node_type: string }> }) => (id: string) =>
  g.nodes.find((n) => n.id === id)?.node_type ?? null

describe('isMlMultiPath', () => {
  it('workflow fan-out (if_switch / approval / error branch) is not an ML multi-path run', () => {
    const order = topoOrderGraph(workflow)
    const shape = computePipelineShape(order, workflow.edges)
    expect(shape.kind).not.toBe('linear') // the raw shape still forks…
    const paths = fallbackPathResults({ shape, graphNodes: workflow.nodes, metricsByNode: {} })
    expect(paths.length).toBeGreaterThan(1)
    // …but no path carries metrics and no branch trains → no Path chrome.
    expect(isMlMultiPath({ shape, paths, nodeTypeOf: typeOf(workflow) })).toBe(false)
    expect(graphHasMlPaths(shape, typeOf(workflow))).toBe(false)
  })

  it('Example 06 ML run (3 paths with metrics) keeps Shared + Path A/B/C grouping', () => {
    const order = topoOrderGraph(mlGraph)
    const shape = computePipelineShape(order, mlGraph.edges)
    expect(shape.kind).toBe('fork')
    const metricsByNode = { ev_a: { accuracy: 0.81 }, ev_b: { accuracy: 0.9 }, ev_c: { accuracy: 0.86 } }
    const paths = fallbackPathResults({ shape, graphNodes: mlGraph.nodes, metricsByNode })
    expect(paths.filter((p) => p.primary)).toHaveLength(3)
    expect(isMlMultiPath({ shape, paths, nodeTypeOf: typeOf(mlGraph) })).toBe(true)
    const groups = groupStepsByLane(order, (id) => id, shape)
    expect(groups.map((g) => g.label)).toEqual(['Shared', 'Path A', 'Path B', 'Path C'])
    expect(groups[1].rows.map((r) => r.item)).toEqual(['mb_a', 'tr_a', 'ev_a'])
  })

  it('a live ML run (no metrics yet) is still multi-path by its trainer branches', () => {
    const shape = computePipelineShape(topoOrderGraph(mlGraph), mlGraph.edges)
    const paths: PathResult[] = []
    expect(isMlMultiPath({ shape, paths, nodeTypeOf: typeOf(mlGraph) })).toBe(true)
  })

  it('linear graphs are never multi-path', () => {
    const shape = computePipelineShape(['a', 'b'], [{ src_id: 'a', dst_id: 'b' }])
    expect(isMlMultiPath({ shape, paths: [], nodeTypeOf: () => 'trainer' })).toBe(false)
  })
})

describe('step display names', () => {
  const catalog: Record<string, string> = {
    webhook_trigger: 'Webhook Trigger',
    if_switch: 'IF Switch',
    hitl_approve: 'Hitl Approve',
    set_map: 'Set / Map',
    http_request: 'HTTP Request',
  }
  const names = stepDisplayNames(workflow.nodes, (t) => catalog[t] ?? t)

  it('shared types show the node id with the type as secondary text', () => {
    expect(names.get('approved')).toEqual({ title: 'approved', subtitle: 'Set / Map' })
    expect(names.get('lookup')).toEqual({ title: 'lookup', subtitle: 'HTTP Request' })
  })
  it('a unique type uses the catalog label, id as secondary text', () => {
    expect(names.get('check')).toEqual({ title: 'IF Switch', subtitle: 'check' })
    expect(names.get('gate')).toEqual({ title: 'Hitl Approve', subtitle: 'gate' })
  })
  it('an IR label wins; a label equal to the type label does not count', () => {
    const m = stepDisplayNames(
      [
        { id: 'a', node_type: 'set_map', label: 'Mark approved' },
        { id: 'b', node_type: 'set_map', label: 'Set / Map' },
        { id: 'if_switch_0', node_type: 'if_switch' },
      ],
      (t) => catalog[t] ?? t,
    )
    expect(m.get('a')).toEqual({ title: 'Mark approved', subtitle: 'Set / Map' })
    expect(m.get('b')).toEqual({ title: 'b', subtitle: 'Set / Map' })
    expect(m.get('if_switch_0')).toEqual({ title: 'IF Switch', subtitle: '' })
  })
  it('strips backend path suffixes', () => {
    expect(stripPathSuffix('Http request · Path C')).toBe('Http request')
    expect(stripPathSuffix('Trainer · Path B (MobileNet)')).toBe('Trainer')
    expect(stripPathSuffix('Lookup')).toBe('Lookup')
  })
})

describe('skip reasons', () => {
  it('reads node_skip reasons in plain words', () => {
    expect(skipReasonText('upstream_skipped')).toBe('branch not taken')
    expect(skipReasonText('all_inputs_unproduced')).toBe('branch not taken')
    expect(skipReasonText('condition_false')).toBe('condition false')
    expect(skipReasonText('resumed_from_checkpoint')).toBe('reused from checkpoint')
    expect(skipReasonText('excluded_from_partial_execution')).toBe('not part of this partial run')
    expect(skipReasonText('')).toBe('not run')
    expect(skipReasonText('some_new_reason')).toBe('some new reason')
  })
  it('collects reasons per node (journal rows may wrap the event JSON)', () => {
    const m = skipReasonsByNode([
      { type: 'node_skip', node_id: 'auto', reason: 'all_inputs_unproduced' },
      { message: JSON.stringify({ type: 'node_skip', node_id: 'rejected', reason: 'upstream_skipped' }) },
      { type: 'node_end', node_id: 'gate' },
    ])
    expect([...m.entries()]).toEqual([
      ['auto', 'all_inputs_unproduced'],
      ['rejected', 'upstream_skipped'],
    ])
  })
})

describe('branch context', () => {
  it('names the branch a step hangs off', () => {
    const { branching, errorPorts } = branchingNodesOf(workflow.nodes)
    const ctx = branchContextByNode(workflow.edges, { branchingNodes: branching, errorPorts })
    expect(ctx.get('gate')).toBe('check → true')
    expect(ctx.get('auto')).toBe('check → false')
    expect(ctx.get('approved')).toBe('gate → approved')
    expect(ctx.get('caught')).toBe('bad_call → error')
    expect(ctx.get('after_bad')).toBe('bad_call → output')
    // hook fans the same port out — not a branch.
    expect(ctx.has('lookup')).toBe(false)
    expect(ctx.has('check')).toBe(false)
  })
})

describe('handled errors', () => {
  const events = [
    { type: 'node_start', node_id: 'bad_call' },
    {
      type: 'node_error_routed',
      node_id: 'bad_call',
      port: 'error',
      error_type: 'HTTPError',
      error: '404',
      message: "failure routed to port 'error': HTTPError",
    },
  ]
  const resilience = resilienceByNode(events)
  const handled = handledErrorNodes(resilience)

  it('routed / continued failures are handled', () => {
    expect([...handled]).toEqual(['bad_call'])
    expect(handledErrorText(resilience.get('bad_call'))).toBe('Failed → routed to error branch')
    expect(handledErrorText({ retries: [], routed: null, continued: { errorType: '', error: '', attempt: 1 } })).toBe(
      'Failed → run continued',
    )
    expect(handledErrorText(null)).toBe('')
    expect(handledErrorsLabel(1)).toBe('1 handled error')
    expect(handledErrorsLabel(2)).toBe('2 handled errors')
  })

  it('splits the debug error lines: handled lines leave the red banner and count', () => {
    const split = splitRunErrors({
      errorCount: 2,
      recentErrors: [
        { level: 'ERROR', message: "failure routed to port 'error': HTTPError" },
        { level: 'ERROR', node_id: 'bad_call', message: 'HTTP 404 error from https://example.invalid' },
      ],
      handled,
    })
    expect(split.unhandledCount).toBe(0)
    expect(split.unhandledRecent).toEqual([])
    expect(split.handledRecent).toHaveLength(2)
    expect(split.handledCount).toBe(1)
  })

  it('keeps real errors red', () => {
    const split = splitRunErrors({
      errorCount: 3,
      recentErrors: [
        { level: 'ERROR', node_id: 'lookup', message: 'boom' },
        { message: JSON.stringify({ type: 'node_error_routed', node_id: 'bad_call' }) },
      ],
      handled,
    })
    expect(split.unhandledCount).toBe(2)
    expect(split.unhandledRecent).toHaveLength(1)
  })
})
