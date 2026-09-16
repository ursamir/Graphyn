/**
 * Global run-detail node picker — numbered pipeline stack with All on top.
 * Labels stay readable; status is a small dot (full status in title tooltip).
 */
import { Layers } from 'lucide-react'
import { humanNodeLabel, focusMatchesNode } from '../../lib/format'
import clsx from 'clsx'

export type PipelineStackItem = {
  id: string
  status?: string
}

function statusDotClass(status?: string): string {
  const s = String(status || '').toLowerCase()
  if (['succeeded', 'completed', 'success', 'done'].includes(s)) return 'bg-emerald-500'
  if (['failed', 'error'].includes(s)) return 'bg-rose-500'
  if (['running', 'queued', 'paused', 'pending'].includes(s)) return 'bg-sky-500'
  if (['cancelled', 'canceled'].includes(s)) return 'bg-ink-400'
  return 'bg-ink-300'
}

export function PipelineStack({
  items,
  value,
  onChange,
  className,
}: {
  items: PipelineStackItem[]
  /** null = All (whole run). */
  value: string | null
  onChange: (id: string | null) => void
  className?: string
}) {
  if (items.length === 0) return null

  return (
    <nav
      aria-label="Pipeline focus"
      className={clsx(
        'flex w-[15rem] min-w-[15rem] max-w-[15rem] shrink-0 grow-0 flex-col gap-1 overflow-y-auto rounded-xl border border-ink-200 bg-white p-1.5',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onChange(null)}
        className={clsx(
          'flex w-full items-center gap-2.5 rounded-xl border px-2.5 py-2 text-left transition',
          value == null
            ? 'border-accent-400 bg-white shadow-sm ring-1 ring-accent-200'
            : 'border-transparent bg-transparent hover:border-ink-200 hover:bg-ink-50/80',
        )}
      >
        <span
          className={clsx(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
            value == null ? 'bg-accent-100 text-accent-800' : 'bg-ink-100 text-ink-600',
          )}
        >
          <Layers className="h-3.5 w-3.5" />
        </span>
        <span className="min-w-0 flex-1 text-sm font-semibold leading-snug text-ink-900">All</span>
      </button>
      <ol className="space-y-1">
        {items.map((item, idx) => {
          const active = value != null && focusMatchesNode(value, item.id)
          const label = humanNodeLabel(item.id)
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onChange(item.id)}
                title={item.status ? `${label} · ${item.status}` : label}
                className={clsx(
                  'flex w-full items-start gap-2.5 rounded-xl border px-2.5 py-2 text-left transition',
                  active
                    ? 'border-accent-400 bg-white shadow-sm ring-1 ring-accent-200'
                    : 'border-transparent bg-transparent hover:border-ink-200 hover:bg-ink-50/80',
                )}
              >
                <span
                  className={clsx(
                    'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                    active ? 'bg-accent-100 text-accent-800' : 'bg-ink-100 text-ink-600',
                  )}
                >
                  {idx + 1}
                </span>
                <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-ink-900">
                  {label}
                </span>
                {item.status ? (
                  <span
                    className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', statusDotClass(item.status))}
                    aria-label={item.status}
                  />
                ) : null}
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
