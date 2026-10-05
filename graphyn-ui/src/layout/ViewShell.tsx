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
  /** Optional tabs/filters — second row by default, or inline beside the title. */
  toolbar?: React.ReactNode
  /**
   * When true, title + toolbar + actions share one row (dense IDE pages like Runs).
   * Description, if present, still sits under the title on a second line.
   */
  inlineToolbar?: boolean
  children: React.ReactNode
  className?: string
  /** Extra class on the content (body) region. */
  contentClassName?: string
  /** Extra class on the page-shell-header. */
  headerClassName?: string
}

export function ViewShell({
  title,
  description,
  actions,
  toolbar,
  inlineToolbar = false,
  children,
  className,
  contentClassName,
  headerClassName,
}: ViewShellProps) {
  return (
    <div className={clsx('flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white', className)} data-shell-noscroll>
      <div className={clsx('page-shell-header relative z-10', inlineToolbar && '!py-1.5', headerClassName)}>
        {inlineToolbar ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <div className="min-w-0 max-w-full">
              <h1 className="text-[15px] font-semibold leading-tight tracking-tight text-ink-950">
                {title}
              </h1>
              {description ? (
                <p className="mt-0.5 text-type-meta text-ink-500">{description}</p>
              ) : null}
            </div>
            {toolbar ? <div className="min-w-0 max-w-full">{toolbar}</div> : null}
            {actions ? (
              <div className="ml-auto flex min-w-0 max-w-full flex-wrap items-center justify-end gap-1.5">{actions}</div>
            ) : null}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <h1 className="text-[15px] font-semibold leading-tight tracking-tight text-ink-950">
                  {title}
                </h1>
                {description ? (
                  <p className="mt-0.5 text-type-meta text-ink-500">{description}</p>
                ) : null}
              </div>
              {actions ? (
                <div className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5">{actions}</div>
              ) : null}
            </div>
            {toolbar ? <div className="mt-2">{toolbar}</div> : null}
          </>
        )}
      </div>
      <div className={clsx('min-h-0 flex-1 overflow-hidden bg-[var(--surface-muted)]', contentClassName)}>
        {children}
      </div>
    </div>
  )
}
