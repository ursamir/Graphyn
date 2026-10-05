import { describe, expect, it } from 'vitest'
import {
  apiOrigin,
  hookDeliveries,
  hookFullUrl,
  parseHeaderAllowlist,
  parseHookView,
  shellQuote,
  signingExample,
} from './webhookHook'

describe('hook view + URL', () => {
  it('parses the API view with defaults', () => {
    const v = parseHookView({ exists: true, hook_id: 'h1', enabled: true, env: 'draft', url_path: '/api/v1/hooks/ws/p' })!
    expect(v.allowedEnvs).toEqual(['draft'])
    expect(v.signatureHeader).toBe('X-Graphyn-Signature')
    expect(parseHookView(null)).toBeNull()
  })
  it('builds the full delivery URL from the API origin', () => {
    expect(apiOrigin('/api/v1', 'https://console.example.com/')).toBe('https://console.example.com')
    expect(apiOrigin('https://api.example.com:8001/api/v1', 'http://x')).toBe('https://api.example.com:8001')
    expect(hookFullUrl('https://a.b', '/api/v1/hooks/ws/p')).toBe('https://a.b/api/v1/hooks/ws/p')
    expect(hookFullUrl('https://a.b', '/api/v1/hooks/ws/p', 'staging', 'prod')).toBe('https://a.b/api/v1/hooks/ws/p?env=staging')
  })
})

describe('signing example', () => {
  it('signs "<timestamp>." + body with HMAC-SHA256 and sends both headers', () => {
    const s = signingExample({ url: 'https://a.b/api/v1/hooks/ws/p', body: '{"a":1}' })
    expect(s).toContain(`BODY='{"a":1}'`)
    expect(s).toContain(`printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET"`)
    expect(s).toContain('-H "X-Graphyn-Timestamp: $TS"')
    expect(s).toContain('-H "X-Graphyn-Signature: sha256=$SIG"')
    expect(s).toContain("curl -sS -X POST 'https://a.b/api/v1/hooks/ws/p'")
    expect(s).toContain('--data-raw "$BODY"')
  })
  it('shell-quotes bodies with single quotes', () => {
    expect(shellQuote("it's")).toBe(`'it'\\''s'`)
    expect(signingExample({ url: 'u', body: `{"m":"it's"}` })).toContain(`BODY='{"m":"it'\\''s"}'`)
  })
})

describe('header allowlist + deliveries', () => {
  it('normalizes header names', () => {
    expect(parseHeaderAllowlist('X-Request-Id, x-tenant,, bad header!, x-tenant')).toEqual(['x-request-id', 'x-tenant', 'bad'])
  })
  it('keeps only webhook runs of this hook', () => {
    const runs = [
      { run_id: 'r1', status: 'succeeded', trigger: 'webhook', webhook: { hook_id: 'h1', auth: 'hmac', payload_bytes: 12, received_at: '2026-10-05T00:00:00Z' } },
      { run_id: 'r2', status: 'failed', trigger: 'webhook', actor: 'webhook:h2' },
      { run_id: 'r3', status: 'succeeded', trigger: 'ui' },
      { run_id: 'r4', status: 'failed', trigger: 'webhook', actor: 'webhook:h1', created_at: 't' },
    ]
    const d = hookDeliveries(runs, 'h1')
    expect(d.map((x) => x.runId)).toEqual(['r1', 'r4'])
    expect(d[0]).toMatchObject({ auth: 'hmac', bytes: 12 })
    expect(hookDeliveries(runs, '')).toEqual([])
  })
})
