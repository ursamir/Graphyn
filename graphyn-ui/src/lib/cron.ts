/**
 * Human-readable previews for schedule cadences (Ops → Schedules, Editor
 * Triggers dock). Mirrors the backend parser (`app/core/pipelines/cron.py`):
 * 5 fields `minute hour day-of-month month day-of-week`, evaluated in UTC;
 * each field accepts `*`, `N`, `A-B`, `* /S`, `A-B/S`, `N/S` and comma lists;
 * month / weekday accept names (jan…dec, sun…sat); weekday 0 and 7 are
 * Sunday; macros @hourly, @daily/@midnight, @weekly, @monthly, @yearly/@annually.
 * Pure + unit-tested (cron.test.ts).
 */

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

const MACROS: Record<string, string> = {
  '@hourly': '0 * * * *',
  '@daily': '0 0 * * *',
  '@midnight': '0 0 * * *',
  '@weekly': '0 0 * * 0',
  '@monthly': '0 0 1 * *',
  '@yearly': '0 0 1 1 *',
  '@annually': '0 0 1 1 *',
}

type Field = {
  /** Expanded values (sorted, unique). */
  values: number[]
  star: boolean
  /** `*\/S` (or `A-B/S` / `N/S`) step, when the whole field is one stepped part. */
  step: number | null
  raw: string
}

function value(token: string, lo: number, hi: number, names?: string[]): number {
  const t = token.trim().toLowerCase()
  if (names) {
    const idx = names.indexOf(t)
    if (idx >= 0) return names === MONTHS ? idx + 1 : idx
  }
  if (!/^\d+$/.test(t)) throw new Error(`invalid value “${token}”`)
  const v = Number(t)
  if (v < lo || v > hi) throw new Error(`value ${v} out of range ${lo}–${hi}`)
  return v
}

function parseField(text: string, lo: number, hi: number, names?: string[]): Field {
  const raw = text.trim()
  const out = new Set<number>()
  let step: number | null = null
  const parts = raw.split(',')
  for (const partRaw of parts) {
    const part = partRaw.trim()
    if (!part) throw new Error('empty list item')
    let base = part
    let s = 1
    if (part.includes('/')) {
      const [b, st] = part.split('/')
      if (!/^\d+$/.test(st ?? '') || Number(st) < 1) throw new Error(`invalid step “${part}”`)
      s = Number(st)
      base = b
      if (parts.length === 1) step = s
    }
    let a: number
    let b: number
    if (base === '*') {
      a = lo
      b = hi
    } else if (base.includes('-')) {
      const [x, y] = base.split('-')
      a = value(x, lo, hi, names)
      b = value(y, lo, hi, names)
      if (a > b) throw new Error(`range ${base} is reversed`)
    } else {
      a = value(base, lo, hi, names)
      b = part.includes('/') ? hi : a
    }
    for (let v = a; v <= b; v += s) out.add(v)
  }
  return { values: [...out].sort((x, y) => x - y), star: raw === '*', step, raw }
}

export type CronPreview = { ok: true; text: string; normalized: string } | { ok: false; error: string }

const pad = (n: number) => String(n).padStart(2, '0')

function listText(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** Consecutive run (≥3 items) → "A–B", else null. */
function asRange(values: number[]): [number, number] | null {
  if (values.length < 3) return null
  for (let i = 1; i < values.length; i++) if (values[i] !== values[i - 1] + 1) return null
  return [values[0], values[values.length - 1]]
}

function timeText(min: Field, hour: Field): { text: string; atTime: boolean } {
  const everyHour = hour.star
  if (min.star && everyHour) return { text: 'every minute', atTime: false }
  if (min.step && min.raw.startsWith('*') && everyHour) {
    return { text: min.step === 1 ? 'every minute' : `every ${min.step} minutes`, atTime: false }
  }
  if (min.values.length === 1 && everyHour) {
    return { text: min.values[0] === 0 ? 'every hour' : `every hour at :${pad(min.values[0])}`, atTime: false }
  }
  if (min.values.length === 1 && hour.step && hour.raw.startsWith('*')) {
    return {
      text: `every ${hour.step} hours${min.values[0] ? ` at :${pad(min.values[0])}` : ''}`,
      atTime: false,
    }
  }
  if (min.values.length * hour.values.length <= 4 && !min.star && !hour.star) {
    const times: string[] = []
    for (const h of hour.values) for (const m of min.values) times.push(`${pad(h)}:${pad(m)}`)
    return { text: `at ${listText(times)}`, atTime: true }
  }
  const hr = asRange(hour.values)
  const hourPart = hour.star
    ? ''
    : hr
      ? ` between ${pad(hr[0])}:00 and ${pad(hr[1])}:59`
      : ` during hours ${hour.values.map(pad).join(', ')}`
  if (min.step && min.raw.startsWith('*')) return { text: `every ${min.step} minutes${hourPart}`, atTime: false }
  if (min.values.length === 1) {
    return { text: `every hour at :${pad(min.values[0])}${hourPart}`, atTime: false }
  }
  return { text: `at minutes ${min.values.map(pad).join(', ')}${hourPart}`, atTime: false }
}

function dowText(dow: Field): string {
  const days = [...new Set(dow.values.map((d) => (d === 7 ? 0 : d)))].sort((a, b) => a - b)
  const key = days.join(',')
  if (key === '1,2,3,4,5') return 'every weekday'
  if (key === '0,6') return 'on weekends'
  if (days.length === 7) return 'every day'
  if (days.length === 1) return `every ${DAY_NAMES[days[0]]}`
  const r = asRange(days)
  if (r) return `${DAY_NAMES[r[0]]} through ${DAY_NAMES[r[1]]}`
  return `on ${listText(days.map((d) => DAY_NAMES[d]))}`
}

function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] || 'th'
  return `${n}${s}`
}

/**
 * "0 9 * * 1-5" → "every weekday at 09:00 UTC"; "*\/15 * * * *" → "every 15
 * minutes"; invalid → { ok:false, error }.
 */
export function describeCron(expr: string): CronPreview {
  const input = String(expr ?? '').trim()
  if (!input) return { ok: false, error: 'Enter a cron expression' }
  const text = MACROS[input.toLowerCase()] ?? input
  const parts = text.split(/\s+/)
  if (parts.length !== 5) {
    return { ok: false, error: `Cron needs 5 fields (minute hour day month weekday), got ${parts.length}` }
  }
  let min: Field, hour: Field, dom: Field, mon: Field, dow: Field
  try {
    min = parseField(parts[0], 0, 59)
    hour = parseField(parts[1], 0, 23)
    dom = parseField(parts[2], 1, 31)
    mon = parseField(parts[3], 1, 12, MONTHS)
    dow = parseField(parts[4], 0, 7, DAYS)
  } catch (err) {
    return { ok: false, error: `Invalid cron: ${err instanceof Error ? err.message : String(err)}` }
  }
  const t = timeText(min, hour)
  let day = ''
  if (!dom.star && !dow.star) {
    day = `on day ${listText(dom.values.map(String))} of the month or ${dowText(dow).replace(/^every |^on /, '')}`
  } else if (!dow.star) {
    day = dowText(dow)
  } else if (!dom.star) {
    day =
      dom.values.length === 1
        ? `on the ${ordinal(dom.values[0])} of the month`
        : `on days ${listText(dom.values.map(String))} of the month`
  }
  let month = ''
  if (!mon.star) month = `in ${listText(mon.values.map((m) => MONTH_NAMES[m - 1]))}`

  let sentence: string
  if (t.atTime) {
    sentence = [day || 'every day', month, t.text].filter(Boolean).join(' ')
  } else {
    sentence = [t.text, day, month].filter(Boolean).join(' ')
  }
  const needsUtc = t.atTime || /:\d\d/.test(t.text)
  return { ok: true, text: `${sentence}${needsUtc ? ' UTC' : ''}`, normalized: text }
}

/** 60 → "every hour", 1440 → "every day", 90 → "every 90 minutes". */
export function intervalText(minutes: unknown): string {
  const m = Number(minutes)
  if (!Number.isFinite(m) || m <= 0) return 'interval not set'
  if (m === 1) return 'every minute'
  if (m % 1440 === 0) return m === 1440 ? 'every day' : `every ${m / 1440} days`
  if (m % 60 === 0) return m === 60 ? 'every hour' : `every ${m / 60} hours`
  return `every ${m} minutes`
}

/** One-line cadence for a schedule row: the cron preview (raw cron in `raw`), else the interval. */
export function scheduleCadence(row: { cron?: unknown; interval_minutes?: unknown }): { text: string; raw: string } {
  const cron = typeof row.cron === 'string' ? row.cron.trim() : ''
  if (cron) {
    const p = describeCron(cron)
    return { text: p.ok ? p.text : cron, raw: cron }
  }
  return { text: intervalText(row.interval_minutes), raw: '' }
}

/** Quick picks for the cron field. */
export const CRON_PRESETS: Array<{ label: string; cron: string }> = [
  { label: 'Every 15 minutes', cron: '*/15 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Daily 02:00', cron: '0 2 * * *' },
  { label: 'Weekdays 09:00', cron: '0 9 * * 1-5' },
  { label: 'Mondays 06:00', cron: '0 6 * * 1' },
  { label: 'Monthly (1st)', cron: '0 0 1 * *' },
]
