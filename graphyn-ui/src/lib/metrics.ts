/**
 * Shared metric helpers — one number format across Home, Activity, Models,
 * Ship and Runs. Domain-agnostic: accuracy-like names are only a preference
 * order for picking a headline number; any finite scalar is formattable.
 *
 * Backend contract (UX API draft): runs carry
 *   `summary.primary_metric = { name, value }` (preference
 *   test_accuracy > accuracy > val_accuracy > f1) and
 *   `regression = { best_previous_run_id, best_previous_value, delta }`.
 * Older APIs only expose a flat `metrics` object — `primaryMetric` falls back
 * to the same preference order over it.
 */

export type MetricFormatOptions = {
  /** Render 0..1 values as a percentage ("56.1%"). */
  percent?: boolean
  /** Significant decimals for non-integers (default 3 → 0.5611 → "0.561"). */
  digits?: number
}

/** 0.5611 → "0.561"; 12 → "12"; {percent:true} 0.5611 → "56.1%"; non-numbers → "—". */
export function formatMetric(value: unknown, opts: MetricFormatOptions = {}): string {
  const n = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  if (typeof n !== 'number' || !Number.isFinite(n)) return '—'
  if (opts.percent && Math.abs(n) <= 1) {
    const pct = n * 100
    return `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`
  }
  if (Number.isInteger(n)) return String(n)
  const digits = opts.digits ?? 3
  const abs = Math.abs(n)
  if (abs !== 0 && abs < 10 ** -digits) return n.toExponential(1)
  return n.toFixed(digits)
}

/** "test_accuracy" → "Test accuracy"; "roc_auc" → "ROC AUC"; "f1" → "F1". */
export function metricLabel(name: string): string {
  const special: Record<string, string> = {
    roc_auc: 'ROC AUC',
    auc: 'AUC',
    f1: 'F1',
    f1_score: 'F1 score',
    mae: 'MAE',
    mse: 'MSE',
    rmse: 'RMSE',
    val_accuracy: 'Validation accuracy',
    val_loss: 'Validation loss',
    acc: 'Accuracy',
  }
  const key = name.trim().toLowerCase()
  if (special[key]) return special[key]
  const words = key.replace(/[_-]+/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name
}

/** Ratio-like metrics where a percent reads naturally. */
export function isRatioMetric(name: string, value?: unknown): boolean {
  const k = name.toLowerCase()
  const ratioName = /(accuracy|acc$|precision|recall|f1|auc)/.test(k)
  if (!ratioName) return false
  return typeof value !== 'number' || (value >= 0 && value <= 1)
}

export const PRIMARY_METRIC_PREFERENCE = ['test_accuracy', 'accuracy', 'val_accuracy', 'f1', 'acc'] as const

export type PrimaryMetric = { name: string; value: number }

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

function finite(v: unknown): number | null {
  const n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** Headline metric from a flat metrics object by preference order (null if none). */
export function pickPrimaryMetric(metrics: unknown): PrimaryMetric | null {
  const o = asRecord(metrics)
  if (!o) return null
  for (const k of PRIMARY_METRIC_PREFERENCE) {
    const v = finite(o[k])
    if (v != null) return { name: k === 'acc' ? 'accuracy' : k, value: v }
  }
  return null
}

/**
 * Headline metric for a run row / run detail: `summary.primary_metric` (new API),
 * else `primary_metric` at top level or under `meta`, else preference order over
 * `metrics` / `meta.metrics`.
 */
export function primaryMetric(run: unknown): PrimaryMetric | null {
  const r = asRecord(run)
  if (!r) return null
  const meta = asRecord(r.meta)
  const summary = asRecord(r.summary) ?? asRecord(meta?.summary)
  for (const cand of [summary?.primary_metric, r.primary_metric, meta?.primary_metric]) {
    const pm = asRecord(cand)
    if (!pm) continue
    const v = finite(pm.value)
    const name = typeof pm.name === 'string' ? pm.name : typeof pm.key === 'string' ? pm.key : null
    if (v != null && name) return { name, value: v }
  }
  return pickPrimaryMetric(r.metrics) ?? pickPrimaryMetric(meta?.metrics)
}

/** "Test accuracy 0.561" (or "… 56.1%" with percent). Null when no metric. */
export function formatPrimaryMetric(run: unknown, opts: MetricFormatOptions = {}): string | null {
  const pm = primaryMetric(run)
  if (!pm) return null
  return `${metricLabel(pm.name)} ${formatMetric(pm.value, opts)}`
}

export type RegressionInfo = { delta: number; previousValue: number | null; previousRunId: string | null }

/** `regression` block from a run row / detail; null when absent or not numeric. */
export function regressionOf(run: unknown): RegressionInfo | null {
  const r = asRecord(run)
  if (!r) return null
  const reg = asRecord(r.regression) ?? asRecord(asRecord(r.meta)?.regression)
  if (!reg) return null
  const delta = finite(reg.delta)
  if (delta == null) return null
  return {
    delta,
    previousValue: finite(reg.best_previous_value),
    previousRunId: typeof reg.best_previous_run_id === 'string' ? reg.best_previous_run_id : null,
  }
}

/** "+0.041" / "−0.020" — signed delta with the same precision as formatMetric. */
export function formatDelta(delta: number, opts: MetricFormatOptions = {}): string {
  if (!Number.isFinite(delta)) return '—'
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '±'
  return `${sign}${formatMetric(Math.abs(delta), opts)}`
}
