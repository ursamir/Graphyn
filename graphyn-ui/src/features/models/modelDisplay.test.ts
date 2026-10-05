import { describe, expect, it } from 'vitest'
import {
  disambiguatedModelTitles,
  findModelForRoute,
  looksLikeNodeId,
  modelDisplayName,
  modelPrimaryMetricText,
  modelRowSubtitle,
  modelStageSummary,
  modelUsedInRuns,
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

describe('modelRowSubtitle / modelStageSummary', () => {
  const row = {
    name: 'kws',
    stages: {
      prod: { run_id: 'aaaaaaaa11112222333344445555', created_at: '2026-10-01T10:00:00Z', metrics: { test_accuracy: 0.739 } },
      staging: { source_run_id: 'bbbbbbbb11112222333344445555', created_at: '2026-10-03T10:00:00Z', metrics: { test_accuracy: 0.756 } },
    },
  }
  it('shows the preferred stage run short id and date', () => {
    expect(modelRowSubtitle(row)).toEqual({ runId: 'aaaaaaaa11112222333344445555', shortId: 'aaaaaaaa', date: '2026-10-01' })
    expect(modelRowSubtitle({ name: 'x' })).toEqual({ runId: null, shortId: null, date: '' })
  })
  it('lists both stages with metrics', () => {
    expect(modelStageSummary(row.stages)).toBe('Production 73.9% · Staging 75.6%')
    expect(modelStageSummary({ staging: { run_id: 'r' } })).toBe('Staging')
    expect(modelStageSummary({ latest: { run_id: 'r' } })).toBe('')
    expect(modelStageSummary(null)).toBe('')
  })
})


describe('defaultModelName', () => {
  it('prefers a production model, then the newest', async () => {
    const { defaultModelName } = await import('./modelDisplay')
    expect(defaultModelName([])).toBeNull()
    expect(
      defaultModelName([
        { name: 'old', stages: { staging: { run_id: 'a' } }, updated_at: '2026-10-02' },
        { name: 'new', stages: { staging: { run_id: 'b' } }, updated_at: '2026-10-04' },
      ]),
    ).toBe('new')
    expect(
      defaultModelName([
        { name: 'new', stages: { staging: { run_id: 'b' } }, updated_at: '2026-10-04' },
        { name: 'shipped', stages: { prod: { run_id: 'c' } }, updated_at: '2026-10-01' },
      ]),
    ).toBe('shipped')
  })
})

describe('modelUsedInRuns', () => {
  const rows = [
    { run_id: 'aaaaaaaaaaaaaaaa', created_at: '2026-01-01T00:00:00Z', graph_name: 'ship', lineage_request: { model: { name: 'kws', stage: 'prod' } } },
    { run_id: 'bbbbbbbbbbbbbbbb', created_at: '2026-02-01T00:00:00Z', display_name: 'Ship v2', lineage_request: { model: { name: 'kws' } } },
    { run_id: 'cccccccccccccccc', created_at: '2026-03-01T00:00:00Z', lineage_request: { model: { name: 'other' } } },
    { run_id: 'dddddddddddddddd', created_at: '2026-04-01T00:00:00Z', lineage: { models: [{ name: 'kws', stage: 'staging' }] } },
    { run_id: 'eeeeeeeeeeeeeeee', created_at: '2026-05-01T00:00:00Z' },
  ]
  it('lists runs whose lineage names the model, newest first', () => {
    const used = modelUsedInRuns(rows, 'kws')
    expect(used.map((u) => u.runId)).toEqual(['dddddddddddddddd', 'bbbbbbbbbbbbbbbb', 'aaaaaaaaaaaaaaaa'])
    expect(used[0].stage).toBe('staging')
    expect(used[1].label).toBe('Ship v2')
    expect(used[2]).toMatchObject({ stage: 'prod', label: 'ship' })
  })
  it('excludes the source run and handles empty input', () => {
    expect(modelUsedInRuns(rows, 'kws', { excludeRunIds: ['dddddddddddddddd'] })).toHaveLength(2)
    expect(modelUsedInRuns(null, 'kws')).toEqual([])
    expect(modelUsedInRuns(rows, '')).toEqual([])
  })
})
