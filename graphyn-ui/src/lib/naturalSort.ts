/**
 * Natural ("human") string order: nohash_2 before nohash_10 — without
 * mangling hex-like ids. A plain numeric collator splits `03401e93` into
 * 3401 · e · 93 and `0c540988` into 0 · c · 540988, which put
 * `03401e93_nohash_0.wav` far away from its lexicographic neighbours in the
 * Speech Commands listing. Runs of ≥6 hex chars that mix digits and a–f
 * letters are therefore compared as plain strings; other digit runs compare
 * numerically.
 */
export const naturalCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

const plainCollator = new Intl.Collator(undefined, { sensitivity: 'base' })

type Token = { num: string } | { text: string }

const HEXISH = /[0-9a-f]{6,}/gi

function isHexId(s: string): boolean {
  return /[0-9]/.test(s) && /[a-f]/i.test(s)
}

function pushDigitSplit(out: Token[], s: string) {
  for (const part of s.split(/(\d+)/)) {
    if (!part) continue
    if (/^\d+$/.test(part)) out.push({ num: part })
    else out.push({ text: part })
  }
}

/** Exported for tests. */
export function naturalTokens(s: string): Token[] {
  const out: Token[] = []
  let last = 0
  for (const m of s.matchAll(HEXISH)) {
    const start = m.index ?? 0
    if (!isHexId(m[0])) continue
    pushDigitSplit(out, s.slice(last, start))
    out.push({ text: m[0] })
    last = start + m[0].length
  }
  pushDigitSplit(out, s.slice(last))
  // merge adjacent text tokens so "abc" + "123def…" style splits compare as one string
  const merged: Token[] = []
  for (const t of out) {
    const prev = merged[merged.length - 1]
    if (prev && 'text' in prev && 'text' in t) merged[merged.length - 1] = { text: prev.text + t.text }
    else merged.push(t)
  }
  return merged
}

function compareNumeric(a: string, b: string): number {
  const x = a.replace(/^0+(?=\d)/, '')
  const y = b.replace(/^0+(?=\d)/, '')
  if (x.length !== y.length) return x.length - y.length
  return x < y ? -1 : x > y ? 1 : 0
}

export function naturalCompare(a: string, b: string): number {
  const ta = naturalTokens(a)
  const tb = naturalTokens(b)
  const n = Math.min(ta.length, tb.length)
  for (let i = 0; i < n; i++) {
    const x = ta[i]
    const y = tb[i]
    let c: number
    if ('num' in x && 'num' in y) c = compareNumeric(x.num, y.num)
    else c = plainCollator.compare('num' in x ? x.num : x.text, 'num' in y ? y.num : y.text)
    if (c !== 0) return c
  }
  if (ta.length !== tb.length) return ta.length - tb.length
  return plainCollator.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0)
}
