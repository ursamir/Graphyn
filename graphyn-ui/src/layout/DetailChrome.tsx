/**
 * Compact detail-pane header: title row + optional meta + actions.
 * Prefer this over tall card stacks in the detail pane.
 */
import React from 'react'
import clsx from 'clsx'

type DetailChromeProps = {
  title: React.ReactNode
  meta?: React.ReactNode
  actions?: React.ReactNode
  /** Soft alert / status strip under the header (failed run, etc.). */
  banner?: React.ReactNode
  children?: React.ReactNode
  className?: string
}

export function DetailChrome({ title, meta, actions, banner, children, className }: DetailChromeProps) {
  return (
    <div className={clsx('space-y-3', className)}>
      <div className="rounded-xl border border-ink-200/80 bg-white px-3.5 py-2.5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0 flex flex-wrap items-center gap-2">
            <div className="min-w-0 text-[14px] font-semibold text-ink-950">{title}</div>
            {meta}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
        </div>
        {banner ? <div className="mt-2">{banner}</div> : null}
      </div>
      {children}
    </div>
  )
}

/** Horizontally scrollable chip row — avoids Focus overflow wrapping the pane. */
export function FocusChipRow({
  label = 'Focus',
  children,
  hint,
  title,
}: {
  label?: string
  children: React.ReactNode
  hint?: string
  title?: string
}) {
  return (
    <div className="min-w-0 space-y-1" title={title || hint}>
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
          {label}
        </span>
        <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto pb-0.5 [scrollbar-width:thin]">
          {children}
        </div>
      </div>
      {hint ? <p className="text-[11px] text-ink-400">{hint}</p> : null}
    </div>
  )
}
