/** Human-facing labels and execution-log lines for the console. */

export function stripIsolatedPrefix(name: string): string {
  return name.replace(/^Isolated_/, '')
}

export function startCase(key: string): string {
  const spaced = key
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim()
  if (!spaced) return key
  return spaced.replace(/\b\w/g, (c) => c.toUpperCase())
}

export function humanNodeLabel(name: string): string {
  let s = stripIsolatedPrefix(name)
  s = s.replace(/Node$/, '')
  return startCase(s) || name
}

export function schemaFieldLabel(key: string, def?: Record<string, unknown>): string {
  const title = def && typeof def.title === 'string' ? def.title.trim() : ''
  return title || startCase(key)
}

export function schemaFieldHint(def?: Record<string, unknown>): string | undefined {
  if (!def) return undefined
  const d = def.description
  return typeof d === 'string' && d.trim() ? d : undefined
}

function durationLabel(ev: Record<string, unknown>): string | null {
  const s = ev.duration_s ?? ev.duration ?? ev.elapsed_s
  const ms = ev.duration_ms ?? ev.elapsed_ms
  let seconds: number | null = null
  if (typeof s === 'number' && Number.isFinite(s)) seconds = s
  else if (typeof ms === 'number' && Number.isFinite(ms)) seconds = ms / 1000
  if (seconds == null) return null
  if (seconds < 0.05) return `${Math.round(seconds * 1000)}ms`
  return `${seconds.toFixed(1)}s`
}

function cacheLabel(ev: Record<string, unknown>, message?: string): string | null {
  if (ev.cache_hit === true) return 'cache hit'
  if (ev.cache_hit === false) return 'cache miss'
  const blob = `${message ?? ''} ${String(ev.message ?? '')}`.toLowerCase()
  if (blob.includes('cache hit')) return 'cache hit'
  if (blob.includes('cache miss')) return 'cache miss'
  return null
}

function eventType(ev: Record<string, unknown>): string {
  return String(ev.type ?? ev.event ?? '')
}

function nodeFromEvent(ev: Record<string, unknown>): string {
  const raw = String(ev.node_type ?? ev.node ?? ev.nodeType ?? '')
  return raw ? humanNodeLabel(raw) : ''
}

function firstLine(text: string): string {
  return text.split('\n')[0]?.trim() ?? text
}

function errorFromEvent(ev: Record<string, unknown>): string | null {
  const raw = ev.error_message ?? ev.error ?? ev.message
  if (raw == null) return null
  const s = firstLine(String(raw))
  return s.replace(/^Isolated_/g, '')
}

const TEXT_NODE_RE =
  /\[(\d+)\]\s+(Isolated_)?([A-Za-z0-9_]+)\s+[—–-]\s+(.*)$/

function formatPlainMessage(message: string): string {
  const m = message.match(TEXT_NODE_RE)
  if (m) {
    const label = humanNodeLabel(`${m[2] ?? ''}${m[3]}`)
    const rest = m[4].trim()
    const lower = rest.toLowerCase()
    if (lower.includes('failed')) {
      const err = rest.replace(/^FAILED:?\s*/i, '').replace(/^failed:?\s*/i, '')
      return `${label} · failed · ${err}`
    }
    if (lower.includes('cache hit')) return `${label} · cache hit`
    if (lower.includes('cache miss')) return `${label} · cache miss`
    const done = rest.match(/done in ([\d.]+)s/i)
    if (done) return `${label} · ${Number(done[1]).toFixed(1)}s`
    if (lower.includes('starting')) return `${label} · started`
    return `${label} · ${rest.replace(/^Isolated_/, '')}`
  }
  return message.replace(/Isolated_/g, '')
}

export function formatExecutionEvent(
  ev: Record<string, unknown>,
  fallback = '',
): { text: string; level: string } {
  const kind = eventType(ev)
  const node = nodeFromEvent(ev)
  const dur = durationLabel(ev)
  const cache = cacheLabel(ev, fallback)
  const levelRaw = String(ev.level ?? kind ?? 'info').toLowerCase()
  const errLevel = kind.includes('error') || levelRaw.includes('error') ? 'error' : levelRaw

  if (kind === 'node_start') {
    return { text: node ? `${node} · started` : 'Node started', level: 'info' }
  }
  if (kind === 'node_end' || kind === 'node_complete') {
    const parts = [node || 'Node', cache, dur].filter(Boolean)
    return { text: parts.join(' · '), level: 'success' }
  }
  if (kind === 'node_error') {
    const err = errorFromEvent(ev) ?? 'failed'
    return { text: `${node || 'Node'} · failed · ${err}`, level: 'error' }
  }
  if (kind === 'error') {
    const err = errorFromEvent(ev) ?? fallback
    return { text: node ? `${node} · failed · ${err}` : firstLine(String(err)), level: 'error' }
  }
  if (kind === 'pipeline_start') {
    const n = ev.total_nodes
    return { text: n != null ? `Pipeline starting · ${n} nodes` : 'Pipeline starting', level: 'info' }
  }
  if (kind === 'done' || kind === 'pipeline_done') {
    const parts = ['Pipeline complete', dur].filter(Boolean)
    return { text: parts.join(' · '), level: 'success' }
  }
  if (kind === 'pipeline_summary') {
    return { text: 'Pipeline summary', level: 'info' }
  }

  if (typeof ev.message === 'string' && ev.message.trim()) {
    return { text: formatPlainMessage(ev.message), level: errLevel.includes('error') ? 'error' : 'info' }
  }
  if (kind) return { text: startCase(kind.replace(/_/g, ' ')), level: errLevel }
  if (fallback.startsWith('{')) return { text: 'Event', level: 'info' }
  return { text: formatPlainMessage(fallback || 'Event'), level: 'info' }
}

export function formatExecutionLine(raw: string): { text: string; level: string; raw: string } {
  const trimmed = raw.trim()
  if (!trimmed) return { text: '', level: 'info', raw: trimmed }
  try {
    const ev = JSON.parse(trimmed) as unknown
    if (ev && typeof ev === 'object' && !Array.isArray(ev)) {
      const formatted = formatExecutionEvent(ev as Record<string, unknown>, trimmed)
      return { ...formatted, raw: trimmed }
    }
  } catch {
    /* plain text */
  }
  return { text: formatPlainMessage(trimmed), level: /fail|error/i.test(trimmed) ? 'error' : 'info', raw: trimmed }
}

export function prettyScalar(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '—'
  if (typeof value === 'string') return value || '—'
  return ''
}

export function formatLocaleDateTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  try {
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export function shortRunId(id: string): string {
  if (!id) return '—'
  if (id.length > 12) return id.slice(0, 8)
  return id
}

export function skipConsecutiveByText<T>(items: T[], textOf: (item: T) => string): T[] {
  const out: T[] = []
  let last = ''
  for (const item of items) {
    const text = textOf(item)
    if (text && text === last) continue
    out.push(item)
    last = text
  }
  return out
}

export function formatCleanupToast(res: unknown): string {
  const o = res && typeof res === 'object' ? (res as Record<string, unknown>) : {}
  const runs = Number(o.runs_deleted ?? 0) || 0
  const cache = Number(o.cache_entries_deleted ?? o.cache_deleted ?? 0) || 0
  const artifacts = Number(o.artifacts_deleted ?? 0) || 0
  if (runs === 0 && cache === 0 && artifacts === 0) return 'Nothing to delete'
  const parts: string[] = []
  if (runs) parts.push(`${runs} ${runs === 1 ? 'run' : 'runs'}`)
  if (cache) parts.push(`${cache} cache ${cache === 1 ? 'entry' : 'entries'}`)
  if (artifacts) parts.push(`${artifacts} ${artifacts === 1 ? 'artifact' : 'artifacts'}`)
  return parts.length ? `Deleted ${parts.join(', ')}` : 'Nothing to delete'
}

export function formatValidationErrors(errors: unknown): string {
  if (errors == null) return 'Invalid config'
  if (typeof errors === 'string') return errors
  if (Array.isArray(errors)) {
    const bits = errors
      .map((e) => {
        if (typeof e === 'string') return e
        if (e && typeof e === 'object') {
          const o = e as Record<string, unknown>
          return String(o.msg ?? o.message ?? o.loc ?? '')
        }
        return ''
      })
      .filter(Boolean)
    return bits.join('; ') || 'Invalid config'
  }
  if (typeof errors === 'object' && errors && 'message' in errors) {
    return String((errors as { message?: unknown }).message)
  }
  return 'Invalid config'
}

export function formatMergeToast(res: unknown): string {
  if (!res || typeof res !== 'object') return 'Merge complete'
  const o = res as Record<string, unknown>
  const n = o.merged ?? o.count ?? o.files ?? o.entries
  if (typeof n === 'number' && n >= 0) return n === 0 ? 'Nothing to merge' : `Merged ${n} sources`
  return 'Merge complete'
}

const TEMPLATE_ACRONYMS = new Set(['e2e', 'asr', 'tts', 'stt', 'llm', 'api', 'hf', 'ml', 'nlp'])

/** `ex-06-speech-commands-e2e` → “Speech commands (E2E)”. */
export function humanizeTemplateName(id: string): string {
  const raw = id.trim()
  if (!raw) return id
  const s = raw.replace(/^ex-\d+-/, '')
  const parts = s.split(/[-_]+/).filter(Boolean)
  if (parts.length === 0) return raw
  const trailing: string[] = []
  while (parts.length && TEMPLATE_ACRONYMS.has(parts[parts.length - 1].toLowerCase())) {
    trailing.unshift(parts.pop()!.toUpperCase())
  }
  const words = parts.map((w, i) => {
    const lower = w.toLowerCase()
    if (TEMPLATE_ACRONYMS.has(lower)) return lower.toUpperCase()
    if (i === 0) return lower.charAt(0).toUpperCase() + lower.slice(1)
    return lower
  })
  let out = words.join(' ')
  if (trailing.length) out = `${out}${out ? ' ' : ''}(${trailing.join(', ')})`
  return out || raw
}

export function isIsolatedRuntime(runtime?: string | null, nodeType?: string | null): boolean {
  const r = (runtime ?? '').toLowerCase()
  if (r === 'isolated' || r.includes('isolated')) return true
  return Boolean(nodeType && nodeType.startsWith('Isolated_'))
}

export function formatUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return ''
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return m ? `${h}h ${m}m` : `${h}h`
}

export function formatMetricsSummary(data: unknown): string | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const o = data as Record<string, unknown>
  const req = o.requests_total ?? o.run_count ?? o.runs
  const up = o.uptime_s ?? o.uptime
  const parts: string[] = []
  if (typeof req === 'number' && Number.isFinite(req)) {
    parts.push(`${req} ${req === 1 ? 'request' : 'requests'}`)
  }
  if (typeof up === 'number' && Number.isFinite(up) && up > 0) {
    const label = formatUptime(up)
    if (label) parts.push(`uptime ${label}`)
  }
  if (typeof o.errors_5xx_total === 'number' && o.errors_5xx_total > 0) {
    parts.push(`${o.errors_5xx_total} 5xx`)
  }
  return parts.length ? parts.join(' · ') : null
}

const HEALTH_FACT_KEYS = [
  'status',
  'timestamp',
  'ready',
  'ok',
  'version',
  'uptime_s',
  'uptime',
  'checks',
]

export function pickStatusFacts(data: unknown, max = 6): Array<{ key: string; value: unknown }> {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return []
  const o = data as Record<string, unknown>
  const out: Array<{ key: string; value: unknown }> = []
  const seen = new Set<string>()
  const push = (key: string, value: unknown) => {
    if (seen.has(key) || value === undefined) return
    seen.add(key)
    out.push({ key, value })
  }
  for (const k of HEALTH_FACT_KEYS) {
    if (!(k in o)) continue
    const v = o[k]
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const [ck, cv] of Object.entries(v as Record<string, unknown>)) {
        push(ck, cv)
        if (out.length >= max) return out
      }
    } else {
      push(k, v)
    }
    if (out.length >= max) return out
  }
  if (out.length === 0) {
    for (const [k, v] of Object.entries(o)) {
      if (v && typeof v === 'object') continue
      push(k, v)
      if (out.length >= max) break
    }
  }
  return out.slice(0, max)
}
