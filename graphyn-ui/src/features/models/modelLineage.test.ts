import { describe, expect, it } from 'vitest'
import { buildModelLineage, datasetLine, lineageStageFor, modelStageLabel, stepLine, stepSettings } from './modelLineage'

const RAW = {
  name: 'kws',
  description: 'keyword spotter',
  stages: {
    prod: { stage: 'prod', run_id: 'r1', node_id: 'trainer_b', model_hash: 'sha256:aaaaaaaabbbb', made_from: null },
    staging: {
      stage: 'staging',
      run_id: 'r2',
      node_id: 'trainer_c',
      path_id: 'path-c',
      artifact_path: 'workspace/x.keras',
      format: 'keras',
      model_file_count: 1,
      made_from: {
        run_id: 'r2run0000000000',
        sealed: true,
        graph_hash: '1234567890abcdef',
        seed: 42,
        datasets: [{ node_id: 'ingest', key: 'input_dir', label: 'speech-commands', path: 'w/d', content_hash: 'sha256:3f2a9c1b77', file_count: 1204, dataset_version: 'v3' }],
        node: { node_id: 'trainer_c', node_type: 'trainer', label: 'Trainer · Path C', plugin: 'keras-trainer', plugin_version: '1.4.2', code_hash: '9ac1e2f0aa' },
        step_config: { epochs: 30, learning_rate: 0.002, layers: [{ a: 1 }], classes: ['yes', 'no'] },
        environment: { python: '3.11.9', image: 'graphyn:1', graphyn_version: '0.9', git_commit: 'abcdef1234567' },
      },
    },
  },
  pending_prod: null,
  used_in: [
    { run_id: 'old', created_at: '2026-10-01', status: 'succeeded', actor: 'bob', actor_verified: false, stage: 'staging', package: null },
    { run_id: 'new0000000', short: 'new00000', created_at: '2026-10-03', status: 'succeeded', actor: 'alice', actor_verified: true, stage: 'prod', graph_name: 'edge-deploy', package: { sha256: 'deadbeefcafe' } },
  ],
  packages: [{ package_id: 'pkg-1', project: 'w', status: 'built', env: 'staging', stage: 'staging', run_id: 'new0000000', created_at: 't', sha256: 'deadbeef' }],
}

describe('model lineage view', () => {
  it('maps stages in Staging → Production order with made_from', () => {
    const v = buildModelLineage(RAW)!
    expect(v.stages.map((s) => s.label)).toEqual(['Staging', 'Production'])
    const st = lineageStageFor(v, 'staging')!
    expect(st.madeFrom?.seed).toBe(42)
    expect(st.madeFrom?.datasets[0]).toMatchObject({ label: 'speech-commands', fileCount: 1204 })
    expect(datasetLine(st.madeFrom!.datasets[0])).toBe('speech-commands · 3f2a9c1b · 1,204 files · v3')
    expect(stepLine(st.madeFrom!.step!)).toBe('Trainer · Path C · keras-trainer 1.4.2 · code 9ac1e2f0')
    expect(st.madeFrom?.settings).toEqual([
      { key: 'classes', value: 'yes, no' },
      { key: 'epochs', value: '30' },
      { key: 'learning_rate', value: '0.002' },
    ])
    expect(st.madeFrom?.environment.map((e) => e.label)).toEqual(['Python', 'Graphyn', 'Image', 'Git'])
    expect(lineageStageFor(v, 'prod')?.madeFrom).toBeNull()
  })

  it('maps used_in newest first with actor + package and packages', () => {
    const v = buildModelLineage(RAW)!
    expect(v.usedIn.map((u) => u.runId)).toEqual(['new0000000', 'old'])
    expect(v.usedIn[0]).toMatchObject({ actor: 'alice', actorVerified: true, stageLabel: 'Production', packageSha: 'deadbeefcafe' })
    expect(v.usedIn[1].short).toBe('old')
    expect(v.packages[0]).toMatchObject({ packageId: 'pkg-1', stageLabel: 'Staging' })
  })

  it('handles junk and vocab', () => {
    expect(buildModelLineage(null)).toBeNull()
    expect(buildModelLineage({})!.stages).toEqual([])
    expect(modelStageLabel('prod')).toBe('Production')
    expect(modelStageLabel('testing')).toBe('Staging')
    expect(modelStageLabel('latest')).toBe('Latest')
    expect(stepSettings(null)).toEqual([])
  })
})
