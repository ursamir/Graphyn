import { describe, expect, it } from 'vitest'
import { canonicalJson, describeDriftChange, diffGraphs, parsePipelineDrift, unscopeRunPaths } from './graphDrift'

const RUN = {
  nodes: [
    { id: 'ingest_0', node_type: 'dataset_ingest', config: { path: 'a' } },
    { id: 'trainer_0', node_type: 'trainer', config: { epochs: 50 } },
  ],
  edges: [{ src_id: 'ingest_0', src_port: 'output', dst_id: 'trainer_0', dst_port: 'input' }],
  metadata: { seed: 42 },
}

describe('graphDrift', () => {
  it('canonical json sorts keys', () => {
    expect(canonicalJson({ b: 1, a: { d: 2, c: undefined } })).toBe('{"a":{"d":2},"b":1}')
  })
  it('no drift when the Editor only filled in catalog defaults', () => {
    const current = {
      ...RUN,
      nodes: [RUN.nodes[0], { id: 'trainer_0', node_type: 'trainer', config: { epochs: 50, batch_size: 32, note: '' } }],
    }
    expect(diffGraphs(RUN, current, { defaultsFor: () => ({ batch_size: 32 }) })).toEqual([])
  })
  it('reports config, node and edge changes', () => {
    const current = {
      nodes: [
        { id: 'ingest_0', node_type: 'dataset_ingest', config: { path: 'b' } },
        { id: 'eval_0', node_type: 'evaluator', config: {} },
      ],
      edges: [{ src_id: 'ingest_0', src_port: 'output', dst_id: 'eval_0', dst_port: 'input' }],
      metadata: { seed: 7 },
    }
    const d = diffGraphs(RUN, current, { compareSeed: true })
    expect(d.map((c) => c.kind).sort()).toEqual(
      ['config-changed', 'edge-added', 'edge-removed', 'node-added', 'node-removed', 'seed-changed'].sort(),
    )
    const cfg = d.find((c) => c.kind === 'config-changed')!
    expect(describeDriftChange(cfg, (id) => (id === 'ingest_0' ? 'Dataset Ingest' : undefined))).toBe(
      'Dataset Ingest · path: a → b',
    )
  })
  it('parses backend pipeline_drift', () => {
    expect(parsePipelineDrift(true)?.changed).toBe(true)
    expect(parsePipelineDrift({ current_hash: 'a', run_hash: 'b' })?.changed).toBe(true)
    expect(parsePipelineDrift({ changed: false, pipeline: 'p' })).toEqual({
      changed: false,
      currentHash: '',
      runHash: '',
      pipeline: 'p',
      layoutOnly: false,
      missing: false,
    })
    expect(parsePipelineDrift({ drifted: true, layout_only: true })?.changed).toBe(false)
    expect(parsePipelineDrift({ drifted: null, pipeline: 'x' })).toMatchObject({ changed: false, missing: true })
    expect(parsePipelineDrift(null)).toBeNull()
  })
})


describe('unscopeRunPaths', () => {
  const rid = '14347a1f299242e692763338a4d35d74'
  it('removes run + per-node folders', () => {
    const g = unscopeRunPaths(
      {
        nodes: [
          { id: 'trainer_0', config: { output_path: `workspace/artifacts/sc/runs/${rid}/trainer_0`, epochs: 5 } },
          { id: 'edge_optimizer_0', config: { output_dir: `workspace/artifacts/sc/runs/${rid}/edge_optimizer_0/tflite` } },
          { id: 'model_builder_0', config: { output_path: `workspace/artifacts/sc/runs/${rid}/models`, other: 'x' } },
        ],
      },
      rid,
    )
    expect(g.nodes!.map((n) => n.config)).toEqual([
      { output_path: 'workspace/artifacts/sc/trainer_0', epochs: 5 },
      { output_dir: 'workspace/artifacts/sc/tflite' },
      { output_path: 'workspace/artifacts/sc/models', other: 'x' },
    ])
  })
})

describe('run-scoped write paths', () => {
  it('are not drift', () => {
    const rid = 'r'.repeat(32)
    const run = { nodes: [{ id: 't', node_type: 'trainer', config: { output_path: `w/a/runs/${rid}/t`, epochs: 1 } }], edges: [] }
    const cur = { nodes: [{ id: 't', node_type: 'trainer', config: { output_path: 'w/a/t', epochs: 1 } }], edges: [] }
    expect(diffGraphs(run, cur, { runId: rid })).toEqual([])
    expect(diffGraphs(run, cur).length).toBe(1)
  })
})
