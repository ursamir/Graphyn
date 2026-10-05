/**
 * Workflow facts of a run for the Run record / step details — pure,
 * unit-tested (runWorkflow.test.ts). Sources (all optional, older runs and
 * APIs degrade to null / []):
 *
 *  - sealed record (`prove`) `webhook` / `run_inputs` / `external_calls`
 *    (app/core/runs/audit_record.py), else run meta (`webhook`,
 *    `inputs_sha256`, `input_keys`, `parameters_sha256`, `parameter_names`,
 *    `external_calls`);
 *  - journal events `node_retry` / `node_error_routed` / `node_failed_continued`.
 */

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '')
const num = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => String(x ?? '').trim()).filter(Boolean) : [])

export type WebhookReceipt = {
  hookId: string
  auth: string
  payloadSha256: string
  payloadBytes: number | null
  idempotencyKey: string
  sourceIp: string
  contentType: string
  receivedAt: string
}

/** Webhook delivery receipt (record `webhook`, else meta `webhook`). */
export function webhookReceipt(prove: unknown, meta: unknown): WebhookReceipt | null {
  const w = rec(rec(prove)?.webhook) || rec(rec(meta)?.webhook)
  if (!w) return null
  return {
    hookId: str(w.hook_id),
    auth: str(w.auth),
    payloadSha256: str(w.payload_sha256),
    payloadBytes: num(w.payload_bytes),
    idempotencyKey: str(w.idempotency_key),
    sourceIp: str(w.source_ip),
    contentType: str(w.content_type),
    receivedAt: str(w.received_at),
  }
}

/** "hmac" → "Signed (HMAC)", "bearer" → "Bearer token". */
export function webhookAuthLabel(auth: string): string {
  const a = auth.trim().toLowerCase()
  if (a === 'hmac') return 'Signed (HMAC)'
  if (a === 'bearer') return 'Bearer token'
  return auth || 'not recorded'
}

export type RunInputsView = {
  inputKeys: string[]
  inputsSha256: string
  inputsBytes: number | null
  parameterNames: string[]
  parametersSha256: string
}

/** Injected inputs / parameters fingerprints (record `run_inputs`, else meta). */
export function runInputsView(prove: unknown, meta: unknown): RunInputsView | null {
  const src = rec(rec(prove)?.run_inputs) || rec(meta)
  if (!src) return null
  const view: RunInputsView = {
    inputKeys: strList(src.input_keys),
    inputsSha256: str(src.inputs_sha256),
    inputsBytes: num(src.inputs_bytes),
    parameterNames: strList(src.parameter_names),
    parametersSha256: str(src.parameters_sha256),
  }
  return view.inputsSha256 || view.parametersSha256 || view.inputKeys.length || view.parameterNames.length ? view : null
}

export type ExternalCallRow = {
  key: string
  nodeId: string
  nodeType: string
  kind: string
  method: string
  url: string
  status: string
  ok: boolean | null
  requestSha256: string
  responseSha256: string
  durationMs: number | null
  connectionId: string
  error: string
  ts: string
}

/** Record `external_calls` (else meta) as table rows; URL query / userinfo stripped defensively. */
export function externalCallRows(prove: unknown, meta: unknown): ExternalCallRow[] {
  const raw = Array.isArray(rec(prove)?.external_calls)
    ? (rec(prove)!.external_calls as unknown[])
    : Array.isArray(rec(meta)?.external_calls)
      ? (rec(meta)!.external_calls as unknown[])
      : []
  const rows: ExternalCallRow[] = []
  raw.forEach((item, i) => {
    const r = rec(item)
    if (!r) return
    const statusRaw = r.status
    const code = num(statusRaw)
    const status = statusRaw == null ? '' : String(statusRaw)
    const error = str(r.error)
    const ok = error ? false : code != null ? code < 400 : /^(ok|sent|success)$/i.test(status) ? true : null
    const url = str(r.url).split('#')[0].split('?')[0].replace(/(\/\/)[^/@]*@/, '$1')
    rows.push({
      key: `${i}`,
      nodeId: str(r.node_id),
      nodeType: str(r.node_type),
      kind: str(r.kind).toLowerCase() || 'http',
      method: str(r.method).toUpperCase(),
      url,
      status,
      ok,
      requestSha256: str(r.request_sha256),
      responseSha256: str(r.response_sha256),
      durationMs: num(r.duration_ms),
      connectionId: str(r.connection_id),
      error,
      ts: str(r.ts),
    })
  })
  return rows
}

/** Fold summary: "4 calls · 1 failed · http 3, smtp 1". */
export function externalCallsSummary(rows: ExternalCallRow[]): string {
  if (!rows.length) return 'none'
  const failed = rows.filter((r) => r.ok === false).length
  const byKind = new Map<string, number>()
  for (const r of rows) byKind.set(r.kind, (byKind.get(r.kind) ?? 0) + 1)
  const kinds = [...byKind.entries()].map(([k, n]) => `${k} ${n}`).join(', ')
  return [`${rows.length} call${rows.length === 1 ? '' : 's'}`, failed ? `${failed} failed` : '', kinds].filter(Boolean).join(' · ')
}

// ── Step resilience (retries / routed errors) ──────────────────────────

export type StepRetry = { attempt: number | null; maxAttempts: number | null; waitS: number | null; errorType: string; error: string }
export type StepResilience = {
  retries: StepRetry[]
  routed: { port: string; errorType: string; error: string; attempt: number | null } | null
  continued: { errorType: string; error: string; attempt: number | null } | null
}

/** node_id → retries / routed error / continued failure, from the run's journal events. */
export function resilienceByNode(events: unknown): Map<string, StepResilience> {
  const out = new Map<string, StepResilience>()
  if (!Array.isArray(events)) return out
  const get = (id: string) => {
    let s = out.get(id)
    if (!s) {
      s = { retries: [], routed: null, continued: null }
      out.set(id, s)
    }
    return s
  }
  for (const row of events) {
    let ev = rec(row)
    if (!ev) continue
    if (typeof ev.message === 'string' && ev.message.trim().startsWith('{')) {
      try {
        const inner = rec(JSON.parse(ev.message))
        if (inner) ev = { ...ev, ...inner }
      } catch {
        /* plain text */
      }
    }
    const type = str(ev.type) || str(ev.event)
    if (type !== 'node_retry' && type !== 'node_error_routed' && type !== 'node_failed_continued') continue
    const id = str(ev.node_id)
    if (!id) continue
    const s = get(id)
    const errorType = str(ev.error_type)
    const error = str(ev.error)
    if (type === 'node_retry') {
      s.retries.push({ attempt: num(ev.attempt), maxAttempts: num(ev.max_attempts), waitS: num(ev.wait_s), errorType, error })
    } else if (type === 'node_error_routed') {
      s.routed = { port: str(ev.port) || 'error', errorType, error, attempt: num(ev.attempt) }
    } else {
      s.continued = { errorType, error, attempt: num(ev.attempt) }
    }
  }
  return out
}

/** One-line text for the step header: "retried 2× · error routed to “error”". */
export function resilienceText(s: StepResilience | null | undefined): string {
  if (!s) return ''
  const parts: string[] = []
  if (s.retries.length) parts.push(`retried ${s.retries.length}×`)
  if (s.routed) parts.push(`error routed to “${s.routed.port}”`)
  if (s.continued) parts.push('failed · run continued')
  return parts.join(' · ')
}
