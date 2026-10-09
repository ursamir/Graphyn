import { describe, expect, it } from 'vitest'
import { connectionRefusal, shortTypeLabel } from './portTypes'

describe('shortTypeLabel', () => {
  it('drops module paths but keeps generics', () => {
    expect(shortTypeLabel('builtins.list[app.models.audio_sample.AudioSample]')).toBe('list[AudioSample]')
    expect(shortTypeLabel('_graphyn_plugin_http-request_ab12.types.HttpResponse')).toBe('HttpResponse')
    expect(shortTypeLabel('app.models.audio_sample.AudioSample | None')).toBe('AudioSample | None')
  })
  it('reads untyped ports as any', () => {
    expect(shortTypeLabel('builtins.object')).toBe('any')
    expect(shortTypeLabel('builtins.object | None')).toBe('any')
    expect(shortTypeLabel('typing.Any')).toBe('any')
    expect(shortTypeLabel(undefined)).toBe('')
  })
})

describe('connectionRefusal', () => {
  it('allows compatible or unknown checks', () => {
    expect(connectionRefusal({ compatible: true })).toBeNull()
    expect(connectionRefusal(null)).toBeNull()
  })
  it('explains a type mismatch in plain words', () => {
    expect(
      connectionRefusal({
        compatible: false,
        source_type: 'x.types.HttpResponse',
        target_type: 'app.models.dataset.DatasetArtifact',
      }),
    ).toBe("Can't connect: this output is HttpResponse, but the input expects DatasetArtifact.")
  })
  it('falls back to the server reason for a missing port', () => {
    expect(connectionRefusal({ compatible: false, reason: "trainer has no input named 'x'." })).toBe(
      "Can't connect: trainer has no input named 'x'.",
    )
  })
})
