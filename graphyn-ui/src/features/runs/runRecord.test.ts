import { describe, expect, it } from 'vitest'
import {
  buildRunRecord,
  cacheSourcesFromNodeStats,
  compactNodeLabel,
  failuresByNode,
  failureView,
  formatDurationMs,
  groupVerify,
  formatUtc,
  isArchivedRun,
  isPlaceholderVersion,
  linkableRunId,
  normalizeVerify,
  parseReplayConflict,
  pickProve,
  recordCopyText,
  replayOfRun,
  replayRunId,
  shortHash,
  triggerLabel,
  worstVerifyState,
  nodeLabelsFromRun,
  eventNodeLabel,
} from './runRecord'

const OLD_PROVE = {
  run_id: '14347a1f299242e692763338a4d35d74',
  graph_hash: 'b30993f454cc0dc95631c4c714aaf2c741a842cbacbd16f3e2d3b28b5bdb4462',
  pipeline_version: null,
  dataset_versions: [],
  input_artifact_hashes: ['12426a80126b4145132823db36d1b9076c0c340131ef15f392b32a66225dc8dc'],
  node_implementation_versions: { trainer: 'builtin', evaluator: 'builtin' },
  plugin_version: {},
  runtime_version: 'python-3.12.15/Linux',
  graphyn_version: '0.1.0',
  seed: 42,
  actor: 'system',
  trigger: 'api',
  environment: null,
  timestamp: '2026-10-03T19:02:04.432163+00:00',
}
const META = {
  created_at: '2026-10-03T18:52:16.304586+00:00',
  duration_s: 588.0961,
  graph_hash: 'b30993f4',
  materialized_graph_hash: '1ffb0fb35a72',
}

describe('format helpers', () => {
  it('short hash / utc / duration', () => {
    expect(shortHash('sha256:abcdef0123456789')).toBe('abcdef01')
    expect(shortHash(null)).toBe('')
    expect(formatUtc('2026-10-03T18:52:16.304586+00:00')).toBe('2026-10-03 18:52:16 UTC')
    expect(formatDurationMs(588096)).toBe('9m 48s')
    expect(formatDurationMs(6049)).toBe('6.0 s')
    expect(formatDurationMs(340)).toBe('340 ms')
    expect(formatDurationMs(null)).toBe('')
    expect(triggerLabel('api')).toBe('API')
    expect(triggerLabel('schedule')).toBe('Schedule')
  })
  it('placeholder versions', () => {
    expect(isPlaceholderVersion('builtin')).toBe(true)
    expect(isPlaceholderVersion('')).toBe(true)
    expect(isPlaceholderVersion(null)).toBe(true)
    expect(isPlaceholderVersion('1.2.0')).toBe(false)
  })
})

describe('buildRunRecord', () => {
  it('flags every gap of an old run record', () => {
    const v = buildRunRecord({ runId: 'r1', prove: OLD_PROVE, meta: META })
    expect(v.actor).toBe('system')
    expect(v.seed).toBe(42)
    expect(v.startedAt).toBe(META.created_at)
    expect(v.durationMs).toBeCloseTo(588096.1, 0)
    expect(v.endedAt.startsWith('2026-10-03T19:02:04')).toBe(true)
    expect(v.nodeVersions.map((n) => n.placeholder)).toEqual([true, true])
    expect(v.inputs).toHaveLength(1)
    const keys = v.gaps.map((g) => g.key)
    expect(keys).toEqual(
      expect.arrayContaining([
        'actor',
        'pipeline_version',
        'node_versions',
        'plugin_version',
        'dataset_versions',
        'environment',
        'record_hash',
      ]),
    )
    expect(keys).not.toContain('seed')
    expect(keys).not.toContain('graph_hash')
  })

  it('reads the enriched record shape', () => {
    const v = buildRunRecord({
      runId: 'r2',
      prove: {
        ...OLD_PROVE,
        actor: 'alice',
        trigger: 'replay',
        pipeline_version: { name: 'speech', env: 'staging', revision: 'v3' },
        node_implementation_versions: {
          trainer: { version: '1.4.0', plugin: 'audio-ml', code_hash: 'deadbeefcafe' },
        },
        plugin_version: { trainer: '1.4.0' },
        dataset_versions: [{ name: 'speech-commands', version: 'v1', content_hash: 'aa11' }],
        input_artifact_hashes: [{ path: 'datasets/input/a.wav', sha256: 'ff00', dataset_version: 'v1' }],
        environment: { python: '3.12.1', packages: { numpy: '2.0.1' }, git: { commit: 'abc123def4567890', dirty: true } },
        record_hash: 'f00d',
        chain: { position: 12, prev_hash: 'beef' },
      },
      detail: { replay_of: 'aaaaaaaabbbbbbbbccccccccdddddddd' },
    })
    expect(v.gaps).toEqual([])
    expect(v.pipeline).toMatchObject({ kind: 'saved', name: 'speech', env: 'staging', revision: 'v3' })
    expect(v.nodeVersions[0]).toMatchObject({ version: '1.4.0', plugin: 'audio-ml', codeHash: 'deadbeefcafe', placeholder: false })
    expect(v.inputs[0]).toMatchObject({ label: 'datasets/input/a.wav', hash: 'ff00', datasetVersion: 'v1' })
    expect(v.environment?.git).toBe('abc123def456 · dirty')
    expect(v.environment?.libs).toEqual([['numpy', '2.0.1']])
    expect(v.chainPosition).toBe(12)
    expect(v.replayOf).toBe('aaaaaaaabbbbbbbbccccccccdddddddd')
    expect(recordCopyText(v)).toContain('Pipeline version: speech / staging / v3')
  })

  it('reads the 2.0 contract record', () => {
    const v = buildRunRecord({
      runId: 'r4',
      prove: {
        schema_version: '2.0',
        actor: 'alice',
        trigger: 'ui',
        seed: 1,
        graph_hash: 'gh',
        pipeline_source: 'saved_modified',
        pipeline_version: { project: 'p', name: 'speech', env: 'draft', version: null, revision_hash: 'abcdef0123456789ff', match: 'content_hash', label: 'speech@draft:abcdef012345' },
        node_implementation_versions: { trainer: { plugin: 'trainer', version: '1.0.0', runtime: 'isolated', plugin_code_hash: 'sha256:c0de' } },
        plugin_version: { trainer: '1.0.0' },
        plugin_code_hashes: { trainer: 'sha256:c0de' },
        external_inputs: [{ node_id: 'ingest_0', path: 'workspace/datasets/input/sc', kind: 'dir', content_hash: 'sha256:11', hash_mode: 'manifest', file_count: 10, dataset: { project: 'p', version: 'v1' } }],
        input_artifact_hashes: ['zz'],
        dataset_versions: [{ project: 'p', version: 'v1', path: 'x', content_hash: 'sha256:22' }],
        environment: { python: '3.12.15', implementation: 'CPython', os: 'Linux', machine: 'x86_64', libraries: { numpy: '1.26.4', torch: null }, container_image_digest: null, git_commit: 'd11e324' },
        chain: { project: 'p', seq: 4 },
        previous_record_hash: 'prev',
        record_hash: 'rh',
      },
    })
    expect(v.gaps).toEqual([])
    expect(v.pipeline).toMatchObject({ kind: 'saved', name: 'speech', env: 'draft', revision: 'abcdef012345', modified: true })
    expect(v.nodeVersions[0]).toMatchObject({ version: '1.0.0', runtime: 'isolated', codeHash: 'sha256:c0de' })
    expect(v.inputs).toEqual([
      { label: 'workspace/datasets/input/sc', hash: 'sha256:11', datasetVersion: 'p v1', nodeId: 'ingest_0', kind: 'dir', hashMode: 'manifest', fileCount: 10 },
    ])
    expect(v.datasetVersions[0]).toEqual({ name: 'p', version: 'v1', hash: 'sha256:22' })
    expect(v.environment).toMatchObject({ python: '3.12.15 CPython', platform: 'Linux · x86_64', git: 'd11e324', libs: [['numpy', '1.26.4']] })
    expect(v.chainPosition).toBe(4)
    expect(v.prevRecordHash).toBe('prev')
    expect(buildRunRecord({ runId: 'r5', prove: { pipeline_source: 'adhoc', pipeline_version: null } }).pipeline).toEqual({ kind: 'ad-hoc' })
  })

  it('no prove → single record gap', () => {
    const v = buildRunRecord({ runId: 'r3', prove: null, meta: META })
    expect(v.hasProve).toBe(false)
    expect(v.gaps.map((g) => g.key)).toEqual(['record'])
  })

  it('pickProve prefers backend record fields', () => {
    expect(pickProve({ record: { a: 1 } }, { b: 2 })).toEqual({ a: 1 })
    expect(pickProve({ meta: { prove: { c: 3 } } })).toEqual({ c: 3 })
    expect(pickProve({}, { b: 2 })).toEqual({ b: 2 })
    expect(pickProve({}, null)).toBeNull()
  })
})

describe('replay / archive', () => {
  it('replay_of and archived flags', () => {
    expect(replayOfRun({ meta: { replay_of: 'x'.repeat(32) } })).toBe('x'.repeat(32))
    expect(replayOfRun({})).toBe('')
    expect(isArchivedRun({ archived: true })).toBe(true)
    expect(isArchivedRun({ meta: { archived_at: '2026-01-01' } })).toBe(true)
    expect(isArchivedRun({ status: 'archived' })).toBe(true)
    expect(isArchivedRun({ status: 'succeeded' })).toBe(false)
    expect(replayRunId({ run_id: 'abc' })).toBe('abc')
  })
  it('parses a 409 input-changed body', () => {
    const c = parseReplayConflict({
      error: { code: 'inputs_changed', message: 'Inputs changed since the run' },
      detail: {
        code: 'inputs_changed',
        changes: [{ path: 'datasets/a.wav', recorded: 'aa', current: 'bb', status: 'changed' }, 'datasets/b.wav'],
      },
    })
    expect(c.message).toBe('Inputs changed since the run')
    expect(c.changes).toEqual([
      { label: 'datasets/a.wav', recorded: 'aa', current: 'bb', change: 'changed' },
      { label: 'datasets/b.wav', recorded: '', current: '', change: 'changed' },
    ])
  })
})

describe('verify', () => {
  it('normalizes the contract checks array and groups it', () => {
    const v = normalizeVerify({
      status: 'changed',
      ok: false,
      checks: [
        { check: 'record_hash', status: 'pass', expected: 'aa', actual: 'aa' },
        { check: 'chain', status: 'skipped', details: { seq: 3 } },
        { check: 'graph_snapshot', status: 'pass' },
        { check: 'external_input', target: 'workspace/datasets/input/x', node_id: 'ingest_0', status: 'changed', expected: 'sha256:aaaa', actual: 'sha256:bbbb' },
        { check: 'external_input', target: 'workspace/datasets/input/y', status: 'pass' },
        { check: 'output', target: 'w/runs/r/trainer_0', node_id: 'trainer_0', status: 'missing' },
        { check: 'output', target: 'w/runs/r/eval_0', status: 'changed', details: { added: ['a'], modified: ['b', 'c'] } },
      ],
    })
    expect(v.ok).toBe(false)
    expect(v.status).toBe('changed')
    const groups = groupVerify(v.items)
    expect(groups.map((g) => [g.label, g.state, g.items.length])).toEqual([
      ['Graph snapshot', 'pass', 1],
      ['Inputs', 'changed', 2],
      ['Outputs', 'failed', 2],
      ['Record hash', 'pass', 1],
      ['Record chain', 'unknown', 1],
    ])
    const inp = groups[1].items[0]
    expect(inp.target).toBe('workspace/datasets/input/x')
    expect(inp.detail).toBe('recorded aaaa · now bbbb')
    expect(groups[2].items[1].detail).toBe('1 added · 2 modified')
    expect(groups[4].items[0].detail).toBe('position 3')
  })
  it('normalizes a keyed map', () => {
    const v = normalizeVerify({ run_id: 'x', graph: true, outputs: { ok: true }, chain: 'skipped' })
    expect(v.items.map((i) => i.state)).toEqual(['pass', 'pass', 'unknown'])
    expect(v.ok).toBe(false)
    expect(worstVerifyState([])).toBe('unknown')
  })
})

describe('cache provenance + failures + links', () => {
  it('cache sources', () => {
    const m = cacheSourcesFromNodeStats([
      { node_id: 'a', cache_hit: true, cache_source_run_id: 'r0' },
      { node_id: 'b', cache_hit: true },
    ])
    expect(m.get('a')).toBe('r0')
    expect(m.has('b')).toBe(false)
    const m2 = cacheSourcesFromNodeStats([], [{ node_id: 'b', source_run_id: 'r9' }])
    expect(m2.get('b')).toBe('r9')
  })
  it('node labels from run + events', () => {
    const m = nodeLabelsFromRun({
      meta: { node_labels: { t1: 'Trainer · Path C' }, node_stats: [{ node_id: 't2', node_label: 'Trainer · Path B' }] },
    })
    expect([...m.entries()]).toEqual([
      ['t1', 'Trainer · Path C'],
      ['t2', 'Trainer · Path B'],
    ])
    expect(eventNodeLabel({ node_label: 'X' })).toBe('X')
    expect(eventNodeLabel({ message: '{"node_label":"Y"}' })).toBe('Y')
    expect(eventNodeLabel({})).toBe('')
  })
  it('failure view splits type + message and hides noise', () => {
    const f = failureView({
      error: 'shape mismatch',
      errorType: 'ValueError',
      traceback: [
        'Traceback (most recent call last):',
        '  File "/app/app/core/execution/node_executor.py", line 10, in run',
        '    out = node.execute()',
        '  File "/plugins/trainer/node.py", line 42, in execute',
        '    raise ValueError("shape mismatch")',
        'ValueError: shape mismatch',
      ].join('\n'),
    })!
    expect(f.headline).toBe('ValueError: shape mismatch')
    expect(f.traceback).not.toContain('node_executor.py')
    expect(f.traceback).toContain('/plugins/trainer/node.py')
    expect(f.hiddenNoise).toBe(2)
  })
  it('failure view parses a bare traceback blob', () => {
    const f = failureView({ error: 'Traceback (most recent call last):\n  File "x.py", line 1\nKeyError: \'label\'' })!
    expect(f.errorType).toBe('KeyError')
    expect(f.headline).toBe("KeyError: 'label'")
    expect(f.traceback).toContain('x.py')
  })
  it('failure view: plain message', () => {
    expect(failureView({ error: 'RuntimeError: boom' })!.headline).toBe('RuntimeError: boom')
    expect(failureView({ error: 'boom' })!.headline).toBe('boom')
    expect(failureView({})).toBeNull()
  })
  it('never links a truncated id', () => {
    expect(linkableRunId('14347a1f')).toBe('')
    expect(linkableRunId('14347a1f299242e692763338a4d35d74')).toBe('14347a1f299242e692763338a4d35d74')
  })
})


describe('per-node failures + compact labels', () => {
  it('reads node_error events (incl. JSON in message)', () => {
    const m = failuresByNode([
      { type: 'node_start', node_id: 'a' },
      { type: 'node_error', node_id: 'a', error: 'ValueError: bad shape', error_type: 'ValueError', traceback: 'Traceback…' },
      { message: JSON.stringify({ type: 'node_error', node_id: 'b', error: 'boom' }) },
    ])
    expect(m.get('a')?.headline).toBe('ValueError: bad shape')
    expect(m.get('a')?.traceback).toBe('Traceback…')
    expect(m.get('b')?.headline).toBe('boom')
  })
  it('compacts labels', () => {
    expect(compactNodeLabel('Trainer · Path C (MobileNet · lr 0.002)')).toBe('Trainer · Path C')
    expect(compactNodeLabel('Trainer')).toBe('Trainer')
  })
})
