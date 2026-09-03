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
