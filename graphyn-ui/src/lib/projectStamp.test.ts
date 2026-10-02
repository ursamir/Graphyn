import { describe, expect, it } from 'vitest'
import type { GraphIR } from '../types/graph'
import { GENERIC_EXPORT_OUTPUT_DIR, isRetargetableExportDir, stampProjectOnGraph } from './projectStamp'

const PHASE1_DIR = 'workspace/artifacts/speech-commands/dataset/speech_commands'
const PHASE2_INGEST = `${PHASE1_DIR}/v1`

function graph(nodes: Array<{ id: string; node_type: string; config: Record<string, unknown> }>): GraphIR {
  return { schema_version: '1.2', metadata: { name: 'g' }, nodes, edges: [] } as unknown as GraphIR
}

function cfg(g: GraphIR, id: string): Record<string, unknown> {
  const n = (g.nodes ?? []).find((x) => x.id === id)
  return (n?.config ?? {}) as Record<string, unknown>
}

describe('isRetargetableExportDir', () => {
  it('accepts empty, the plugin default and Library exports', () => {
    expect(isRetargetableExportDir(undefined)).toBe(true)
    expect(isRetargetableExportDir('')).toBe(true)
    expect(isRetargetableExportDir(GENERIC_EXPORT_OUTPUT_DIR)).toBe(true)
    expect(isRetargetableExportDir('workspace/datasets/output/other')).toBe(true)
  })

  it('rejects explicit artifact paths', () => {
    expect(isRetargetableExportDir(PHASE1_DIR)).toBe(false)
    expect(isRetargetableExportDir('workspace/artifacts/x/out')).toBe(false)
  })
})

describe('stampProjectOnGraph', () => {
  it('keeps the Phase-1 exporter path so the Phase-2 ingest still matches', () => {
    const pre = graph([
      { id: 'exp', node_type: 'audio_exporter', config: { output_dir: PHASE1_DIR, version_tag: 'v1' } },
    ])
    const stamped = stampProjectOnGraph(pre, 'e06-verify-1')
    const c = cfg(stamped, 'exp')
    expect(c.output_dir).toBe(PHASE1_DIR)
    expect(c.project).toBeUndefined() // exporter ignores output_dir once project is set
    expect(`${c.output_dir}/${c.version_tag}`).toBe(PHASE2_INGEST)
    expect(stamped.metadata?.project).toBe('e06-verify-1')

    const train = graph([{ id: 'ing', node_type: 'dataset_ingest', config: { path: PHASE2_INGEST } }])
    expect(cfg(stampProjectOnGraph(train, 'e06-verify-1'), 'ing').path).toBe(PHASE2_INGEST)
  })

  it('retargets a default exporter into the project Library folder', () => {
    const g = graph([
      { id: 'exp', node_type: 'audio_exporter', config: { output_dir: GENERIC_EXPORT_OUTPUT_DIR } },
      { id: 'ver', node_type: 'dataset_versioner', config: {} },
    ])
    const stamped = stampProjectOnGraph(g, 'proj', 'v2')
    expect(cfg(stamped, 'exp')).toMatchObject({
      project: 'proj',
      output_dir: 'workspace/datasets/output/proj',
      version_tag: 'v2',
    })
    expect(cfg(stamped, 'ver')).toMatchObject({ project: 'proj', output_dir: 'workspace/datasets/output/proj' })
  })

  it('does not overwrite an existing version_tag', () => {
    const g = graph([{ id: 'exp', node_type: 'audio_exporter', config: { output_dir: PHASE1_DIR, version_tag: 'v1' } }])
    expect(cfg(stampProjectOnGraph(g, 'p', 'v9'), 'exp').version_tag).toBe('v1')
  })

  it('isolates generic artifact sinks but leaves dataset hand-off trees alone', () => {
    const g = graph([
      { id: 'cap', node_type: 'caption_export', config: { output_dir: 'workspace/artifacts/x/captions' } },
      { id: 'ds', node_type: 'some_writer', config: { output_dir: `${PHASE1_DIR}` } },
    ])
    const stamped = stampProjectOnGraph(g, 'proj')
    expect(cfg(stamped, 'cap').output_dir).toBe('workspace/artifacts/proj/cap')
    expect(cfg(stamped, 'ds').output_dir).toBe(PHASE1_DIR)
  })

  it('leaves node configs untouched when no project is active', () => {
    const g = graph([{ id: 'exp', node_type: 'audio_exporter', config: { output_dir: GENERIC_EXPORT_OUTPUT_DIR } }])
    const stamped = stampProjectOnGraph(g, '')
    expect(cfg(stamped, 'exp')).toEqual({ output_dir: GENERIC_EXPORT_OUTPUT_DIR })
  })
})
