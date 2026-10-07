import { describe, expect, it } from 'vitest'
import type { GraphIR } from '../types/graph'
import {
  exportDestinationHint,
  GENERIC_EXPORT_OUTPUT_DIR,
  isRetargetableExportDir,
  rewritePreparedIngestPath,
  shouldRewritePreparedIngestPath,
  stampProjectOnGraph,
} from './projectStamp'

const LEGACY_ARTIFACT = 'workspace/artifacts/speech-commands/dataset/speech_commands'
const LIBRARY_EXPORT = GENERIC_EXPORT_OUTPUT_DIR

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
    expect(isRetargetableExportDir(LEGACY_ARTIFACT)).toBe(false)
    expect(isRetargetableExportDir('workspace/artifacts/x/out')).toBe(false)
  })
})

describe('exportDestinationHint', () => {
  it('names the workspace Outputs folder for retargetable exporters', () => {
    expect(exportDestinationHint('audio_exporter', 'output_dir', { output_dir: LIBRARY_EXPORT }, 'ws')).toBe(
      'Run writes to workspace/datasets/output/ws/ (next free vN).',
    )
    expect(exportDestinationHint('audio_exporter', 'project', {}, 'ws')).toContain('“ws”')
    expect(exportDestinationHint('audio_exporter', 'project', { project: 'ws' }, 'ws')).toBeNull()
  })

  it('skips other nodes and flags custom folders', () => {
    expect(exportDestinationHint('trainer', 'output_dir', {}, 'ws')).toBeNull()
    expect(exportDestinationHint('audio_exporter', 'output_dir', { output_dir: LEGACY_ARTIFACT }, 'ws')).toContain(
      'Legacy dataset folder',
    )
    expect(exportDestinationHint('audio_exporter', 'output_dir', { output_dir: '/data/out' }, 'ws')).toContain(
      'Custom folder',
    )
  })
})

describe('prepared ingest rewrite', () => {
  it('rewrites the Library default always and legacy artifact paths only on template load', () => {
    expect(shouldRewritePreparedIngestPath(`${LIBRARY_EXPORT}/latest`)).toBe(true)
    expect(shouldRewritePreparedIngestPath(`${LEGACY_ARTIFACT}/v1`)).toBe(false)
    expect(shouldRewritePreparedIngestPath(`${LEGACY_ARTIFACT}/v1`, { legacyIngest: true })).toBe(true)
    expect(shouldRewritePreparedIngestPath('workspace/datasets/input/speech-commands')).toBe(false)
    expect(rewritePreparedIngestPath(`${LIBRARY_EXPORT}/latest`, 'my-test1')).toBe(
      'workspace/datasets/output/my-test1/latest',
    )
    expect(rewritePreparedIngestPath(`${LEGACY_ARTIFACT}/v1`, 'my-test1')).toBeNull()
    expect(rewritePreparedIngestPath(`${LEGACY_ARTIFACT}/v1`, 'my-test1', { legacyIngest: true })).toBe(
      'workspace/datasets/output/my-test1/v1',
    )
  })
})

describe('stampProjectOnGraph', () => {
  it('retargets prepare exporter + train ingest into the workspace Library folder', () => {
    const prepare = graph([
      {
        id: 'exp',
        node_type: 'audio_exporter',
        config: { output_dir: LIBRARY_EXPORT, version_tag: 'v1' },
      },
    ])
    const stampedPrep = stampProjectOnGraph(prepare, 'my-test1')
    expect(cfg(stampedPrep, 'exp')).toMatchObject({
      project: 'my-test1',
      output_dir: 'workspace/datasets/output/my-test1',
      version_tag: 'v1',
    })

    const train = graph([
      {
        id: 'ing',
        node_type: 'dataset_ingest',
        config: { path: `${LIBRARY_EXPORT}/latest` },
      },
    ])
    expect(cfg(stampProjectOnGraph(train, 'my-test1'), 'ing').path).toBe(
      'workspace/datasets/output/my-test1/latest',
    )
  })

  it('rewrites legacy artifact ingest paths when opening old templates', () => {
    const train = graph([
      { id: 'ing', node_type: 'dataset_ingest', config: { path: `${LEGACY_ARTIFACT}/latest` } },
    ])
    expect(cfg(stampProjectOnGraph(train, 'ws', undefined, { legacyIngest: true }), 'ing').path).toBe(
      'workspace/datasets/output/ws/latest',
    )
  })

  it('leaves a user-picked legacy artifact ingest path alone at run time', () => {
    const train = graph([
      { id: 'ing', node_type: 'dataset_ingest', config: { path: `${LEGACY_ARTIFACT}/v3` } },
    ])
    expect(cfg(stampProjectOnGraph(train, 'ws'), 'ing').path).toBe(`${LEGACY_ARTIFACT}/v3`)
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
    const g = graph([
      { id: 'exp', node_type: 'audio_exporter', config: { output_dir: LIBRARY_EXPORT, version_tag: 'v1' } },
    ])
    expect(cfg(stampProjectOnGraph(g, 'p', 'v9'), 'exp').version_tag).toBe('v1')
  })

  it('isolates generic artifact sinks but leaves leftover artifact dataset export dirs alone', () => {
    const g = graph([
      { id: 'cap', node_type: 'caption_export', config: { output_dir: 'workspace/artifacts/x/captions' } },
      { id: 'ds', node_type: 'audio_exporter', config: { output_dir: LEGACY_ARTIFACT } },
    ])
    const stamped = stampProjectOnGraph(g, 'proj')
    expect(cfg(stamped, 'cap').output_dir).toBe('workspace/artifacts/proj/cap')
    // Legacy non-retargetable exporter path is not rewritten (templates should use Library).
    expect(cfg(stamped, 'ds').output_dir).toBe(LEGACY_ARTIFACT)
  })

  it('leaves node configs untouched when no project is active', () => {
    const g = graph([{ id: 'exp', node_type: 'audio_exporter', config: { output_dir: GENERIC_EXPORT_OUTPUT_DIR } }])
    const stamped = stampProjectOnGraph(g, '')
    expect(cfg(stamped, 'exp')).toEqual({ output_dir: GENERIC_EXPORT_OUTPUT_DIR })
  })
})
