import { describe, expect, it } from 'vitest'
import { buildNodeTypePluginMap, summarizeMissing } from './missingPlugins'

const rows = [
  { name: 'trainer', manifest: { name: 'trainer', node_types: ['trainer', 'model_builder'] } },
  { name: 'evaluator', manifest: { name: 'evaluator', node_types: ['Isolated_evaluator'] } },
  { name: 'idx-asr', node_types: ['asr_transcribe'] },
]

describe('missingPlugins', () => {
  it('maps node types to plugin names from manifests and index entries', () => {
    const m = buildNodeTypePluginMap(rows)
    expect(m.get('model_builder')).toBe('trainer')
    expect(m.get('evaluator')).toBe('evaluator')
    expect(m.get('asr_transcribe')).toBe('idx-asr')
  })

  it('labels mapped types as plugins, deduped', () => {
    const s = summarizeMissing(['trainer', 'model_builder'], buildNodeTypePluginMap(rows))
    expect(s.plugins).toEqual(['trainer'])
    expect(s.label).toBe('Needs plugins: trainer')
    expect(s.tooltip).toContain('model_builder (trainer)')
  })

  it('labels unknown node types as missing node types, not plugins', () => {
    const s = summarizeMissing(['asr_transcribe'], new Map())
    expect(s.label).toBe('Missing node types: asr_transcribe')
    expect(s.plugins).toEqual([])
  })

  it('mixes both and truncates', () => {
    const s = summarizeMissing(['trainer', 'a', 'b', 'c', 'd'], buildNodeTypePluginMap(rows), 2)
    expect(s.label).toBe('Needs plugins: trainer · missing node types: a, b +2')
  })
})
