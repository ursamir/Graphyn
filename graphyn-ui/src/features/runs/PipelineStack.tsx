/**
 * Global run-detail node picker — numbered pipeline stack with All on top.
 * Labels stay readable; status is a small dot (full status in title tooltip).
 * When a fork/parallel shape is known, items group under Shared / Path A·B
 * (numbers stay execution-order so they match the Overview timeline).
 */
import { Fragment } from 'react'
import { Layers } from 'lucide-react'
import { humanNodeLabel, focusMatchesNode } from '../../lib/format'
import { looksLikeOpaqueId } from './runOutputs'
import { laneLabel } from './runNodes'
import { progressBadgeText, type NodeProgress } from './runProgress'
import clsx from 'clsx'

export type PipelineStackItem = {
  id: string
  /** Display label (graph node label); falls back to a humanized id. */
  label?: string
  status?: string
}

function statusDotClass(status?: string): string {
  const s = String(status || '').toLowerCase()
  if (['succeeded', 'completed', 'success', 'done'].includes(s)) return 'bg-emerald-500'
  if (['failed', 'error'].includes(s)) return 'bg-rose-500'
  if (s === 'running') return 'bg-sky-500 animate-pulse ring-2 ring-sky-200'
  if (['queued', 'paused', 'pending'].includes(s)) return 'bg-sky-500'
  if (['cancelled', 'canceled'].includes(s)) return 'bg-ink-400'
  if (s === 'skipped') return 'border border-dashed border-ink-400 bg-transparent'
  return 'bg-ink-300'
}

function laneChipClass(lane: string): string {
  if (lane === 'shared') return 'text-ink-500'
  if (lane === 'A') return 'text-sky-700'
  if (lane === 'B') return 'text-teal-700'
  return 'text-amber-800'
}

/** Group Shared → A → B… for the rail; keep execution index for numbering. */
function groupByLane(
  items: PipelineStackItem[],
  laneOf: Map<string, string>,
): Array<{ item: PipelineStackItem; execIndex: number; lane: string }> {
  const numbered = items.map((item, i) => ({
    item,
    execIndex: i + 1,
    lane: laneOf.get(item.id) || 'shared',
  }))
  const laneOrder: string[] = ['shared']
  for (const row of numbered) {
    if (row.lane !== 'shared' && !laneOrder.includes(row.lane)) laneOrder.push(row.lane)
  }
  const out: Array<{ item: PipelineStackItem; execIndex: number; lane: string }> = []
  for (const lane of laneOrder) {
    for (const row of numbered) {
      if (row.lane === lane) out.push(row)
    }
  }
  return out
}

export function PipelineStack({
  items,
  value,
  onChange,
  className,
  laneOf,
  laneTitle,
  progressOf,
}: {
  items: PipelineStackItem[]
  /** null = All (whole run). */
  value: string | null
  onChange: (id: string | null) => void
  className?: string
  /** When fork/parallel, id → shared | A | B — groups the rail under section headers. */
  laneOf?: Map<string, string> | null
  /** Lane header text (e.g. "Path B (Simple CNN · 30 epochs)"); default "Path B". */
  laneTitle?: (lane: string) => string | null | undefined
  /** Live node_progress for a running step (progress bar under its label). */
  progressOf?: (id: string) => NodeProgress | null
}) {
  const visible = items.filter(
    (item) => !looksLikeOpaqueId(item.id) && !looksLikeOpaqueId(String(item.label || '')),
  )
  if (visible.length === 0) return null

  const multiTrack =
    Boolean(laneOf) &&
    visible.some((it) => {
      const lane = laneOf!.get(it.id)
      return Boolean(lane && lane !== 'shared')
    })

  const rows = multiTrack && laneOf
    ? groupByLane(visible, laneOf)
    : visible.map((item, i) => ({ item, execIndex: i + 1, lane: 'shared' }))

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
        aria-pressed={value == null}
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
        {rows.map((row, idx) => {
          const { item, execIndex, lane } = row
          const active = value != null && focusMatchesNode(value, item.id)
          const label =
            item.label && !looksLikeOpaqueId(item.label)
              ? item.label
              : humanNodeLabel(item.id)
          const statusText = item.status === 'skipped' ? 'skipped (not run)' : item.status
          const prog = item.status === 'running' || item.status == null ? progressOf?.(item.id) ?? null : null
          const prevLane = idx > 0 ? rows[idx - 1].lane : null
          const showLaneHeader = multiTrack && lane !== prevLane
          return (
            <Fragment key={item.id}>
              {showLaneHeader ? (
                <li className="list-none px-2.5 pb-0.5 pt-1.5 first:pt-0.5">
                  <span
                    className={clsx(
                      'text-[10px] font-semibold uppercase tracking-wide',
                      laneChipClass(lane),
                    )}
                  >
                    {(lane !== 'shared' && laneTitle?.(lane)) || laneLabel(lane)}
                  </span>
                </li>
              ) : null}
              <li>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChange(item.id)}
                  title={`${label}${statusText ? ` · ${statusText}` : ''} · ${item.id}`}
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
                    {execIndex}
                  </span>
                  <span
                    className={clsx(
                      'min-w-0 flex-1 text-sm font-medium leading-snug',
                      item.status === 'skipped' ? 'text-ink-400' : 'text-ink-900',
                    )}
                  >
                    {label}
                    {item.status === 'skipped' ? (
                      <span className="block text-[10px] font-normal text-ink-400">not run</span>
                    ) : null}
                    {prog ? (
                      <span className="mt-1 block" aria-live="polite">
                        {prog.pct != null ? (
                          <span className="block h-1 overflow-hidden rounded-full bg-ink-100">
                            <span
                              className="block h-full rounded-full bg-sky-500 transition-[width]"
                              style={{ width: `${Math.max(2, prog.pct)}%` }}
                            />
                          </span>
                        ) : null}
                        <span className="mt-0.5 block truncate text-[10px] font-normal tabular-nums text-ink-500">
                          {progressBadgeText(prog)}
                        </span>
                      </span>
                    ) : null}
                  </span>
                  {item.status ? (
                    <span
                      className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', statusDotClass(item.status))}
                      aria-label={statusText}
                    />
                  ) : null}
                </button>
              </li>
            </Fragment>
          )
        })}
      </ol>
    </nav>
  )
}
