import { describe, expect, it } from 'vitest'
import {
  auditActionLabel,
  auditActionTone,
  auditMatchesQuery,
  auditTarget,
  nextAuditLimit,
  relatedRunId,
} from './auditEvents'

const RID = '14347a1f299242e692763338a4d35d74'

describe('auditTarget', () => {
  it('maps runs / models / pipelines / proposals with full ids', () => {
    expect(auditTarget({ resource_type: 'run', resource_id: RID, metadata: { project: 'ws' } })).toEqual({
      kind: 'run',
      runId: RID,
      project: 'ws',
    })
    expect(auditTarget({ resource_type: 'model', resource_id: 'speech-commands@staging' })).toEqual({
      kind: 'model',
      name: 'speech-commands',
      project: '',
    })
    expect(auditTarget({ resource_type: 'model', resource_id: 'speech-commands->prod' })).toMatchObject({ name: 'speech-commands' })
    expect(auditTarget({ resource_type: 'pipeline', resource_id: 'e06/speech_train@v1' })).toEqual({
      kind: 'pipeline',
      project: 'e06',
      name: 'speech_train',
      version: 'v1',
    })
    expect(auditTarget({ resource_type: 'proposal', resource_id: 'b6e2' })).toEqual({ kind: 'proposal', id: 'b6e2' })
    expect(auditTarget({ resource_type: 'schedule', resource_id: 'tick' })).toBeNull()
  })
  it('related run from metadata', () => {
    expect(relatedRunId({ resource_type: 'model', resource_id: 'x', meta: { run_id: RID } })).toBe(RID)
    expect(relatedRunId({ resource_type: 'run', resource_id: RID, meta: { run_id: RID } })).toBe('')
  })
})

describe('labels / tones / search', () => {
  it('labels lifecycle actions', () => {
    expect(auditActionLabel('run.finish')).toBe('Run finished')
    expect(auditActionLabel('run.archive')).toBe('Run archived')
    expect(auditActionLabel('webhook.set')).toBe('webhook.set')
    expect(auditActionTone('run.fail')).toBe('danger')
    expect(auditActionTone('run.purge')).toBe('danger')
    expect(auditActionTone('run.cancel')).toBe('warning')
    expect(auditActionTone('run.finish')).toBe('success')
    expect(auditActionTone('run.replay')).toBe('info')
    expect(auditActionTone('run.start', 'denied')).toBe('danger')
  })
  it('searches by run id prefix and metadata', () => {
    const ev = { action: 'model.register', resource_type: 'model', resource_id: 'm@staging', meta: { run_id: RID } }
    expect(auditMatchesQuery(ev, '14347a1f')).toBe(true)
    expect(auditMatchesQuery(ev, 'zzz')).toBe(false)
    expect(auditMatchesQuery({ action: 'run.finish' }, 'finished')).toBe(true)
    expect(auditMatchesQuery(ev, '')).toBe(true)
  })
  it('pages up to the API cap', () => {
    expect(nextAuditLimit(100)).toBe(200)
    expect(nextAuditLimit(950)).toBe(1000)
  })
})
