/**
 * Small presentational pieces for the Runs views: 8-char ids with copy on
 * hover, the multi-path comparison table, the single-path metrics row, and the
 * compact step picker used by Logs / Run outputs / Checkpoints.
 */
import clsx from 'clsx'
import { Trophy } from 'lucide-react'
import { CopyableMono } from '../../components/ui'
import { FieldSelect } from '../../components/FieldSelect'
import { shortRunId } from '../../lib/format'
import { formatMetricValue, isRatioMetric, metricLabel } from '../../lib/metrics'
import { formatStepDuration, type PathTableRow, type StepOption } from './runOverview'

/** "1e4ff50a" in mono; full id in the tooltip; copy button appears on hover. */
export function ShortId({ value, className, label = 'id' }: { value: string; className?: string; label?: string }) {
  if (!value) return null
  return (
    <span className={clsx('group inline-flex items-center gap-0.5 font-mono text-[11px] text-ink-500', className)} title={`${label} ${value}`}>
      {shortRunId(value)}
      <span className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <CopyableMono value={value} title={`Copy full ${label}`} copyOnly />
      </span>
    </span>
  )
}

function metricText(name: string, v: number): string {
  return Number.isInteger(v) && !isRatioMetric(name, v) ? v.toLocaleString() : formatMetricValue(name, v)
}

/** One table for multi-path runs: rows = paths, columns = primary + key metrics + time. */
export function PathComparisonTable({
  rows,
  primaryName,
  columns,
  activeLetter,
  onSelect,
  stacked = false,
}: {
  rows: PathTableRow[]
  primaryName: string | null
  columns: string[]
  /** Path of the focused step (row highlight). */
  activeLetter?: string | null
  onSelect?: (row: PathTableRow) => void
  /** Narrow detail pane (< ~700 px): one card per path instead of a wide table. */
  stacked?: boolean
}) {
  const anyTraining = rows.some((r) => r.trainingMs != null)
  const anyTime = rows.some((r) => r.trainingMs != null || r.totalMs != null)
  if (stacked) return <PathCards rows={rows} primaryName={primaryName} columns={columns} activeLetter={activeLetter} onSelect={onSelect} />
  return (
    <section aria-label="Path comparison" className="overflow-hidden rounded-xl border border-ink-200 bg-white">
      <div className="flex items-baseline justify-between gap-2 border-b border-ink-100 px-3 py-1.5">
        <h3 className="text-[13px] font-semibold text-ink-900">Paths compared</h3>
        <span className="text-[11px] text-ink-400">Click a path to see its steps</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left text-[12px]">
          <thead className="text-[11px] text-ink-500">
            <tr className="border-b border-ink-100">
              <th className="px-3 py-1.5 font-medium">Path</th>
              {primaryName ? <th className="px-3 py-1.5 text-right font-medium">{metricLabel(primaryName)}</th> : null}
              {columns.map((c) => (
                <th key={c} className="px-3 py-1.5 text-right font-medium" title={c}>
                  {metricLabel(c)}
                </th>
              ))}
              {anyTime ? <th className="px-3 py-1.5 text-right font-medium">{anyTraining ? 'Training time' : 'Time'}</th> : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {rows.map((r) => {
              const time = r.trainingMs ?? r.totalMs
              return (
                <tr
                  key={r.pathId}
                  className={clsx(
                    'cursor-pointer transition-colors',
                    activeLetter === r.letter ? 'bg-accent-50/60' : 'hover:bg-ink-50/70',
                  )}
                  onClick={() => onSelect?.(r)}
                  tabIndex={onSelect ? 0 : undefined}
                  onKeyDown={(e) => {
                    if (onSelect && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault()
                      onSelect(r)
                    }
                  }}
                >
                  <td
                    className="px-3 py-1.5"
                    title={
                      Object.entries(r.allMetrics)
                        .map(([k, v]) => `${metricLabel(k)} ${metricText(k, v)}`)
                        .join(' · ') || undefined
                    }
                  >
                    <span className="flex flex-wrap items-baseline gap-x-1.5">
                      <span className="font-medium text-ink-900">{r.label}</span>
                      {r.description ? <span className="text-ink-500">{r.description}</span> : null}
                      {r.best ? (
                        <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-emerald-700">
                          <Trophy className="h-3 w-3" aria-hidden /> best
                        </span>
                      ) : null}
                    </span>
                  </td>
                  {primaryName ? (
                    <td className={clsx('px-3 py-1.5 text-right tabular-nums', r.best ? 'font-semibold text-ink-950' : 'text-ink-800')}>
                      {r.primaryValue != null ? formatMetricValue(primaryName, r.primaryValue) : <span className="text-ink-300">—</span>}
                    </td>
                  ) : null}
                  {columns.map((c) => (
                    <td key={c} className="px-3 py-1.5 text-right tabular-nums text-ink-700">
                      {typeof r.values[c] === 'number' ? metricText(c, r.values[c]) : <span className="text-ink-300">—</span>}
                    </td>
                  ))}
                  {anyTime ? (
                    <td
                      className="px-3 py-1.5 text-right tabular-nums text-ink-600"
                      title={[
                        r.trainingMs != null ? `Training ${formatStepDuration(r.trainingMs)}` : '',
                        r.totalMs != null ? `All steps on this path ${formatStepDuration(r.totalMs)}` : '',
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    >
                      {time != null ? formatStepDuration(time) : <span className="text-ink-300">—</span>}
                    </td>
                  ) : null}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/** Stacked path cards: Path + description, primary metric big, 2–3 other metrics + time. */
function PathCards({
  rows,
  primaryName,
  columns,
  activeLetter,
  onSelect,
}: {
  rows: PathTableRow[]
  primaryName: string | null
  columns: string[]
  activeLetter?: string | null
  onSelect?: (row: PathTableRow) => void
}) {
  return (
    <section aria-label="Path comparison" className="rounded-xl border border-ink-200 bg-white">
      <div className="border-b border-ink-100 px-3 py-1.5">
        <h3 className="text-[13px] font-semibold text-ink-900">Paths compared</h3>
      </div>
      <ul className="divide-y divide-ink-100">
        {rows.map((r) => {
          const extras = columns.filter((c) => typeof r.values[c] === 'number').slice(0, 3)
          const time = r.trainingMs ?? r.totalMs
          return (
            <li key={r.pathId}>
              <button
                type="button"
                className={clsx(
                  'flex w-full min-w-0 items-start gap-3 px-3 py-2 text-left',
                  activeLetter === r.letter ? 'bg-accent-50/60' : 'hover:bg-ink-50/70',
                )}
                onClick={() => onSelect?.(r)}
                title={
                  Object.entries(r.allMetrics)
                    .map(([k, v]) => `${metricLabel(k)} ${metricText(k, v)}`)
                    .join(' · ') || undefined
                }
              >
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 items-baseline gap-1.5">
                    <span className="shrink-0 text-[12px] font-medium text-ink-900">{r.label}</span>
                    {r.best ? (
                      <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] font-medium text-emerald-700">
                        <Trophy className="h-3 w-3" aria-hidden /> best
                      </span>
                    ) : null}
                  </span>
                  {r.description ? <span className="block truncate text-[11px] text-ink-500">{r.description}</span> : null}
                  <span className="mt-0.5 flex flex-wrap gap-x-2.5 text-[11px] text-ink-600">
                    {extras.map((c) => (
                      <span key={c} className="tabular-nums">
                        {metricLabel(c)} <span className="font-medium text-ink-800">{metricText(c, r.values[c])}</span>
                      </span>
                    ))}
                    {time != null ? <span className="tabular-nums text-ink-500">{formatStepDuration(time)}</span> : null}
                  </span>
                </span>
                {primaryName ? (
                  <span className="shrink-0 text-right">
                    <span className="block text-[10px] text-ink-500">{metricLabel(primaryName)}</span>
                    <span className={clsx('block text-[17px] leading-tight tabular-nums', r.best ? 'font-semibold text-ink-950' : 'text-ink-800')}>
                      {r.primaryValue != null ? formatMetricValue(primaryName, r.primaryValue) : '—'}
                    </span>
                  </span>
                ) : null}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** Single-path runs: the run's metrics as one compact row (extra metrics behind a fold). */
export function CompactMetricsRow({
  metrics,
  caption,
  inline = 6,
}: {
  metrics: Record<string, number>
  caption?: string | null
  inline?: number
}) {
  const entries = Object.entries(metrics)
  if (!entries.length) return null
  const shown = entries.slice(0, inline)
  const more = entries.slice(inline)
  const cell = ([k, v]: [string, number]) => (
    <div key={k} className="min-w-0">
      <dt className="truncate text-[11px] text-ink-500" title={k}>
        {metricLabel(k)}
      </dt>
      <dd className="text-[14px] font-semibold tabular-nums text-ink-900">{metricText(k, v)}</dd>
    </div>
  )
  return (
    <section aria-label="Metrics" className="rounded-xl border border-ink-200 bg-white px-3 py-2">
      <div className="mb-1 flex items-baseline gap-2">
        <h3 className="text-[13px] font-semibold text-ink-900">Metrics</h3>
        {caption ? <span className="text-[11px] text-ink-500">{caption}</span> : null}
      </div>
      <dl className="flex flex-wrap gap-x-6 gap-y-1.5">{shown.map(cell)}</dl>
      {more.length > 0 ? (
        <details className="mt-1.5">
          <summary className="cursor-pointer select-none text-[11px] text-ink-500 hover:text-ink-800">
            {more.length} more metric{more.length === 1 ? '' : 's'}
          </summary>
          <dl className="mt-1 flex flex-wrap gap-x-6 gap-y-1.5">{more.map(cell)}</dl>
        </details>
      ) : null}
    </section>
  )
}

/** Compact step dropdown (replaces the left pipeline column). */
export function StepPicker({
  options,
  value,
  onChange,
  className,
}: {
  options: StepOption[]
  value: string | null
  onChange: (id: string | null) => void
  className?: string
}) {
  if (options.length <= 1) return null
  return (
    <FieldSelect
      className={clsx('w-[15rem] max-w-full shrink-0', className)}
      allowEmpty={false}
      value={value ?? ''}
      onChange={(v) => onChange(v || null)}
      aria-label="Step"
      options={options}
      triggerClassName="!mt-0 !py-1 rounded-md border border-ink-200 bg-white px-2 text-[12px] text-ink-800"
    />
  )
}
