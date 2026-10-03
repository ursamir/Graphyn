import { describe, expect, it } from 'vitest'
import {
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
