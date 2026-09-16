/** Minimal SVG bar chart for compare metrics — no extra chart dependency. */
export function MetricBars({
  title,
  series,
}: {
  title: string
  series: Array<{ label: string; value: number }>
}) {
  const max = Math.max(...series.map((s) => Math.abs(s.value)), 1e-9)
  if (series.length === 0) return null
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-400">{title}</div>
      <div className="space-y-1.5">
        {series.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-[11px]">
            <span className="w-16 truncate font-mono text-ink-500" title={s.label}>
              {s.label}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded bg-ink-100">
              <div
                className="h-full rounded bg-accent-500"
                style={{ width: `${Math.min(100, (Math.abs(s.value) / max) * 100)}%` }}
              />
            </div>
            <span className="w-14 text-right font-mono text-ink-700">{s.value.toPrecision(4)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
