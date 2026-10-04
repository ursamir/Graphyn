/**
 * Human-readable error text from API error bodies.
 *
 * The API returns several shapes — `{detail: "..."}`, `{detail: {code, message}}`,
 * `{error: {code, message}}`, `{code, message}`, `{error: "code", detail}` and
 * pydantic `{detail: [{loc, msg}]}`. Toasts and banners must show the human
 * message, never the raw JSON body (`{"code":"run_not_found",...}`).
 */

function rec(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

function nonEmpty(v: unknown): string {
  return typeof v === 'string' && v.trim() ? v.trim() : ''
}

/** snake_case error code -> readable fragment, e.g. "run_not_found" -> "Run not found". */
export function humanizeErrorCode(code: string): string {
  const s = code.replace(/_/g, ' ').trim()
  return s ? s[0].toUpperCase() + s.slice(1) : code
}

const CODE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/

/** Pydantic 422 list → "body.name: field required; …". */
function validationList(list: unknown[]): string {
  const parts = list
    .map((item) => {
      const r = rec(item)
      if (!r) return typeof item === 'string' ? item : ''
      const msg = nonEmpty(r.msg) || nonEmpty(r.message)
      const loc = Array.isArray(r.loc) ? r.loc.filter((x) => x !== 'body').join('.') : ''
      return msg ? (loc ? `${loc}: ${msg}` : msg) : ''
    })
    .filter(Boolean)
  return parts.join('; ')
}

/** One readable line from an object error (`{code, message}`, `{error, detail}`, …). */
function fromObject(o: Record<string, unknown>, depth: number): string {
  if (depth > 3) return ''
  const message = nonEmpty(o.message) || nonEmpty(o.msg)
  if (message) return message
  if (typeof o.detail === 'string' && o.detail.trim()) return o.detail.trim()
  for (const nested of [rec(o.detail), rec(o.error)]) {
    if (!nested) continue
    const m = fromObject(nested, depth + 1)
    if (m) return m
  }
  if (Array.isArray(o.detail)) {
    const m = validationList(o.detail)
    if (m) return m
  }
  const code = nonEmpty(o.code) || nonEmpty(o.error)
  if (code) {
    const extras = Object.entries(o)
      .filter(
        ([k, v]) =>
          !['error', 'detail', 'code', 'message', 'status'].includes(k) &&
          (typeof v === 'string' || typeof v === 'number') &&
          String(v) !== '',
      )
      .map(([k, v]) => `${k}=${String(v)}`)
      .join(', ')
    const msg = CODE_RE.test(code) ? humanizeErrorCode(code) : code
    return extras ? `${msg} (${extras})` : msg
  }
  return ''
}

/**
 * Human message from a parsed API error body, or null when nothing readable
 * is in it. Prefers `message` over `code`; humanizes bare snake_case codes.
 */
export function errorMessageFromBody(body: unknown): string | null {
  if (typeof body === 'string') return body.trim() ? humanizeErrorText(body) : null
  if (Array.isArray(body)) return validationList(body) || null
  const b = rec(body)
  if (!b) return null
  // `{error: {code, message}, detail: …}` envelope: the error message wins.
  const errObj = rec(b.error)
  if (errObj) {
    const own = nonEmpty(errObj.message) || nonEmpty(errObj.msg)
    if (own) return own
    const d = rec(b.detail)
    const fromDetail = nonEmpty(b.detail) || (d ? fromObject(d, 1) : '')
    if (fromDetail) return fromDetail
    const m = fromObject(errObj, 1)
    if (m) return m
  }
  if (typeof b.error === 'string' && typeof b.detail === 'string' && b.detail.trim()) {
    return `${CODE_RE.test(b.error) ? humanizeErrorCode(b.error) : b.error}: ${b.detail.trim()}`
  }
  return fromObject(b, 0) || null
}

/**
 * Safety net for already-built error strings: a message that is a JSON object
 * (`{"code":"run_not_found","message":"Run 'x' not found"}`) becomes its human
 * message; a bare `snake_code` or `code:arg · code2` list is humanized.
 * Anything else is returned unchanged.
 */
export function humanizeErrorText(text: string): string {
  const t = text.trim()
  if (!t) return text
  // Allow a short prefix such as "HTTP 404: {...}" or "Register failed: {...}".
  const brace = t.indexOf('{')
  if (brace >= 0 && t.endsWith('}')) {
    try {
      const parsed = JSON.parse(t.slice(brace)) as unknown
      const msg = errorMessageFromBody(parsed)
      if (msg) {
        const prefix = t.slice(0, brace).trim().replace(/[:\-–—]\s*$/, '').trim()
        return prefix ? `${prefix}: ${msg}` : msg
      }
    } catch {
      /* not JSON — fall through */
    }
  }
  // "run_not_found:96505918 · no_node_stats_or_artifacts" (trace warnings).
  const parts = t.split(/\s*·\s*/)
  if (parts.every((p) => /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?::\S+)?$/.test(p))) {
    return parts
      .map((p) => {
        const [code, ...rest] = p.split(':')
        const arg = rest.join(':')
        return arg ? `${humanizeErrorCode(code)} (${arg})` : humanizeErrorCode(code)
      })
      .join(' · ')
  }
  return text
}
