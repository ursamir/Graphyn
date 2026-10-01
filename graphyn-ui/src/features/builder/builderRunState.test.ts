import { beforeEach, describe, expect, it } from 'vitest'
import {
  _resetRememberedOutcomes,
  badgeFromServerStatus,
  decorateNodeData,
  reconcileNodeStatuses,
  rememberRunOutcome,
  rememberedRunOutcome,
  runStartErrorMessage,
  runStartErrorTitle,
  statusesFromEvents,
} from './builderRunState'

describe('execution badge', () => {
  beforeEach(() => _resetRememberedOutcomes())

  it('maps server statuses and never defaults to succeeded', () => {
    expect(badgeFromServerStatus('completed')).toBe('succeeded')
    expect(badgeFromServerStatus('succeeded')).toBe('succeeded')
    expect(badgeFromServerStatus('cancelled')).toBe('cancelled')
    expect(badgeFromServerStatus('failed')).toBe('failed')
    expect(badgeFromServerStatus('running')).toBe('running')
    expect(badgeFromServerStatus(undefined)).toBe('unknown')
    expect(badgeFromServerStatus('weird')).toBe('unknown')
  })

  it('remembers outcomes per run id (not one global flag)', () => {
    rememberRunOutcome('a', 'cancelled')
    rememberRunOutcome('b', 'succeeded')
    expect(rememberedRunOutcome('a')).toBe('cancelled')
    expect(rememberedRunOutcome('b')).toBe('succeeded')
    expect(rememberedRunOutcome('c')).toBeNull()
    expect(rememberedRunOutcome(null)).toBeNull()
  })
})

describe('cancel reconciliation', () => {
  const ids = ['ingest', 'cond', 'seg', 'train']
  const events = [
    { type: 'node_start', node_id: 'ingest' },
    { type: 'node_end', node_id: 'ingest' },
    { type: 'node_start', node_id: 'cond' },
    { type: 'node_end', node_id: 'cond' },
    { type: 'node_start', node_id: 'seg' },
    { type: 'node_end', node_id: 'seg' },
    { type: 'node_start', node_id: 'train' },
  ]

  it('keeps nodes the journal says completed as succeeded on a cancelled run', () => {
    const m = reconcileNodeStatuses(ids, events, null, 'cancelled')
    expect(m.get('seg')).toBe('succeeded')
    expect(m.get('train')).toBe('cancelled')
  })

  it('cancel that 404s because the run already succeeded paints no cancelled nodes', () => {
    const all = [...events, { type: 'node_end', node_id: 'train' }]
    const m = reconcileNodeStatuses(ids, all, null, 'succeeded')
    expect([...m.values()].every((s) => s === 'succeeded')).toBe(true)
  })

  it('never-started nodes read skipped (not run) once the run failed or was cancelled', () => {
    const early = events.slice(0, 2)
    expect(reconcileNodeStatuses(ids, early, null, 'cancelled').get('seg')).toBe('skipped')
    expect(reconcileNodeStatuses(ids, early, null, 'failed').get('seg')).toBe('skipped')
    expect(reconcileNodeStatuses(ids, early, null, 'failed').get('train')).toBe('skipped')
    expect(reconcileNodeStatuses(ids, early, null, 'succeeded').get('seg')).toBe('idle')
    // unknown status: only what the journal says
    const unknown = reconcileNodeStatuses(ids, early, null, 'unknown')
    expect(unknown.get('ingest')).toBe('succeeded')
    expect(unknown.has('seg')).toBe(false)
  })

  it('maps node_index through execution order and ignores running after terminal', () => {
    const m = statusesFromEvents(
      [
        { type: 'node_end', node_index: 1 },
        { type: 'node_start', node_index: 1 },
      ],
      ['a', 'b'],
    )
    expect(m.get('b')).toBe('succeeded')
  })
})

describe('catalog re-decoration', () => {
  const entry = {
    node_type: 'Segmenter',
    label: 'Segmenter',
    category: 'audio',
    runtime: 'python',
    config_schema: {
      properties: {
        window_ms: { type: 'number', default: 1000 },
        hop_ms: { type: 'number', default: 500 },
      },
    },
    input_ports: [{ name: 'samples', data_type: 'AudioSample' }],
    output_ports: [{ name: 'segments', data_type: 'AudioSample' }],
  }

  it('fills catalog data and merges defaults UNDER existing config', () => {
    const data = {
      nodeType: 'Segmenter',
      label: 'Segmenter',
      config: { window_ms: 250 },
      schemaProps: {},
      inputs: [{ name: 'input' }],
      outputs: [{ name: 'output' }, { name: 'segments' }],
      catalogDecorated: false,
    }
    const out = decorateNodeData(data, entry, new Set(), new Set(['segments']))
    expect(out.category).toBe('audio')
    expect(out.runtime).toBe('python')
    expect(out.config).toEqual({ window_ms: 250, hop_ms: 500 })
    expect(Object.keys(out.schemaProps ?? {})).toEqual(['window_ms', 'hop_ms'])
    expect(out.inputs.map((p) => p.name)).toEqual(['samples'])
    expect(out.outputs.map((p) => p.name)).toEqual(['segments'])
    expect(out.outputs[0].data_type).toBe('AudioSample')
    expect(out.catalogDecorated).toBe(true)
  })

  it('keeps an explicit custom label and edge-used placeholder ports', () => {
    const out = decorateNodeData(
      { nodeType: 'Segmenter', label: 'My cutter', config: {}, inputs: [{ name: 'input' }], outputs: [] },
      entry,
      new Set(['input']),
    )
    expect(out.label).toBe('My cutter')
    expect(out.inputs.map((p) => p.name)).toEqual(['samples', 'input'])
  })
})

describe('run start errors', () => {
  it('extracts FastAPI detail shapes', () => {
    expect(runStartErrorMessage({ detail: 'Too many concurrent runs' }, 'x')).toBe('Too many concurrent runs')
    expect(
      runStartErrorMessage({ detail: { code: 'draining', message: 'Control plane is shutting down' } }, 'x'),
    ).toBe('Control plane is shutting down (draining)')
    expect(runStartErrorMessage({ error: { code: 'busy', message: 'Busy' }, detail: null }, 'x')).toBe('Busy')
    expect(runStartErrorMessage(undefined, 'HTTP 503')).toBe('HTTP 503')
    expect(runStartErrorTitle(503)).toMatch(/server busy/)
  })
})
