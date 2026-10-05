/**
 * Cron input + presets + live plain-English preview (`lib/cron.ts`). Used by
 * the Editor Triggers dock and Ops → Schedules.
 */
import clsx from 'clsx'
import { CRON_PRESETS, describeCron } from '../lib/cron'

export function CronField({
  value,
  onChange,
  compact = false,
  inputClassName,
}: {
  value: string
  onChange: (v: string) => void
  compact?: boolean
  inputClassName?: string
}) {
  const preview = describeCron(value)
  return (
    <div className={compact ? 'space-y-1' : 'space-y-1.5'}>
      <input
        className={inputClassName ?? 'field-control mt-0 font-mono text-xs'}
        value={value}
        placeholder="0 9 * * 1-5"
        spellCheck={false}
        aria-label="Cron expression (minute hour day month weekday, UTC)"
        aria-invalid={!preview.ok}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className={clsx('text-[11px]', preview.ok ? 'text-ink-600' : 'font-medium text-rose-700')} aria-live="polite">
        {preview.ok ? `Runs ${preview.text}` : preview.error}
      </p>
      <div className="flex flex-wrap gap-1">
        {CRON_PRESETS.map((p) => (
          <button
            key={p.cron}
            type="button"
            className={clsx(
              'rounded border px-1.5 py-px text-[10px]',
              value.trim() === p.cron ? 'border-ink-700 text-ink-900' : 'border-ink-200 text-ink-500 hover:text-ink-800',
            )}
            title={p.cron}
            onClick={() => onChange(p.cron)}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  )
}
