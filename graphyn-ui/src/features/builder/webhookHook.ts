/**
 * Inbound pipeline webhook (Editor → Triggers dock): pure helpers for the
 * `GET/PUT /projects/{ws}/pipelines/{p}/hook` view, the public delivery URL
 * and a copy-paste signing example (curl + openssl). Unit-tested
 * (webhookHook.test.ts). The secret itself is shown once by `…/hook/rotate`
 * and never stored by the console.
 */

export type HookView = {
  workspace: string
  pipeline: string
  exists: boolean
  hookId: string
  enabled: boolean
  env: string
  allowedEnvs: string[]
  headerAllowlist: string[]
  urlPath: string
  secretConnectionId: string
  hasSecret: boolean
  createdBy: string
  createdAt: string
  updatedAt: string
  rotatedAt: string
  signatureHeader: string
  timestampHeader: string
  signatureScheme: string
}

export const HOOK_ENVS = ['draft', 'staging', 'prod'] as const

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '')
const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.map((x) => String(x ?? '').trim()).filter(Boolean) : []

export function parseHookView(raw: unknown): HookView | null {
  const r = rec(raw)
  if (!r) return null
  const env = str(r.env) || 'prod'
  return {
    workspace: str(r.workspace),
    pipeline: str(r.pipeline),
    exists: Boolean(r.exists),
    hookId: str(r.hook_id),
    enabled: Boolean(r.enabled),
    env,
    allowedEnvs: strList(r.allowed_envs).length ? strList(r.allowed_envs) : [env],
    headerAllowlist: strList(r.header_allowlist),
    urlPath: str(r.url_path),
    secretConnectionId: str(r.secret_connection_id),
    hasSecret: Boolean(r.has_secret),
    createdBy: str(r.created_by),
    createdAt: str(r.created_at),
    updatedAt: str(r.updated_at),
    rotatedAt: str(r.rotated_at),
    signatureHeader: str(r.signature_header) || 'X-Graphyn-Signature',
    timestampHeader: str(r.timestamp_header) || 'X-Graphyn-Timestamp',
    signatureScheme: str(r.signature_scheme),
  }
}

/**
 * Origin that serves the API: the absolute `VITE_API_BASE_URL` origin when
 * set, else the page origin (relative `/api/v1` goes through the same host).
 */
export function apiOrigin(apiBaseUrl: string, pageOrigin: string): string {
  const m = /^(https?:\/\/[^/]+)/i.exec(apiBaseUrl.trim())
  if (m) return m[1]
  return pageOrigin.replace(/\/+$/, '')
}

/** Full delivery URL; `?env=` only when it differs from the hook default. */
export function hookFullUrl(origin: string, urlPath: string, env?: string, defaultEnv?: string): string {
  const path = urlPath.startsWith('/') ? urlPath : `/${urlPath}`
  const base = `${origin.replace(/\/+$/, '')}${path}`
  return env && env !== defaultEnv ? `${base}?env=${encodeURIComponent(env)}` : base
}

/** POSIX single-quote a value for a shell command line. */
export function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`
}

/**
 * Bash snippet that signs and sends one delivery:
 * `sha256=hex(HMAC_SHA256(secret, "<timestamp>." + raw_body))`.
 */
export function signingExample(opts: {
  url: string
  body?: string
  secret?: string
  signatureHeader?: string
  timestampHeader?: string
}): string {
  const body = opts.body ?? '{"event":"test"}'
  const sigH = opts.signatureHeader || 'X-Graphyn-Signature'
  const tsH = opts.timestampHeader || 'X-Graphyn-Timestamp'
  return [
    `SECRET=${shellQuote(opts.secret || 'whsec_…')}   # shown once when you rotate`,
    `BODY=${shellQuote(body)}`,
    'TS=$(date +%s)',
    `SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')`,
    `curl -sS -X POST ${shellQuote(opts.url)} \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -H "${tsH}: $TS" \\`,
    `  -H "${sigH}: sha256=$SIG" \\`,
    `  -H "Idempotency-Key: $(uuidgen 2>/dev/null || date +%s%N)" \\`,
    '  --data-raw "$BODY"',
  ].join('\n')
}

/** Bearer-token alternative (any accepted API token). */
export function bearerExample(url: string, body = '{"event":"test"}'): string {
  return [
    `curl -sS -X POST ${shellQuote(url)} \\`,
    `  -H "Authorization: Bearer $GRAPHYN_API_TOKEN" \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  --data-raw ${shellQuote(body)}`,
  ].join('\n')
}

/** "x-request-id, X-Tenant ,," → ["x-request-id", "x-tenant"] (lower-case, unique). */
export function parseHeaderAllowlist(text: string): string[] {
  const out: string[] = []
  for (const part of text.split(/[\s,]+/)) {
    const h = part.trim().toLowerCase()
    if (h && /^[a-z0-9-]+$/.test(h) && !out.includes(h)) out.push(h)
  }
  return out
}

/** Recent webhook deliveries of this hook from a `GET /runs` page (newest first). */
export type HookDelivery = { runId: string; status: string; receivedAt: string; auth: string; bytes: number | null }

export function hookDeliveries(runs: unknown, hookId: string, limit = 5): HookDelivery[] {
  if (!Array.isArray(runs) || !hookId) return []
  const out: HookDelivery[] = []
  for (const row of runs) {
    const r = rec(row)
    if (!r) continue
    const meta = rec(r.meta)
    const trigger = str(r.trigger) || str(meta?.trigger)
    const wh = rec(r.webhook) || rec(meta?.webhook)
    const actor = str(r.actor) || str(meta?.actor)
    const matches = (wh && str(wh.hook_id) === hookId) || actor === `webhook:${hookId}`
    if (trigger !== 'webhook' || !matches) continue
    const bytes = Number(wh?.payload_bytes)
    out.push({
      runId: str(r.run_id) || str(r.id),
      status: str(r.status),
      receivedAt: str(wh?.received_at) || str(r.created_at),
      auth: str(wh?.auth),
      bytes: Number.isFinite(bytes) ? bytes : null,
    })
    if (out.length >= limit) break
  }
  return out
}
