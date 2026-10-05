import { describe, expect, it } from 'vitest'
import {
  externalCallRows,
  externalCallsSummary,
  resilienceByNode,
  resilienceText,
  runInputsView,
  webhookAuthLabel,
  webhookReceipt,
} from './runWorkflow'

describe('webhook receipt + inputs', () => {
  it('prefers the sealed record, falls back to meta', () => {
    const meta = { webhook: { hook_id: 'm', auth: 'bearer' }, inputs_sha256: 'aa', input_keys: ['hook.body'] }
    expect(webhookReceipt({ webhook: { hook_id: 'h', auth: 'hmac', payload_bytes: 10 } }, meta)).toMatchObject({
      hookId: 'h',
      auth: 'hmac',
      payloadBytes: 10,
    })
    expect(webhookReceipt({}, meta)?.hookId).toBe('m')
    expect(webhookReceipt({}, {})).toBeNull()
    expect(webhookAuthLabel('hmac')).toBe('Signed (HMAC)')
    expect(runInputsView({ run_inputs: { parameters_sha256: 'pp', parameter_names: ['limit'] } }, meta)).toMatchObject({
      parametersSha256: 'pp',
      parameterNames: ['limit'],
      inputKeys: [],
    })
    expect(runInputsView({}, meta)).toMatchObject({ inputsSha256: 'aa', inputKeys: ['hook.body'] })
    expect(runInputsView({}, {})).toBeNull()
  })
})

describe('external calls', () => {
  it('maps rows, redacts URLs and flags failures', () => {
    const rows = externalCallRows(
      {
        external_calls: [
          { node_id: 'n', kind: 'http', method: 'get', url: 'https://u:p@api.x/a?token=1#f', status: 200, duration_ms: 12 },
          { node_id: 'm', kind: 'smtp', status: 'sent' },
          { node_id: 'k', kind: 'llm', status: 500, error: 'boom' },
        ],
      },
      null,
    )
    expect(rows[0]).toMatchObject({ method: 'GET', url: 'https://api.x/a', ok: true, durationMs: 12 })
    expect(rows[1].ok).toBe(true)
    expect(rows[2].ok).toBe(false)
    expect(externalCallsSummary(rows)).toBe('3 calls · 1 failed · http 1, smtp 1, llm 1')
    expect(externalCallsSummary([])).toBe('none')
  })
})

describe('step resilience', () => {
  it('collects retries and routed / continued failures per node', () => {
    const m = resilienceByNode([
      { type: 'node_retry', node_id: 'a', attempt: 2, max_attempts: 3, wait_s: 1, error_type: 'Timeout' },
      { message: JSON.stringify({ type: 'node_retry', node_id: 'a', attempt: 3, max_attempts: 3 }) },
      { type: 'node_error_routed', node_id: 'a', port: 'error', error_type: 'Timeout', attempt: 3 },
      { type: 'node_failed_continued', node_id: 'b', error: 'x' },
      { type: 'node_done', node_id: 'c' },
    ])
    expect(m.get('a')?.retries).toHaveLength(2)
    expect(resilienceText(m.get('a'))).toBe('retried 2× · error routed to “error”')
    expect(resilienceText(m.get('b'))).toBe('failed · run continued')
    expect(m.has('c')).toBe(false)
  })
})
