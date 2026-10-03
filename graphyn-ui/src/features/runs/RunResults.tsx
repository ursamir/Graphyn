/**
 * Results-first run presentation: headline banner (primary metric per path,
 * dataset, regression vs best earlier run), per-path metric chips, evaluator
 * detail (per-class table + confusion matrix), and the compact live progress
 * line used in Runs → Logs and the Editor execution log.
 */
import React from 'react'
import clsx from 'clsx'
import { Trophy, TrendingDown, TrendingUp } from 'lucide-react'
import { fetchOutputBlobUrl } from '../../api/client'
import { formatDelta, formatMetric, metricLabel } from '../../lib/metrics'
import { shortRunId } from '../../lib/format'
import {
  confusionMatrix,
  datasetSentence,
  isRegression,
  pathDisplayName,
  perClassRows,
  type DatasetInfo,
  type PathResult,
  type RegressionView,
} from './runResults'
import {
  progressSeries,
  sparklinePoints,
  type NodeProgress,
} from './runProgress'

/** Small "Test accuracy 0.561 ★" chip for a path. */
export function PathMetricChip({ path, best }: { path: PathResult; best?: boolean }) {
  if (!path.primary) return null
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ring-1',
        best ? 'bg-emerald-50 text-emerald-900 ring-emerald-200' : 'bg-white text-ink-800 ring-ink-200',
      )}
      title={Object.entries(path.metrics)
        .map(([k, v]) => `${metricLabel(k)} ${formatMetric(v)}`)
        .join(' · ')}
    >
      {best ? <Trophy className="h-3 w-3 text-emerald-600" aria-label="best" /> : null}
      {metricLabel(path.primary.name)} {formatMetric(path.primary.value)}
    </span>
  )
}

/**
 * Headline: "Test accuracy 0.561 · Path A (DS-CNN · 50 epochs) — best",
 * other paths, dataset sentence, and a regression badge.
 */
export function RunResultsBanner({
  paths,
  bestPathId,
  dataset,
  regression,
  onOpenRun,
  onFocusPath,
}: {
  paths: PathResult[]
  bestPathId: string | null
  dataset: DatasetInfo | null
  regression: RegressionView | null
  onOpenRun?: (runId: string) => void
  onFocusPath?: (path: PathResult) => void
}) {
  const scored = paths.filter((p) => p.primary)
  if (scored.length === 0 && !dataset) return null
  const best = scored.find((p) => p.pathId === bestPathId) || scored[0] || null
  const others = scored.filter((p) => p !== best)
  const multi = paths.length > 1
  const regressed = regression ? isRegression(regression) : false
  const improved = regression ? !regressed && Math.abs(regression.delta) > 0.005 : false
  return (
    <div className="rounded-lg border border-ink-200 bg-gradient-to-r from-emerald-50/70 to-white px-3 py-2" aria-label="Run results">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {best?.primary ? (
          <button
            type="button"
            className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-left"
            onClick={() => onFocusPath?.(best)}
            title={multi ? 'Show this path' : undefined}
          >
            <span className="text-[12px] font-medium text-ink-600">{metricLabel(best.primary.name)}</span>
            <span className="text-[20px] font-semibold leading-none tabular-nums text-ink-950">
              {formatMetric(best.primary.value)}
            </span>
            {multi ? (
              <span className="text-[12px] text-ink-700">
                · {pathDisplayName(best)}
                {others.length > 0 ? <span className="font-semibold text-emerald-700"> — best</span> : null}
              </span>
            ) : best.description ? (
              <span className="text-[12px] text-ink-600">· {best.description}</span>
            ) : null}
          </button>
        ) : null}
        {others.map((p) => (
          <button
            key={p.pathId}
            type="button"
            className="text-[12px] text-ink-600 hover:text-ink-900"
            onClick={() => onFocusPath?.(p)}
            title="Show this path"
          >
            {pathDisplayName(p)}{' '}
            <span className="font-semibold tabular-nums text-ink-800">{formatMetric(p.primary!.value)}</span>
          </button>
        ))}
        {regression ? (
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold',
              regressed ? 'bg-rose-100 text-rose-900' : improved ? 'bg-emerald-100 text-emerald-900' : 'bg-ink-100 text-ink-700',
            )}
            title={`Compared with the best earlier run of this pipeline (${metricLabel(regression.metricName)})`}
          >
            {regressed ? <TrendingDown className="h-3 w-3" /> : improved ? <TrendingUp className="h-3 w-3" /> : null}
            {regressed || improved ? '' : '= '}
            {formatDelta(regression.delta)}
            {regression.previousValue != null ? ` vs best ${formatMetric(regression.previousValue)}` : ''}
            {regression.previousRunId ? (
              <>
                {' · run '}
                {onOpenRun ? (
                  <button
                    type="button"
                    className="font-mono underline-offset-2 hover:underline"
                    onClick={() => onOpenRun(regression.previousRunId!)}
                    title="Open that run"
                  >
                    {shortRunId(regression.previousRunId)} — open
                  </button>
                ) : (
                  <span className="font-mono">{shortRunId(regression.previousRunId)}</span>
                )}
              </>
            ) : null}
          </span>
        ) : null}
      </div>
      {dataset ? (
        <p className="mt-1 text-[11px] text-ink-500" title={dataset.source || undefined}>
          {datasetSentence(dataset)}
          {dataset.fallbackUsed ? (
            <span className="ml-1 rounded bg-amber-100 px-1 text-amber-900">sample data used — dataset path was empty</span>
          ) : null}
        </p>
      ) : null}
    </div>
  )
}

function pct(v: number | null): string {
  return v == null ? '—' : formatMetric(v)
}

/** Confusion matrix as a tiny heat grid (rows = true label, cols = predicted). */
function ConfusionGrid({ matrix, labels }: { matrix: number[][]; labels: string[] }) {
  const max = Math.max(1, ...matrix.flat())
  const n = matrix.length
  const cell = n <= 6 ? 18 : n <= 12 ? 12 : 8
  return (
    <div className="inline-block">
      <div className="mb-0.5 text-[10px] text-ink-400">rows: true label · columns: predicted</div>
      <div className="grid gap-px" style={{ gridTemplateColumns: `repeat(${n}, ${cell}px)` }}>
        {matrix.flatMap((row, i) =>
          row.map((v, j) => {
            const a = v / max
            return (
              <div
                key={`${i}-${j}`}
                className={clsx('flex items-center justify-center text-[9px] tabular-nums', a > 0.55 ? 'text-white' : 'text-ink-700')}
                style={{
                  width: cell,
                  height: cell,
                  background: i === j ? `rgba(16,185,129,${0.12 + a * 0.88})` : `rgba(244,63,94,${a * 0.85})`,
                }}
                title={`${labels[i] ?? i} → ${labels[j] ?? j}: ${v}`}
              >
                {cell >= 18 ? v : null}
              </div>
            )
          }),
        )}
      </div>
    </div>
  )
}

function BlobImage({ path, alt }: { path: string; alt: string }) {
  const [url, setUrl] = React.useState<string | null>(null)
  React.useEffect(() => {
    let created: string | null = null
    const ctrl = new AbortController()
    void fetchOutputBlobUrl(path, { signal: ctrl.signal })
      .then((u) => {
        created = u
        setUrl(u)
      })
      .catch(() => setUrl(null))
    return () => {
      ctrl.abort()
      if (created) URL.revokeObjectURL(created)
    }
  }, [path])
  if (!url) return null
  return <img src={url} alt={alt} className="max-h-40 rounded border border-ink-200 bg-white" />
}

/** Evaluator detail for the step story: headline metrics, per-class table, confusion matrix. */
export function EvaluatorResult({
  metrics,
  confusionImagePath,
  path,
}: {
  metrics: unknown
  confusionImagePath?: string
  path?: PathResult | null
}) {
  const rows = perClassRows(metrics)
  const matrix = confusionMatrix(metrics)
  const scalars = Object.entries((metrics as Record<string, unknown>) || {}).filter(
    ([, v]) => typeof v === 'number' && Number.isFinite(v),
  ) as Array<[string, number]>
  if (!scalars.length && !rows.length && !matrix && !confusionImagePath) return null
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-ink-200 bg-white px-2.5 py-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          Results{path ? ` · ${pathDisplayName(path)}` : ''}
        </span>
        {scalars.map(([k, v]) => (
          <span key={k} className="text-[12px] text-ink-700">
            {metricLabel(k)} <span className="font-semibold tabular-nums text-ink-950">{formatMetric(v)}</span>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-start gap-4">
        {rows.length > 0 ? (
          <table className="text-[11px] tabular-nums">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-ink-400">
                <th className="pr-3 font-semibold">Class</th>
                <th className="pr-3 font-semibold">Precision</th>
                <th className="pr-3 font-semibold">Recall</th>
                <th className="font-semibold">F1</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="text-ink-800">
                  <td className="pr-3 font-medium">{r.label}</td>
                  <td className="pr-3">{pct(r.precision)}</td>
                  <td className="pr-3">{pct(r.recall)}</td>
                  <td className={clsx(r.f1 != null && r.f1 < 0.5 ? 'text-rose-700' : '')}>{pct(r.f1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {matrix ? (
          <ConfusionGrid matrix={matrix} labels={rows.map((r) => r.label)} />
        ) : confusionImagePath ? (
          <BlobImage path={confusionImagePath} alt="Confusion matrix" />
        ) : null}
      </div>
    </div>
  )
}

/** Inline sparkline (SVG polyline). */
export function Sparkline({
  values,
  width = 64,
  height = 14,
  className,
}: {
  values: number[]
  width?: number
  height?: number
  className?: string
}) {
  const pts = sparklinePoints(values, width, height)
  if (!pts) return null
  return (
    <svg width={width} height={height} className={clsx('shrink-0 overflow-visible', className)} aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}

/** Thin progress bar (0..100). */
export function ProgressBar({ pct: value, className, tone = 'bg-accent-500' }: { pct: number | null; className?: string; tone?: string }) {
  if (value == null) return null
  return (
    <span
      className={clsx('inline-block h-1.5 overflow-hidden rounded-full bg-black/10', className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span className={clsx('block h-full rounded-full transition-[width]', tone)} style={{ width: `${Math.max(2, value)}%` }} />
    </span>
  )
}

/**
 * One-line live progress row: text · bar · sparkline (history) · "N updates".
 * `dark` for the log panels (dark background).
 */
export function ProgressLogLine({
  text,
  progress,
  history,
  count,
  dark = true,
}: {
  text: string
  progress: NodeProgress
  history: NodeProgress[]
  count: number
  dark?: boolean
}) {
  const series = progressSeries(history)
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 truncate">{text}</span>
      <ProgressBar pct={progress.pct} className="w-20 shrink-0" tone={dark ? 'bg-sky-400' : 'bg-accent-500'} />
      {series ? (
        <span className={clsx('inline-flex items-center gap-1 text-[10px]', dark ? 'text-sky-300' : 'text-accent-700')} title={`${series.name} over time`}>
          <Sparkline values={series.values} width={56} height={12} />
          {series.name}
        </span>
      ) : null}
      {count > 1 ? (
        <span className={clsx('shrink-0 text-[10px]', dark ? 'text-ink-500' : 'text-ink-400')}>{count} updates</span>
      ) : null}
    </span>
  )
}
