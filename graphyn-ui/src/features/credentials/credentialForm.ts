/**
 * Credentials → Add connection: pure helpers that turn a credential kind's
 * declared fields (GET /credentials/kinds) into a form — friendly labels,
 * input types (password / number / checkbox / text), initial values, payload
 * building + required-field checks, and JSON ↔ form round-trips for the
 * "Edit as JSON" toggle. Unit-tested (credentialForm.test.ts).
 */

export type KindField = {
  name: string
  secret: boolean
  required: boolean
  description?: string
  default?: unknown
}

export type KindInfo = {
  id: string
  label: string
  description?: string
  fields: KindField[]
}

export type FieldInput = 'password' | 'number' | 'checkbox' | 'text'

export type FormValues = Record<string, string | boolean>

const FIELD_LABELS: Record<string, string> = {
  api_key: 'API key',
  base_url: 'Base URL',
  default_model: 'Default model',
  host: 'Host',
  port: 'Port',
  user: 'Username',
  username: 'Username',
  password: 'Password',
  from_addr: 'From address',
  tls: 'Use STARTTLS',
  dry_run: 'Dry run (no network)',
  url: 'Webhook URL',
  events: 'Events (comma-separated)',
  token: 'Token',
}

const ACRONYMS: Record<string, string> = { api: 'API', url: 'URL', id: 'ID', tls: 'TLS', smtp: 'SMTP' }

/** "api_key" → "API key"; unknown names are humanized ("org_id" → "Org ID"). */
export function fieldLabel(name: string): string {
  const known = FIELD_LABELS[name]
  if (known) return known
  const words = name
    .split(/[_\-.\s]+/)
    .filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.toLowerCase())
  if (!words.length) return name
  const first = words[0]
  words[0] = first === first.toUpperCase() ? first : first[0].toUpperCase() + first.slice(1)
  return words.join(' ')
}

export function fieldInput(f: KindField): FieldInput {
  if (f.secret) return 'password'
  if (typeof f.default === 'boolean') return 'checkbox'
  if (typeof f.default === 'number') return 'number'
  return 'text'
}

/** Help text under the input: the kind's description unless it just repeats the label. */
export function fieldHint(f: KindField): string {
  // "(scheme=basic)" drives visibility (fieldVisible) — not shown as help.
  const d = (f.description || '').replace(/\s*\(\w+=[\w.-]+\)/g, '').trim()
  if (!d) return ''
  const norm = (s: string) => s.toLowerCase().replace(/^optional\s+/, '').replace(/[^a-z0-9]/g, '')
  return norm(d) === norm(fieldLabel(f.name)) ? '' : d
}

/**
 * Enumerated values declared in a field description written as
 * "a | b | c" (e.g. http_auth `scheme`: "bearer | basic | header") → a select.
 */
export function fieldChoices(f: KindField): string[] | null {
  const d = (f.description || '').trim()
  if (!/^[A-Za-z0-9_.-]+(\s*\|\s*[A-Za-z0-9_.-]+)+$/.test(d)) return null
  return d.split('|').map((x) => x.trim())
}

/**
 * Fields whose description names a condition "(scheme=basic)" only show when
 * that sibling field has that value (or is still empty).
 */
export function fieldVisible(f: KindField, values: FormValues): boolean {
  const m = /\((\w+)=([\w.-]+)\)/.exec(f.description || '')
  if (!m) return true
  const cur = String(values[m[1]] ?? '').trim().toLowerCase()
  return !cur || cur === m[2].toLowerCase()
}

export function hasFormFields(kind: KindInfo | undefined): kind is KindInfo {
  return Boolean(kind && Array.isArray(kind.fields) && kind.fields.length > 0)
}

export function initialFormValues(kind: KindInfo): FormValues {
  const out: FormValues = {}
  for (const f of kind.fields) {
    const input = fieldInput(f)
    if (input === 'checkbox') out[f.name] = Boolean(f.default)
    else out[f.name] = f.default == null ? '' : String(f.default)
  }
  return out
}

/** Labels of required fields that are still empty. */
export function missingRequired(kind: KindInfo, values: FormValues): string[] {
  return kind.fields
    .filter((f) => f.required && fieldInput(f) !== 'checkbox' && fieldVisible(f, values))
    .filter((f) => String(values[f.name] ?? '').trim() === '')
    .map((f) => fieldLabel(f.name))
}

/**
 * Form values → API payload. Empty optional text fields are omitted (the
 * server applies the kind's defaults); numbers are parsed; checkboxes are
 * booleans.
 */
export function buildPayload(kind: KindInfo, values: FormValues): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of kind.fields) {
    // Fields for another scheme (e.g. a token typed before switching to basic) are not sent.
    if (!fieldVisible(f, values)) continue
    const v = values[f.name]
    const input = fieldInput(f)
    if (input === 'checkbox') {
      out[f.name] = Boolean(v)
      continue
    }
    const str = typeof v === 'string' ? (f.secret ? v : v.trim()) : v == null ? '' : String(v)
    if (str === '') {
      if (f.required) out[f.name] = ''
      continue
    }
    if (input === 'number') {
      const n = Number(str)
      out[f.name] = Number.isFinite(n) ? n : str
    } else {
      out[f.name] = str
    }
  }
  return out
}

/** JSON payload → form values (for switching back from "Edit as JSON"). */
export function valuesFromPayload(kind: KindInfo, payload: Record<string, unknown>): FormValues {
  const out = initialFormValues(kind)
  for (const f of kind.fields) {
    if (!(f.name in payload)) continue
    const v = payload[f.name]
    if (fieldInput(f) === 'checkbox') out[f.name] = Boolean(v)
    else out[f.name] = v == null ? '' : typeof v === 'string' ? v : String(v)
  }
  return out
}

/** Parse the JSON editor; returns an error message instead of throwing. */
export function parsePayloadJson(text: string): { payload: Record<string, unknown> } | { error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(text.trim() || '{}')
  } catch {
    return { error: 'Settings must be valid JSON' }
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { error: 'Settings must be a JSON object' }
  }
  return { payload: parsed as Record<string, unknown> }
}
