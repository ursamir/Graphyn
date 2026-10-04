import { describe, expect, it } from 'vitest'
import {
  disambiguatedModelTitles,
  findModelForRoute,
  looksLikeNodeId,
  modelDisplayName,
  modelPrimaryMetricText,
  preferredStageKey,
  stageFacts,
  stageRunId,
} from './modelDisplay'

describe('modelDisplayName', () => {
  it('humanizes node-id names and respects display_name', () => {
    expect(looksLikeNodeId('edge_optimizer_0')).toBe(true)
    expect(looksLikeNodeId('speech-commands-dscnn')).toBe(false)
    expect(modelDisplayName({ name: 'edge_optimizer_0' })).toBe('Edge Optimizer model')
    expect(modelDisplayName({ name: 'edge_optimizer_0', display_name: 'Speech KWS' })).toBe('Speech KWS')
    expect(modelDisplayName({ name: 'speech-commands-dscnn' })).toBe('speech-commands-dscnn')
  })
})

describe('stage helpers', () => {
  it('prefers prod, then staging', () => {
    expect(preferredStageKey({ staging: {}, prod: {} })).toBe('prod')
    expect(preferredStageKey({ staging: {} })).toBe('staging')
    expect(preferredStageKey({})).toBeNull()
  })
  it('builds facts only from present fields', () => {
    const facts = stageFacts({
      metrics: { test_accuracy: 0.5611 },
      format: 'keras',
      size_bytes: 2048,
      labels: ['down', 'go'],
    })
    expect(facts.map((f) => f.label)).toEqual(['Test accuracy', 'Format', 'Size', 'Classes'])
    expect(facts[0].value).toBe('56.1%')
    expect(stageFacts({ run_id: 'r' })).toEqual([])
    expect(stageRunId({ run_id: 'a', source_run_id: 'b' })).toBe('b')
    expect(modelPrimaryMetricText({ metrics: { accuracy: 0.9 } })).toBe('Accuracy 90%')
  })
})

describe('disambiguatedModelTitles', () => {
  it('suffixes colliding titles with source run + date, leaves unique ones', () => {
    const rows = [
      { name: 'edge_optimizer_0', stages: { latest: { run_id: 'aaaaaaaa11112222333344445555', created_at: '2026-10-01T10:00:00Z' } } },
      { name: 'edge_optimizer_1', stages: { latest: { run_id: 'bbbbbbbb11112222333344445555', created_at: '2026-10-02T10:00:00Z' } } },
      { name: 'kws', display_name: 'Keyword spotter' },
    ]
    const t = disambiguatedModelTitles(rows)
    expect(t.get('edge_optimizer_0')).toBe('Edge Optimizer model · run aaaaaaaa · 2026-10-01')
    expect(t.get('edge_optimizer_1')).toBe('Edge Optimizer model · run bbbbbbbb · 2026-10-02')
    expect(t.get('kws')).toBe('Keyword spotter')
  })
  it('falls back to the raw name when run/date also collide', () => {
    const t = disambiguatedModelTitles([{ name: 'edge_optimizer_0' }, { name: 'edge_optimizer_1' }])
    expect(t.get('edge_optimizer_0')).toBe('Edge Optimizer model · edge_optimizer_0')
    expect(t.get('edge_optimizer_1')).toBe('Edge Optimizer model · edge_optimizer_1')
  })
})

describe('findModelForRoute', () => {
  it('matches exact then case-insensitive', () => {
    const rows = [{ name: 'KWS-v1' }, { name: 'other' }]
    expect(findModelForRoute(rows, 'KWS-v1')?.name).toBe('KWS-v1')
    expect(findModelForRoute(rows, 'kws-v1')?.name).toBe('KWS-v1')
    expect(findModelForRoute(rows, 'nope')).toBeNull()
    expect(findModelForRoute(rows, '')).toBeNull()
  })
})
