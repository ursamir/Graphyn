import { describe, expect, it } from 'vitest'
import { buildGraphFromCanvas } from '../../types/graph'
import {
  buildRunExtras,
  checkCondition,
  conditionChipText,
  errorHandlingSummary,
  errorPortOf,
  needsRunDialog,
  onErrorFromIr,
  onErrorToIr,
  outputsWithErrorPort,
  portCaptions,
  retryFromIr,
  retryToIr,
  runInputsSpec,
} from './workflowIr'

describe('on_error / retry IR round-trip', () => {
  it('reads and writes on_error (fail is the omitted default)', () => {
    expect(onErrorFromIr(undefined)).toBeNull()
    expect(onErrorFromIr({ mode: 'fail' })).toBeNull()
    expect(onErrorFromIr({ mode: 'continue' })).toEqual({ mode: 'continue' })
    expect(onErrorFromIr({ mode: 'route' })).toEqual({ mode: 'route', port: 'error' })
    expect(onErrorFromIr({ mode: 'route', port: 'oops' })).toEqual({ mode: 'route', port: 'oops' })
    expect(onErrorToIr({ mode: 'fail' })).toBeNull()
    expect(onErrorToIr({ mode: 'route', port: 'bad port!' })).toEqual({ mode: 'route', port: 'error' })
    expect(errorPortOf({ mode: 'route', port: 'oops' })).toBe('oops')
    expect(errorPortOf({ mode: 'continue' })).toBeNull()
  })
  it('clamps retry and drops defaults', () => {
    expect(retryFromIr({ max_attempts: 50, backoff_s: -1, on: 'timeout' })).toEqual({ max_attempts: 20, backoff_s: 0, on: ['timeout'] })
    expect(retryFromIr({})).toBeNull()
    expect(retryToIr({ max_attempts: 3, backoff_s: 2, max_backoff_s: 60, on: ['exception'] })).toEqual({ max_attempts: 3, backoff_s: 2 })
    expect(retryToIr({ max_attempts: 2, on: ['exception', 'timeout'] })).toEqual({ max_attempts: 2, on: ['exception', 'timeout'] })
    expect(retryToIr(null)).toBeNull()
  })
  it('buildGraphFromCanvas writes on_error/retry only when set and bumps to IR 1.3', () => {
    const node = (id: string, extra: Record<string, unknown> = {}) => ({
      id,
      data: { nodeType: 'http_request', config: {}, ...extra },
    })
    const plain = buildGraphFromCanvas([node('a')], [], 1, 'p')
    expect(plain.schema_version).toBe('1.1')
    expect('on_error' in plain.nodes[0]).toBe(false)
    const g = buildGraphFromCanvas(
      [node('a', { onError: { mode: 'route', port: 'error' }, retry: { max_attempts: 3, backoff_s: 1 } }), node('b')],
      [{ source: 'a', target: 'b', sourceHandle: 'error::bottom', targetHandle: 'input', data: { condition: '  ' } }],
      1,
      'p',
    )
    expect(g.schema_version).toBe('1.3')
    expect(g.nodes[0].on_error).toEqual({ mode: 'route', port: 'error' })
    expect(g.nodes[0].retry).toEqual({ max_attempts: 3, backoff_s: 1 })
    expect(g.edges[0]).toMatchObject({ src_port: 'error', condition: null })
  })
  it('adds a flagged error port in route mode without duplicating native ones', () => {
    expect(outputsWithErrorPort([{ name: 'output' }], { mode: 'route' })).toEqual([
      { name: 'output' },
      { name: 'error', data_type: 'error', isError: true },
    ])
    const native = outputsWithErrorPort([{ name: 'output' }, { name: 'error' }], { mode: 'route' })
    expect(native).toHaveLength(2)
    expect(native[1].isError).toBe(true)
    expect(outputsWithErrorPort([{ name: 'output' }], null)).toEqual([{ name: 'output' }])
  })
  it('summarizes the policy for the inspector', () => {
    expect(errorHandlingSummary(null, null)).toBe('Fail run')
    expect(errorHandlingSummary({ mode: 'route' }, { max_attempts: 3, backoff_s: 5 })).toBe(
      'Route to error branch · up to 3 attempts (5 s back-off)',
    )
  })
})

describe('branch port captions', () => {
  it('labels branch nodes and multi-output nodes', () => {
    expect(portCaptions('if_switch', [{ name: 'true' }, { name: 'false' }])).toEqual([
      { name: 'true', tone: 'ok' },
      { name: 'false', tone: 'bad' },
    ])
    expect(portCaptions('hitl_approve', [{ name: 'approved' }, { name: 'rejected' }])?.map((c) => c.tone)).toEqual(['ok', 'bad'])
    expect(portCaptions('http_request', [{ name: 'output' }])).toBeNull()
    expect(portCaptions('http_request', [{ name: 'output' }, { name: 'error', isError: true }])?.[1].tone).toBe('bad')
  })
})

describe('edge conditions', () => {
  it('builds a short chip label', () => {
    expect(conditionChipText(`output["score"] >= 0.8`)).toBe('score >= 0.8')
    expect(conditionChipText('')).toBe('')
    expect(conditionChipText(`len(output['items']) > 10 and output['ok'] == True`, 20)).toBe('len(items) > 10 and…')
  })
  it('accepts the server whitelist and rejects obvious mistakes', () => {
    expect(checkCondition(`len(output["output"]) > 10 and not output["flag"]`)).toBeNull()
    expect(checkCondition(`output["a"]["b"] != None or output["n"] % 2 == 0`)).toBeNull()
    expect(checkCondition(`output["x"] = 1`)).toMatch(/==/)
    expect(checkCondition(`output.x > 1`)).toMatch(/Attribute/)
    expect(checkCondition(`foo > 1`)).toMatch(/Unknown name/)
    expect(checkCondition(`len(output["x"] > 1`)).toMatch(/Unclosed/)
    expect(checkCondition(`output["x" > 1`)).toMatch(/Unclosed/)
    expect(checkCondition(`output["x"] >`)).toMatch(/incomplete/)
    expect(checkCondition('x'.repeat(501))).toMatch(/Too long/)
  })
})

describe('run inputs', () => {
  const graph = {
    nodes: [
      { id: 'hook', node_type: 'webhook_trigger', config: { sample_body: { a: 1 } } },
      { id: 'n', node_type: 'http_request', config: {} },
    ],
    parameters: { limit: { type: 'int', default: 5, description: 'max' }, flag: { type: 'bool', default: false } },
  }
  it('detects what the Run dialog needs', () => {
    const spec = runInputsSpec(graph)
    expect(spec.webhooks).toEqual([{ nodeId: 'hook', label: 'hook', sampleBody: { a: 1 } }])
    expect(spec.parameters.map((p) => p.name)).toEqual(['limit', 'flag'])
    expect(needsRunDialog(spec)).toBe(true)
    expect(needsRunDialog(runInputsSpec({ nodes: [{ id: 'x', node_type: 'a' }], parameters: {} }))).toBe(false)
  })
  it('builds inputs/parameters and reports bad values', () => {
    const spec = runInputsSpec(graph)
    const ok = buildRunExtras(spec, { hook: '{"b":2}' }, { limit: '5', flag: 'true' })
    expect(ok.errors).toEqual({})
    // limit unchanged from the default → not sent.
    expect(ok.extras).toEqual({ inputs: { hook: { body: { b: 2 } } }, parameters: { flag: true } })
    const bad = buildRunExtras(spec, { hook: '{oops' }, { limit: '1.5' })
    expect(Object.keys(bad.errors).sort()).toEqual(['body:hook', 'param:limit'])
  })
})
