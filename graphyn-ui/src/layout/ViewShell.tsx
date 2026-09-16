/**
 * Container + Content shell for every feature view.
 * Container = title / description / actions; Content = fill body below.
 */
import React from 'react'
import clsx from 'clsx'

type ViewShellProps = {
  title: string
  description?: string
  actions?: React.ReactNode
  /** Optional second row under the title (tabs, filters). */
  toolbar?: React.ReactNode
  children: React.ReactNode
  className?: string
  /** Extra class on the content (body) region. */
  contentClassName?: string
}

export function ViewShell({
  title,
  description,
  actions,
  toolbar,
  children,
  className,
  contentClassName,
}: ViewShellProps) {
  return (
    <div className={clsx('flex h-full min-h-0 flex-col', className)}>
      <div className="relative z-10 shrink-0 border-b border-ink-200/70 bg-white/90 px-5 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-type-page text-ink-950">{title}</h1>
            {description ? (
              <p className="mt-0.5 text-type-meta text-ink-400">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
        {toolbar ? <div className="mt-2.5">{toolbar}</div> : null}
      </div>
      <div className={clsx('min-h-0 flex-1 overflow-hidden', contentClassName)}>{children}</div>
    </div>
  )
}
