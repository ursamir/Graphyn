/**
 * Pretty-log dedupe for execution logs (Editor log panel + Runs → Logs).
 *
 * One node failure is reported twice by the engine: a `node_error` event
 * ("Audio Conditioner · failed · Sample rate should be over 0") followed by
 * the pipeline-level `error` event carrying the same message without a node
 * ("Sample rate should be over 0"). Both rendered and both counted, so the
 * header read "2 errors" for one failure.
 *
 * `dedupeErrorRows` drops an error row whose core message equals the previous
 * error row's core message (until another node starts). The raw view is not
 * passed through this — it stays a faithful event dump.
 *
 * No React here so it can be unit-tested in the node vitest env.
 */

/** "Label · failed · msg" → "msg"; "msg" → "msg" (trimmed, lowercased). */
export function errorCore(text: string): string {
  const t = String(text || '').trim()
  const m = t.match(/^.+? · failed · ([\s\S]*)$/)
  return (m ? m[1] : t).trim().toLowerCase()
}

/** Summary lines that restate the failure rather than being a failure of their own. */
export function isErrorSummaryLine(text: string): boolean {
  return /^pipeline (finished with errors|failed)\b/i.test(String(text || '').trim())
}

export function isErrorRow(level: string | undefined, text: string): boolean {
  return level === 'error' || /fail|error/i.test(text)
}

/**
 * Drop repeated error rows that restate the previous error. `textOf` /
 * `levelOf` read the pretty text and level of a row. A row whose text reads
 * like a node starting (`· started`) resets the window so the same message
 * from a later, different failure is still shown.
 */
export function dedupeErrorRows<T>(
  rows: T[],
  textOf: (row: T) => string,
  levelOf: (row: T) => string | undefined,
): T[] {
  const out: T[] = []
  let lastCore: string | null = null
  for (const row of rows) {
    const text = textOf(row)
    const level = levelOf(row)
    if (isErrorRow(level, text) && !isErrorSummaryLine(text)) {
      const core = errorCore(text)
      if (core && lastCore === core) continue
      lastCore = core
      out.push(row)
      continue
    }
    if (/ · started$/.test(String(text || '').trim())) lastCore = null
    out.push(row)
  }
  return out
}

/** Error count for a log header: real failures only, not "finished with errors" summaries. */
export function countErrorRows<T>(
  rows: T[],
  textOf: (row: T) => string,
  levelOf: (row: T) => string | undefined,
): number {
  let n = 0
  for (const row of rows) {
    const text = textOf(row)
    if (isErrorRow(levelOf(row), text) && !isErrorSummaryLine(text)) n++
  }
  return n
}
