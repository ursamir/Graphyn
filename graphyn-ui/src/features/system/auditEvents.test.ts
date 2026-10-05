import { describe, expect, it } from 'vitest'
import {
  auditActionLabel,
  auditActionTone,
  auditActorDisplay,
  auditMatchesQuery,
  auditResourceLabel,
  auditTarget,
  isSystemAuditEvent,
  auditCategory,
  auditCategoryQuery,
  auditEventLabel,
  DEFAULT_AUDIT_CATEGORIES,
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
    expect(auditActionLabel('workspace.deleted')).toBe('Workspace deleted')
    expect(auditActionLabel('workspace.unarchived')).toBe('Workspace unarchived')
    expect(auditActionLabel('workspace.renamed')).toBe('Workspace id renamed (legacy)')
    expect(auditActionLabel('webhook.set')).toBe('Webhook saved')
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

describe('plain-words audit labels', () => {
  it('labels every known action', () => {
    expect(auditActionLabel('model.register')).toBe('Model registered')
    expect(auditActionLabel('notifications.mark_read')).toBe('Notifications marked read')
    expect(auditActionLabel('credential.bind_default')).toBe('Default connection set')
    expect(auditActionLabel('ship.sign')).toBe('Ship package signed')
    expect(auditActionLabel('MODEL.REGISTER')).toBe('Model registered')
  })

  it('falls back to "<Resource> <verb>ed" for unknown actions', () => {
    expect(auditActionLabel('plugin.install')).toBe('Plugin installed')
    expect(auditActionLabel('dataset.cache_purge')).toBe('Dataset cache purged')
    expect(auditActionLabel('dataset.label_delete')).toBe('Input dataset deleted')
    expect(auditActionLabel('widget.copy')).toBe('Widget copied')
    expect(auditActionLabel('noaction')).toBe('noaction')
    expect(auditActionLabel(undefined)).toBe('Unknown action')
  })

  it('flags housekeeping events', () => {
    expect(isSystemAuditEvent({ action: 'notifications.mark_read' })).toBe(true)
    expect(isSystemAuditEvent({ action: 'run.start' })).toBe(false)
  })

  it('shows unidentified API actors muted', () => {
    expect(auditActorDisplay({ actor: 'api', actor_kind: 'system' })).toEqual({
      label: 'Unidentified (API)',
      muted: true,
      detail: 'api · system',
    })
    expect(auditActorDisplay({ actor: 'samir', actor_kind: 'user' })).toEqual({
      label: 'samir',
      muted: false,
      detail: '',
    })
    expect(auditActorDisplay({ actor: 'ci-bot', actor_kind: 'agent' }).detail).toBe('agent')
  })

  it('shortens resource ids', () => {
    expect(auditResourceLabel({ resource_type: 'run', resource_id: RID })).toBe('14347a1f')
    expect(auditResourceLabel({ resource_type: 'model', resource_id: 'kws@staging' })).toBe('kws@staging')
    expect(auditResourceLabel({ resource_type: 'pipeline', resource_id: 'ws/train@3' })).toBe('train@3')
    expect(auditResourceLabel({ resource_type: 'credential', resource_id: RID })).toBe('14347a1f')
    expect(auditResourceLabel({ resource_type: 'schedule', resource_id: 'nightly' })).toBe('nightly')
    expect(auditResourceLabel({})).toBe('')
  })
})

describe('audit categories / server labels', () => {
  it('prefers the server category, else mirrors the API rules', () => {
    expect(auditCategory({ action: 'run.start', category: 'admin' })).toBe('admin')
    expect(auditCategory({ action: 'run.finish' })).toBe('run')
    expect(auditCategory({ action: 'ship.build' })).toBe('model')
    expect(auditCategory({ action: 'notifications.mark_read' })).toBe('ui')
    expect(auditCategory({ action: 'schedule.tick' })).toBe('system')
    expect(auditCategory({ action: 'schedule.create' })).toBe('admin')
    expect(auditCategory({ action: 'mystery' })).toBe('system')
    expect(auditCategory({ action: 'workspace.deleted' })).toBe('admin')
    expect(auditCategory({ action: 'workspace.archived' })).toBe('admin')
    expect(auditCategory({ action: 'dataset.upload' })).toBe('data')
    expect(auditCategory({ action: 'dataset.version_delete' })).toBe('data')
  })
  it('uses the server label with a client fallback', () => {
    expect(auditEventLabel({ action: 'model.register', label: 'Model saved' })).toBe('Model saved')
    expect(auditEventLabel({ action: 'model.register' })).toBe('Model registered')
    // Failures never read like successes.
    expect(auditEventLabel({ action: 'dataset.upload', label: 'Dataset uploaded', result: 'failure' })).toBe('Dataset upload failed')
    expect(auditEventLabel({ action: 'token.create', result: 'denied' })).toMatch(/create denied$/)
    expect(auditEventLabel({ label: 'Something happened', result: 'failure' })).toBe('Something happened — failed')
    expect(auditActionTone('dataset.upload', 'failure')).toBe('danger')
  })
  it('builds the exclude_category query', () => {
    expect(auditCategoryQuery(DEFAULT_AUDIT_CATEGORIES)).toEqual({ exclude_category: 'system,ui' })
    expect(auditCategoryQuery(new Set(['run', 'model', 'data', 'admin', 'system', 'ui']))).toEqual({})
    expect(auditCategoryQuery(new Set(['run']))).toEqual({ exclude_category: 'model,data,admin,system,ui' })
  })
})
